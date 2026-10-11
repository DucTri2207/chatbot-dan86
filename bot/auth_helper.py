"""
Trợ thủ xử lý thông tin đăng nhập và trích xuất Cookies siêu nhẹ (Auth Helper) cho DAN86.
Tái sử dụng trực tiếp Profile Chrome và cookies sẵn có tại d:\\dan86 (d:\\dan86\\.chrome_profile
và d:\\dan86\\dan86_saved_cookies.json).
Không tạo thêm thư mục profile nặng máy, trích xuất ra state/fb_storage_state.json chỉ ~3.8 KB.
"""

import base64
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
) -> Dict[str, Any]:
    """
    Tự động đồng bộ cookies từ d:\\dan86 sang state/fb_storage_state.json và state/GITHUB_SECRET_VALUE.txt.
    Thao tác trong 0.05s, dung lượng cực nhẹ ~3.8 KB.
    """
    os.makedirs(os.path.dirname(storage_path) or STATE_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(secret_path) or STATE_DIR, exist_ok=True)

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
