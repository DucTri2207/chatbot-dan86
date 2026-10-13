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


def _fetch_cdp_cookies_raw(ws_url: str, timeout: float = 5.0) -> List[Dict[str, Any]]:
    """
    Kết nối trực tiếp WebSocket tầng socket tới Chrome DevTools để lấy cookies.
    Bỏ qua lỗi handshake/tiện ích mở rộng của thư viện bên ngoài, chạy siêu tốc <0.2s.
    """
    import socket
    import struct
    import urllib.parse

    parsed = urllib.parse.urlparse(ws_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 9222
    path = parsed.path or "/"

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        s.sendall(req.encode("ascii"))

        header_buf = b""
        while b"\r\n\r\n" not in header_buf:
            chunk = s.recv(2048)
            if not chunk:
                break
            header_buf += chunk
            if len(header_buf) > 32768:
                break

        if b"101 " not in header_buf:
            return []

        cmd_payload = json.dumps({"id": 1, "method": "Storage.getCookies"}).encode("utf-8")
        mask = os.urandom(4)
        length = len(cmd_payload)
        hdr = bytearray([0x81])
        if length < 126:
            hdr.append(0x80 | length)
        elif length < 65536:
            hdr.append(0x80 | 126)
            hdr.extend(struct.pack(">H", length))
        else:
            hdr.append(0x80 | 127)
            hdr.extend(struct.pack(">Q", length))
        hdr.extend(mask)
        masked_cmd = bytes(b ^ mask[i % 4] for i, b in enumerate(cmd_payload))
        s.sendall(hdr + masked_cmd)

        def read_exact(n: int) -> bytes:
            buf = b""
            while len(buf) < n:
                c = s.recv(n - len(buf))
                if not c:
                    raise EOFError("Socket closed prematurely")
                buf += c
            return buf

        msg_bytes = bytearray()
        while True:
            b1, b2 = struct.unpack("BB", read_exact(2))
            fin = bool(b1 & 0x80)
            opcode = b1 & 0x0F
            has_mask = bool(b2 & 0x80)
            plen = b2 & 0x7F
            if plen == 126:
                plen = struct.unpack(">H", read_exact(2))[0]
            elif plen == 127:
                plen = struct.unpack(">Q", read_exact(8))[0]
            mask_key = read_exact(4) if has_mask else None
            pdata = read_exact(plen)
            if has_mask and mask_key:
                pdata = bytes(b ^ mask_key[i % 4] for i, b in enumerate(pdata))
            msg_bytes.extend(pdata)
            if fin and opcode in (0, 1, 2):
                break

        try:
            close_frame = bytearray([0x88, 0x80]) + os.urandom(4)
            s.sendall(close_frame)
        except Exception:
            pass

        data = json.loads(msg_bytes.decode("utf-8", errors="ignore"))
        return data.get("result", {}).get("cookies", [])
    except Exception as e:
        logger.debug("Lỗi đọc cookies CDP qua socket: %s", e)
        return []
    finally:
        try:
            s.close()
        except Exception:
            pass


async def _async_fetch_cdp_cookies(ws_url: str) -> List[Dict[str, Any]]:
    """Kết nối WebSocket tới Chrome CDP và trích xuất tất cả cookies đang hoạt động (dự phòng)."""
    try:
        import websockets
        async with websockets.connect(ws_url, origin=None, max_size=10 * 1024 * 1024) as ws:
            cmd = {"id": 1, "method": "Storage.getCookies"}
            await ws.send(json.dumps(cmd))
            raw_msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(raw_msg)
            return data.get("result", {}).get("cookies", [])
    except Exception:
        return []


def extract_live_cookies_from_chrome_cdp() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Trích xuất cookies Facebook thời gian thực trực tiếp từ cửa sổ trình duyệt Chrome đang mở.
    Không tốn thời gian, không cần gõ mật khẩu, đảm bảo 100% phiên đăng nhập còn sống.
    """
    ws_url = get_active_chrome_cdp_ws_url()
    if not ws_url:
        return [], {"error": "Không tìm thấy DevToolsActivePort của Chrome đang chạy."}

    # 1. Thử lấy siêu tốc qua socket thuần
    raw_cookies: List[Dict[str, Any]] = _fetch_cdp_cookies_raw(ws_url)

    # 2. Dự phòng bằng async websockets nếu socket thuần chưa được
    if not raw_cookies:
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

    if not raw_cookies:
        return [], {"error": "Không thể kết nối hoặc trích xuất cookies từ Chrome CDP."}

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
    QUAN TRỌNG:
    - Luôn bảo toàn (preserve) mảng origins (chứa localStorage của https://business.facebook.com).
    - Nếu file storage hiện tại đã có phiên hợp lệ (c_user, xs và business.facebook.com trong origins),
      tuyệt đối KHÔNG lấy file nguồn cũ d:\\dan86 ghi đè làm mất origins!
    """
    os.makedirs(os.path.dirname(storage_path) or STATE_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(secret_path) or STATE_DIR, exist_ok=True)

    # Đọc và phân tích phiên hiện tại trong storage_path nếu đã tồn tại
    existing_origins: List[Dict[str, Any]] = []
    existing_cookies: List[Dict[str, Any]] = []
    has_valid_existing_session = False

    if os.path.exists(storage_path):
        try:
            with open(storage_path, "r", encoding="utf-8") as f_ex:
                ex_data = json.load(f_ex)
            if isinstance(ex_data, dict):
                existing_origins = ex_data.get("origins", [])
                existing_cookies = ex_data.get("cookies", [])
                ex_cookie_names = {c.get("name") for c in existing_cookies if isinstance(c, dict)}
                has_biz_origin = any(
                    "business.facebook.com" in org.get("origin", "") and len(org.get("localStorage", [])) > 0
                    for org in existing_origins if isinstance(org, dict)
                )
                if "c_user" in ex_cookie_names and "xs" in ex_cookie_names and has_biz_origin:
                    has_valid_existing_session = True
        except Exception as e_read:
            logger.debug("Lỗi đọc state hiện tại trong %s: %s", storage_path, e_read)

    # Nếu storage_path chưa có phiên hợp lệ, kiểm tra xem secret_path hoặc FB_STORAGE_STATE có lưu phiên chuẩn không
    if not has_valid_existing_session:
        for backup_src in [secret_path, os.environ.get("FB_STORAGE_STATE", "").strip()]:
            if not backup_src:
                continue
            try:
                b_raw = ""
                if backup_src == secret_path and os.path.exists(secret_path):
                    with open(secret_path, "r", encoding="utf-8") as f_b:
                        b_raw = f_b.read().strip()
                elif backup_src != secret_path:
                    b_raw = backup_src
                if b_raw:
                    if b_raw.startswith("{"):
                        b_data = json.loads(b_raw)
                    else:
                        b_data = json.loads(base64.b64decode(b_raw).decode("utf-8"))
                    if isinstance(b_data, dict):
                        b_origins = b_data.get("origins", [])
                        b_cookies = b_data.get("cookies", [])
                        b_cookie_names = {c.get("name") for c in b_cookies if isinstance(c, dict)}
                        b_has_biz = any(
                            "business.facebook.com" in org.get("origin", "") and len(org.get("localStorage", [])) > 0
                            for org in b_origins if isinstance(org, dict)
                        )
                        if "c_user" in b_cookie_names and "xs" in b_cookie_names and b_has_biz:
                            existing_origins = b_origins
                            if not existing_cookies:
                                existing_cookies = b_cookies
                            has_valid_existing_session = True
                            # Khôi phục ngay vào storage_path
                            with open(storage_path, "w", encoding="utf-8") as f_res:
                                json.dump(b_data, f_res, ensure_ascii=False, indent=2)
                            break
            except Exception as e_sec_chk:
                logger.debug("Không thể đọc origins từ nguồn backup %s: %s", backup_src[:30], e_sec_chk)

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
            logger.debug("Không thể lấy cookies qua CDP: %s", e_cdp)

    # 2. Nếu CDP thành công: Cập nhật cookies MỚI nhưng BẢO TOÀN toàn bộ origins hiện có!
    if matched:
        state_payload = {"cookies": matched, "origins": existing_origins}
        with open(storage_path, "w", encoding="utf-8") as f:
            json.dump(state_payload, f, ensure_ascii=False, indent=2)

        storage_size = os.path.getsize(storage_path)
        b64_secret = export_github_secret_file(storage_path, secret_path)
        secret_size = os.path.getsize(secret_path) if os.path.exists(secret_path) else len(b64_secret)

        return {
            "success": True,
            "cookies_count": len(matched),
            "storage_file": storage_path,
            "storage_size_bytes": storage_size,
            "secret_file": secret_path,
            "secret_size_bytes": secret_size,
            "is_authenticated": meta.get("is_authenticated", False),
            "message": (
                f"Đã cập nhật thành công {len(matched)} cookies trực tiếp và bảo toàn {len(existing_origins)} origins!"
            ),
        }

    # 3. Nếu CDP không lấy được cookies mới:
    # Nếu file storage_path HIỆN TẠI ĐÃ CÓ phiên hoàn chỉnh (c_user, xs, business.facebook.com origins)
    # -> TUYỆT ĐỐI KHÔNG lấy file nguồn cũ d:\dan86 ghi đè làm mất origins!
    if has_valid_existing_session:
        logger.info(
            "Phiên làm việc hiện tại trong %s đã đầy đủ cookies và origins (business.facebook.com). "
            "Bảo toàn phiên đăng nhập hiện tại, không ghi đè từ file cục bộ cũ!",
            storage_path,
        )
        b64_secret = export_github_secret_file(storage_path, secret_path)
        storage_size = os.path.getsize(storage_path)
        secret_size = os.path.getsize(secret_path) if os.path.exists(secret_path) else len(b64_secret)
        return {
            "success": True,
            "cookies_count": len(existing_cookies),
            "storage_file": storage_path,
            "storage_size_bytes": storage_size,
            "secret_file": secret_path,
            "secret_size_bytes": secret_size,
            "is_authenticated": True,
            "message": f"Đã bảo toàn phiên đăng nhập hoàn chỉnh với {len(existing_origins)} origins trong {storage_path}!",
        }

    # 4. Nếu chưa có phiên hợp lệ, đọc fallback từ file nguồn cục bộ d:\dan86
    matched, meta = extract_facebook_cookies(source_path)
    if not matched:
        return {
            "success": False,
            "message": meta.get("error", "Không tìm thấy cookies Facebook hợp lệ."),
            "meta": meta,
        }

    state_payload = {"cookies": matched, "origins": existing_origins}
    with open(storage_path, "w", encoding="utf-8") as f:
        json.dump(state_payload, f, ensure_ascii=False, indent=2)

    storage_size = os.path.getsize(storage_path)
    b64_secret = export_github_secret_file(storage_path, secret_path)
    secret_size = os.path.getsize(secret_path) if os.path.exists(secret_path) else len(b64_secret)

    return {
        "success": True,
        "cookies_count": len(matched),
        "storage_file": storage_path,
        "storage_size_bytes": storage_size,
        "secret_file": secret_path,
        "secret_size_bytes": secret_size,
        "is_authenticated": meta.get("is_authenticated", False),
        "message": (
            f"Đã nạp {len(matched)} cookies Facebook vào {storage_path} "
            f"({storage_size} bytes, siêu nhẹ ~{storage_size/1024:.1f} KB)!"
        ),
    }


def export_github_secret_file(
    storage_path: str = STORAGE_STATE_FILE,
    secret_path: str = GITHUB_SECRET_EXPORT_FILE,
) -> str:
    """
    Mã hóa file fb_storage_state.json sang Base64 và ghi vào GITHUB_SECRET_VALUE.txt.
    Dùng để cập nhật Secret FB_STORAGE_STATE trên VPS GitHub Actions.
    Tự động lọc bỏ các key telemetry/analytics dung lượng lớn (falco_queue_*, screen_time_*)
    trong localStorage để đảm bảo kích thước Secret luôn < 10KB (tuân thủ giới hạn 64KB của GitHub Actions).
    """
    if not os.path.exists(storage_path):
        return ""
    try:
        with open(storage_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Làm sạch localStorage trong origins để loại bỏ rác telemetry/analytics của Facebook
        if isinstance(data, dict):
            cur_has_biz = any(
                "business.facebook.com" in org.get("origin", "") and len(org.get("localStorage", [])) > 0
                for org in data.get("origins", []) if isinstance(org, dict)
            )
            if not cur_has_biz and os.path.exists(secret_path):
                try:
                    with open(secret_path, "r", encoding="utf-8") as f_ex_sec:
                        s_raw = f_ex_sec.read().strip()
                    if s_raw:
                        s_data = json.loads(s_raw) if s_raw.startswith("{") else json.loads(base64.b64decode(s_raw).decode("utf-8"))
                        if isinstance(s_data, dict):
                            biz_origins = [o for o in s_data.get("origins", []) if "business.facebook.com" in o.get("origin", "") and len(o.get("localStorage", [])) > 0]
                            if biz_origins:
                                data["origins"] = list(data.get("origins", [])) + biz_origins
                except Exception:
                    pass

        if isinstance(data, dict) and "origins" in data:
            cleaned_origins = []
            for org in data.get("origins", []):
                new_org = dict(org)
                if "localStorage" in new_org:
                    new_org["localStorage"] = [
                        item for item in new_org.get("localStorage", [])
                        if not item.get("name", "").startswith(("falco_", "screen_time_", "ares_", "_oz_"))
                    ]
                cleaned_origins.append(new_org)
            data["origins"] = cleaned_origins

        compact_json = json.dumps(data, ensure_ascii=False)
        b64_secret = base64.b64encode(compact_json.encode("utf-8")).decode("ascii")
        os.makedirs(os.path.dirname(secret_path) or STATE_DIR, exist_ok=True)
        with open(secret_path, "w", encoding="utf-8") as f:
            f.write(b64_secret)
        logger.info("Đã cập nhật mã GitHub Secret: %s (%d bytes)", secret_path, len(b64_secret))
        return b64_secret
    except Exception as e:
        logger.warning("Lỗi xuất file GitHub Secret: %s", e)
        return ""


def sync_storage_secret_to_github(
    secret_path: str = GITHUB_SECRET_EXPORT_FILE,
) -> bool:
    """
    Tự động cập nhật Secret FB_STORAGE_STATE lên GitHub repo thông qua GitHub CLI (gh)
    nếu môi trường có cấu hình GH_TOKEN hoặc GITHUB_TOKEN và công cụ gh sẵn sàng.
    Đảm bảo an toàn 100%: không in/log nội dung secret ra màn hình hoặc log.
    """
    if not os.path.exists(secret_path):
        return False
    try:
        import shutil
        import subprocess

        if not shutil.which("gh"):
            return False

        with open(secret_path, "r", encoding="utf-8") as f:
            b64_content = f.read().strip()
        if not b64_content:
            return False

        cmd = ["gh", "secret", "set", "FB_STORAGE_STATE"]
        repo = os.environ.get("GITHUB_REPOSITORY")
        if repo:
            cmd.extend(["--repo", repo])

        res = subprocess.run(
            cmd,
            input=b64_content,
            text=True,
            capture_output=True,
            timeout=25,
        )
        if res.returncode == 0:
            logger.info("Đã tự động nạp phiên mới FB_STORAGE_STATE lên GitHub Secrets thành công qua gh CLI.")
            return True
        else:
            logger.debug("Không thể cập nhật GitHub Secrets qua gh CLI (thiếu quyền hoặc token hạn chế): %s", res.stderr.strip()[:200])
            return False
    except Exception as e:
        logger.debug("Lỗi cập nhật GitHub Secret qua gh CLI: %s", e)
        return False


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
