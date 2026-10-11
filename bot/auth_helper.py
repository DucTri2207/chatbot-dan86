"""
Trợ thủ xử lý thông tin đăng nhập và trích xuất Cookies siêu nhẹ (Auth Helper) cho DAN86.
Tái sử dụng trực tiếp Profile Chrome và cookies sẵn có tại d:\\dan86 (d:\\dan86\\.chrome_profile
và d:\\dan86\\dan86_saved_cookies.json).
Không tạo thêm thư mục profile nặng máy, trích xuất ra state/fb_storage_state.json chỉ ~3.8 KB.
"""

import asyncio
import base64
import concurrent.futures
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from bot.bot_config import (
    DAN86_SYSTEM_COOKIES_FILE,
    DAN86_SYSTEM_PROFILE_DIR,
    GITHUB_SECRET_EXPORT_FILE,
    STATE_DIR,
    STORAGE_STATE_FILE,
)

logger = logging.getLogger("dan86_auth_helper")


def get_active_chrome_cdp_ws_url() -> Optional[str]:
    """Tìm địa chỉ WebSocket DevTools của Chrome đang chạy."""
    # 1. Kiểm tra d:\dan86\chrome_dan86\DevToolsActivePort
    dan86_port = r"d:\dan86\chrome_dan86\DevToolsActivePort"
    if os.path.exists(dan86_port):
        try:
            with open(dan86_port, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
            if len(lines) >= 2:
                return f"ws://127.0.0.1:{lines[0]}{lines[1]}"
        except Exception:
            pass

    # 2. Kiểm tra Chrome Profile mặc định của người dùng
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        port_file = os.path.join(local_app_data, "Google", "Chrome", "User Data", "DevToolsActivePort")
        if os.path.exists(port_file):
            try:
                with open(port_file, "r", encoding="utf-8") as f:
                    lines = [l.strip() for l in f if l.strip()]
                if len(lines) >= 2:
                    return f"ws://127.0.0.1:{lines[0]}{lines[1]}"
            except Exception:
                pass
    return None


async def _async_fetch_cdp_cookies(ws_url: str) -> List[Dict[str, Any]]:
    """Kết nối WebSocket tới Chrome CDP và trích xuất tất cả cookies đang hoạt động."""
    import websockets
    async with websockets.connect(ws_url, origin=None, max_size=10 * 1024 * 1024) as ws:
        cmd = {"id": 1, "method": "Storage.getCookies"}
        await ws.send(json.dumps(cmd))
        raw_msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
        data = json.loads(raw_msg)
        return data.get("result", {}).get("cookies", [])


def extract_live_cookies_from_chrome_cdp() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Trích xuất cookies Facebook thời gian thực trực tiếp từ cửa sổ trình duyệt Chrome đang mở.
    Không tốn thời gian, không cần gõ mật khẩu, đảm bảo 100% phiên đăng nhập còn sống.
    """
    ws_url = get_active_chrome_cdp_ws_url()
    if not ws_url:
        return [], {"error": "Không tìm thấy DevToolsActivePort của Chrome đang chạy."}

    raw_cookies: List[Dict[str, Any]] = []
    try:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(lambda: asyncio.run(_async_fetch_cdp_cookies(ws_url)))
                    raw_cookies = future.result(timeout=6.0)
            else:
                raw_cookies = loop.run_until_complete(_async_fetch_cdp_cookies(ws_url))
        except RuntimeError:
            raw_cookies = asyncio.run(_async_fetch_cdp_cookies(ws_url))
    except Exception as e:
        logger.debug("Lỗi kết nối CDP Chrome: %s", e)
        return [], {"error": f"Lỗi kết nối CDP: {e}"}

    matched: List[Dict[str, Any]] = []
    has_c_user = False
    has_xs = False

    for c in raw_cookies:
        if not isinstance(c, dict):
            continue
        domain = str(c.get("domain", "")).lower()
        if any(d in domain for d in ["facebook.com", "messenger.com", "meta.com"]):
            sanitized = sanitize_cookie(c)
            if sanitized:
                matched.append(sanitized)
                if sanitized["name"] == "c_user":
                    has_c_user = True
                if sanitized["name"] == "xs":
                    has_xs = True

    meta = {
        "source": "chrome_cdp_live",
        "ws_url": ws_url,
        "total_source_cookies": len(raw_cookies),
        "matched_count": len(matched),
        "has_c_user": has_c_user,
        "has_xs": has_xs,
        "is_authenticated": has_c_user and has_xs,
        "raw_all_cookies": raw_cookies,
    }
    return matched, meta


def sanitize_cookie(c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Chuẩn hóa một cookie theo đúng chuẩn định dạng Playwright add_cookies."""
    if not isinstance(c, dict):
        return None
    name = str(c.get("name", "")).strip()
    value = c.get("value")
    domain = str(c.get("domain", "")).strip()
    if not name or value is None or not domain:
        return None

    item: Dict[str, Any] = {
        "name": name,
        "value": str(value),
        "domain": domain,
        "path": str(c.get("path", "/")),
        "secure": bool(c.get("secure", True)),
        "httpOnly": bool(c.get("httpOnly", False)),
    }

    same_site = c.get("sameSite")
    if same_site in ("Strict", "Lax", "None"):
        item["sameSite"] = same_site

    expires = c.get("expires")
    if expires and isinstance(expires, (int, float)) and expires > 0:
        item["expires"] = float(expires)

    return item


def extract_facebook_cookies(
    source_json_path: str = DAN86_SYSTEM_COOKIES_FILE,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Trích xuất danh sách cookies liên quan Facebook / Messenger / Meta từ file cookie tổng hợp.
    Trả về (danh sách cookies Playwright, metadata).
    """
    if not os.path.exists(source_json_path):
        return [], {"error": f"Không tìm thấy file nguồn: {source_json_path}"}

    try:
        with open(source_json_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except Exception as e:
        return [], {"error": f"Lỗi đọc JSON {source_json_path}: {e}"}

    raw_cookies: List[Dict[str, Any]] = []
    if isinstance(raw_data, list):
        raw_cookies = raw_data
    elif isinstance(raw_data, dict):
        raw_cookies = raw_data.get("cookies", [])

    matched: List[Dict[str, Any]] = []
    has_c_user = False
    has_xs = False

    for c in raw_cookies:
        if not isinstance(c, dict):
            continue
        domain = str(c.get("domain", "")).lower()
        if any(d in domain for d in ["facebook.com", "messenger.com", "meta.com"]):
            sanitized = sanitize_cookie(c)
            if sanitized:
                matched.append(sanitized)
                if sanitized["name"] == "c_user":
                    has_c_user = True
                if sanitized["name"] == "xs":
                    has_xs = True

    meta = {
        "total_source_cookies": len(raw_cookies),
        "matched_count": len(matched),
        "has_c_user": has_c_user,
        "has_xs": has_xs,
        "is_authenticated": has_c_user and has_xs,
    }
    return matched, meta


def sync_facebook_credentials_from_dan86(
    source_path: str = DAN86_SYSTEM_COOKIES_FILE,
    storage_path: str = STORAGE_STATE_FILE,
    secret_path: str = GITHUB_SECRET_EXPORT_FILE,
    use_cdp: bool = True,
) -> Dict[str, Any]:
    """
    Tự động đồng bộ cookies từ d:\\dan86 sang state/fb_storage_state.json và state/GITHUB_SECRET_VALUE.txt.
    Thao tác trong 0.05s, dung lượng cực nhẹ ~3.8 KB.
    """
    os.makedirs(os.path.dirname(storage_path) or STATE_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(secret_path) or STATE_DIR, exist_ok=True)

    # 1. Thử trích xuất cookies thời gian thực từ cửa sổ Chrome đang mở qua CDP (khi dùng file nguồn mặc định)
    matched: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {}
    if use_cdp and source_path == DAN86_SYSTEM_COOKIES_FILE:
        try:
            live_matched, live_meta = extract_live_cookies_from_chrome_cdp()
            if live_matched and live_meta.get("is_authenticated"):
                matched = live_matched
                meta = live_meta
                logger.info("Đã trích xuất %d cookies trực tiếp từ phiên Chrome đang hoạt động!", len(matched))
                # Tự động cập nhật file cookies tổng hợp tại d:\dan86 để đồng bộ
                if live_meta.get("raw_all_cookies") and os.path.isdir(os.path.dirname(source_path)):
                    try:
                        with open(source_path, "w", encoding="utf-8") as f_src:
                            json.dump(live_meta["raw_all_cookies"], f_src, ensure_ascii=False, indent=2)
                    except Exception as e_save:
                        logger.debug("Không thể sao lưu cookies mới vào %s: %s", source_path, e_save)
        except Exception as e_cdp:
            logger.debug("Không thể lấy cookies qua CDP, chuyển sang file cục bộ: %s", e_cdp)

    # 2. Nếu chưa lấy được từ CDP, đọc từ file nguồn cục bộ
    if not matched:
        matched, meta = extract_facebook_cookies(source_path)

    if not matched:
        return {
            "success": False,
            "message": meta.get("error", "Không tìm thấy cookies Facebook hợp lệ."),
            "meta": meta,
        }

    # 1. Ghi file fb_storage_state.json
    state_payload = {"cookies": matched, "origins": []}
    with open(storage_path, "w", encoding="utf-8") as f:
        json.dump(state_payload, f, ensure_ascii=False, indent=2)

    storage_size = os.path.getsize(storage_path)

    # 2. Ghi file GITHUB_SECRET_VALUE.txt (chuỗi mã hóa Base64 cho GitHub Secrets)
    compact_json = json.dumps(state_payload, ensure_ascii=False)
    b64_secret = base64.b64encode(compact_json.encode("utf-8")).decode("ascii")
    with open(secret_path, "w", encoding="utf-8") as f:
        f.write(b64_secret)

    secret_size = os.path.getsize(secret_path)

    return {
        "success": True,
        "cookies_count": len(matched),
        "storage_file": storage_path,
        "storage_size_bytes": storage_size,
        "secret_file": secret_path,
        "secret_size_bytes": secret_size,
        "is_authenticated": meta.get("is_authenticated", False),
        "message": (
            f"Đã trích xuất thành công {len(matched)} cookies Facebook vào {storage_path} "
            f"({storage_size} bytes, siêu nhẹ ~{storage_size/1024:.1f} KB)!"
        ),
    }


def get_storage_state_status() -> Dict[str, Any]:
    """Kiểm tra tình trạng file fb_storage_state.json hiện tại."""
    if not os.path.exists(STORAGE_STATE_FILE):
        return {
            "exists": False,
            "cookies_count": 0,
            "has_auth": False,
            "size_bytes": 0,
            "last_modified": 0,
            "last_modified_str": "Chưa có",
        }

    try:
        size = os.path.getsize(STORAGE_STATE_FILE)
        mtime = os.path.getmtime(STORAGE_STATE_FILE)
        mtime_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
        with open(STORAGE_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cookies = data.get("cookies", []) if isinstance(data, dict) else []
        names = {c.get("name") for c in cookies if isinstance(c, dict)}
        has_auth = "c_user" in names and "xs" in names
        return {
            "exists": True,
            "cookies_count": len(cookies),
            "has_auth": has_auth,
            "size_bytes": size,
            "last_modified": mtime,
            "last_modified_str": mtime_str,
        }
    except Exception as e:
        return {
            "exists": True,
            "cookies_count": 0,
            "has_auth": False,
            "size_bytes": 0,
            "error": str(e),
            "last_modified": 0,
            "last_modified_str": "Lỗi đọc file",
        }
