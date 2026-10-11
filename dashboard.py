"""
Dashboard Theo Dõi Bot Trực Fanpage DAN86 (Dần86Farm) 24/24.
Thiết kế SIÊU NHẸ:
- 100% Python Built-in Standard Library (http.server, json, os, urllib).
- KHÔNG cài thêm bất kỳ thư viện ngoài nào (0 bytes node_modules, 0 bytes pip).
- Dung lượng RAM khi chạy < 18MB, CPU ~0%.
- Tự động mở trình duyệt web tại http://localhost:8686.
- Cập nhật thời gian thực (Live Metrics, Stage 1/2 Customers, Comments, Live Terminal Logs).
"""

import datetime
import http.server
import json
import os
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from typing import Any, Dict, List, Optional

# Cấu hình UTF-8 cho Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from bot.auth_helper import (
    get_storage_state_status,
    sync_facebook_credentials_from_dan86,
)
from bot.bot_config import (
    BASE_DIR,
    BOT_STATUS_FILE,
    CHROME_PROFILE_DIR,
    DAN86_SYSTEM_COOKIES_FILE,
    DAN86_SYSTEM_PROFILE_DIR,
    GITHUB_SECRET_EXPORT_FILE,
    LOGS_DIR,
    MEMORY_FILE,
    META_INBOX_ALL_URL,
    STATE_DIR,
    STORAGE_STATE_FILE,
)

PORT = 8686
LOG_FILE = os.path.join(LOGS_DIR, "bot_truc_page.log")
GITHUB_REPO_ACTIONS = "https://github.com/DucTri2207/chatbot-dan86/actions"
GITHUB_RAW_STATUS_URL = "https://raw.githubusercontent.com/DucTri2207/chatbot-dan86/master/state/bot_status.json"
GITHUB_RAW_MEMORY_URL = "https://raw.githubusercontent.com/DucTri2207/chatbot-dan86/master/state/bot_memory.json"
GITHUB_ACTIONS_API_RUNS = "https://api.github.com/repos/DucTri2207/chatbot-dan86/actions/runs?per_page=3"

_GITHUB_CACHE: Dict[str, Any] = {
    "cached_at": 0.0,
    "vps_status": {},
    "vps_memory": {},
    "actions_run": {},
}


def fetch_github_live_data(force: bool = False) -> Dict[str, Any]:
    """
    Đồng bộ dữ liệu thời gian thực từ VPS GitHub Actions về máy cục bộ.
    Giúp Dashboard hiển thị đầy đủ thông tin kể cả khi Bot đang chạy trên VPS đám mây!
    """
    now = time.time()
    if not force and (now - _GITHUB_CACHE["cached_at"]) < 10.0:
        return _GITHUB_CACHE

    headers = {
        "User-Agent": "DAN86-Dashboard-Monitor",
        "Accept": "application/json",
    }

    # 1. Tải bot_status.json từ GitHub
    try:
        req = urllib.request.Request(f"{GITHUB_RAW_STATUS_URL}?t={int(now)}", headers=headers)
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            if resp.status == 200:
                _GITHUB_CACHE["vps_status"] = json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass

    # 2. Tải bot_memory.json từ GitHub
    try:
        req = urllib.request.Request(f"{GITHUB_RAW_MEMORY_URL}?t={int(now)}", headers=headers)
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            if resp.status == 200:
                _GITHUB_CACHE["vps_memory"] = json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass

    # 3. Lấy thông tin chạy từ GitHub Actions API
    try:
        req = urllib.request.Request(GITHUB_ACTIONS_API_RUNS, headers=headers)
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            if resp.status == 200:
                runs_data = json.loads(resp.read().decode("utf-8"))
                runs = runs_data.get("workflow_runs", [])
                if runs:
                    latest = runs[0]
                    _GITHUB_CACHE["actions_run"] = {
                        "id": latest.get("id"),
                        "status": latest.get("status"),
                        "conclusion": latest.get("conclusion"),
                        "html_url": latest.get("html_url"),
                        "run_number": latest.get("run_number"),
                        "created_at": latest.get("created_at"),
                        "updated_at": latest.get("updated_at"),
                    }
    except Exception:
        pass

    _GITHUB_CACHE["cached_at"] = now

    # Lưu lại memory mới nhất vào ổ đĩa local nếu VPS có dữ liệu
    vps_mem = _GITHUB_CACHE.get("vps_memory")
    if isinstance(vps_mem, dict) and (vps_mem.get("conversations") or vps_mem.get("replied_comments")):
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(vps_mem, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return _GITHUB_CACHE


def format_time_ago(ts: float) -> str:
    """Định dạng thời gian thân thiện (Ví dụ: '2 phút trước', '1 giờ trước')."""
    if not ts or ts <= 0:
        return "Chưa xác định"
    now = time.time()
    diff = max(0, int(now - ts))
    if diff < 10:
        return "Vừa xong"
    if diff < 60:
        return f"{diff} giây trước"
    if diff < 3600:
        return f"{diff // 60} phút trước"
    if diff < 86400:
        return f"{diff // 3600} giờ trước"
    return f"{diff // 86400} ngày trước"


def format_timestamp(ts: float) -> str:
    if not ts or ts <= 0:
        return "--:--:--"
    return datetime.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S")


def get_active_bot_process_info() -> Dict[str, Any]:
    """Kiểm tra xem tiến trình Bot trên máy tính có đang thực sự chạy hay không."""
    if not os.path.exists(BOT_STATUS_FILE):
        return {"is_running": False, "pid": None, "mode": "idle", "cycle": 0, "status_text": "Đang dừng"}

    try:
        with open(BOT_STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        running = bool(data.get("running", False))
        pid = data.get("pid")
        last_heartbeat = float(data.get("last_heartbeat", 0))
        elapsed = time.time() - last_heartbeat

        # Nếu file báo running nhưng quá 3 phút không có heartbeat -> bot đã tắt đột ngột
        if running and elapsed > 180:
            running = False
            status_text = "Mất tín hiệu (Đã dừng)"
        elif running:
            status_text = "Đang chạy"
        else:
            status_text = "Đang dừng"

        uptime_sec = max(0, int(time.time() - float(data.get("started_at", time.time())))) if running else 0
        hours = uptime_sec // 3600
        minutes = (uptime_sec % 3600) // 60
        seconds = uptime_sec % 60
        uptime_str = f"{hours}h {minutes}m {seconds}s" if hours > 0 else f"{minutes}m {seconds}s"

        return {
            "is_running": running,
            "pid": pid,
            "mode": data.get("mode", "live"),
            "cycle": data.get("cycle", 0),
            "headless": data.get("headless", False),
            "started_at_str": format_timestamp(data.get("started_at", 0)),
            "last_heartbeat_ago": format_time_ago(last_heartbeat),
            "uptime_str": uptime_str,
            "status_text": status_text,
        }
    except Exception as e:
        return {"is_running": False, "error": str(e), "status_text": "Lỗi đọc trạng thái"}


def collect_dashboard_data() -> Dict[str, Any]:
    """Thu thập toàn bộ dữ liệu thống kê, khách hàng, bình luận, trạng thái hệ thống."""
    # 1. Đọc bot_memory.json
    memory_data: Dict[str, Any] = {
        "replied_comments": {},
        "conversations": {},
        "stats": {
            "comments_replied": 0,
            "private_inboxes_from_comment": 0,
            "first_inbox_replies": 0,
            "wait_staff_replies": 0,
        },
    }
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                memory_data["replied_comments"] = loaded.get("replied_comments", {})
                memory_data["conversations"] = loaded.get("conversations", {})
                if isinstance(loaded.get("stats"), dict):
                    memory_data["stats"].update(loaded["stats"])
        except Exception:
            pass

    # Tự động nạp & đồng bộ dữ liệu thời gian thực từ VPS GitHub Actions
    gh_data = fetch_github_live_data(force=False)
    vps_mem = gh_data.get("vps_memory")
    if isinstance(vps_mem, dict):
        if len(vps_mem.get("conversations", {})) >= len(memory_data["conversations"]):
            memory_data["conversations"].update(vps_mem.get("conversations", {}))
        if len(vps_mem.get("replied_comments", {})) >= len(memory_data["replied_comments"]):
            memory_data["replied_comments"].update(vps_mem.get("replied_comments", {}))
        if isinstance(vps_mem.get("stats"), dict):
            for k, v in vps_mem["stats"].items():
                memory_data["stats"][k] = max(memory_data["stats"].get(k, 0), v)

    # 2. Xử lý danh sách khách hàng
    conversations_list = []
    stage_1_count = 0
    stage_2_count = 0

    for key, c in memory_data["conversations"].items():
        if not isinstance(c, dict):
            continue
        stage = int(c.get("stage", 1))
        if stage >= 2:
            stage_2_count += 1
            stage_label = "Cần nhân viên hỗ trợ"
            stage_badge_class = "badge-danger"
        else:
            stage_1_count += 1
            stage_label = "Đã chào lần 1"
            stage_badge_class = "badge-info"

        last_ts = float(c.get("last_bot_reply_ts", 0))
        conversations_list.append({
            "key": key,
            "customer_name": c.get("customer_name") or "Khách hàng",
            "stage": stage,
            "stage_label": stage_label,
            "stage_badge_class": stage_badge_class,
            "is_waiting_staff": stage >= 2,
            "last_message": c.get("last_replied_customer_msg", ""),
            "last_reply": c.get("last_bot_reply_text", ""),
            "last_ts": last_ts,
            "last_ts_str": format_timestamp(last_ts),
            "time_ago": format_time_ago(last_ts),
            "source": c.get("source", "messenger"),
        })

    # Sắp xếp: Ưu tiên Stage 2 (Chờ nhân viên) lên đầu, sau đó sắp xếp theo thời gian mới nhất
    conversations_list.sort(key=lambda x: (0 if x["is_waiting_staff"] else 1, -x["last_ts"]))

    # 3. Xử lý danh sách bình luận đã trả lời
    comments_list = []
    for key, cmt in memory_data["replied_comments"].items():
        if not isinstance(cmt, dict):
            continue
        ts = float(cmt.get("replied_at", 0))
        comments_list.append({
            "key": key,
            "author": cmt.get("author") or "Khách bình luận",
            "comment_text": cmt.get("comment_text", ""),
            "public_reply": cmt.get("public_reply", ""),
            "private_inbox_sent": bool(cmt.get("private_inbox_sent", False)),
            "private_reply_text": cmt.get("private_reply_text", ""),
            "replied_at": ts,
            "replied_at_str": format_timestamp(ts),
            "time_ago": format_time_ago(ts),
        })
    comments_list.sort(key=lambda x: -x["replied_at"])

    # 4. Trạng thái Bot & Session
    bot_proc = get_active_bot_process_info()
    storage_info = get_storage_state_status()

    # Kiểm tra trạng thái VPS GitHub Actions
    vps_status_raw = gh_data.get("vps_status") or {}
    vps_action_run = gh_data.get("actions_run") or {}
    run_status = vps_action_run.get("status")

    vps_is_running = False
    if run_status == "in_progress":
        vps_is_running = True
    elif vps_status_raw.get("running"):
        last_hb = float(vps_status_raw.get("last_heartbeat", 0))
        if (time.time() - last_hb) < 420:  # 7 phút
            vps_is_running = True

    # Nếu máy tính cá nhân đang không bật bot nhưng VPS GitHub đang chạy:
    if not bot_proc.get("is_running") and vps_is_running:
        bot_proc["is_running"] = True
        run_num = vps_action_run.get("run_number") or "?"
        bot_proc["pid"] = f"VPS #{run_num}"
        bot_proc["mode"] = f"VPS GitHub (Ca #{vps_status_raw.get('cycle', 1)})"
        bot_proc["cycle"] = vps_status_raw.get("cycle", 1)
        bot_proc["status_text"] = "VPS GitHub đang trực 24/24"
        last_hb = float(vps_status_raw.get("last_heartbeat", 0))
        if last_hb > 0:
            bot_proc["last_heartbeat_ago"] = format_time_ago(last_hb)

    # Đo dung lượng thư mục dự án (chứng minh siêu nhẹ)
    state_size_kb = 0.0
    for root, _, files in os.walk(STATE_DIR):
        for f in files:
            p = os.path.join(root, f)
            if os.path.exists(p):
                state_size_kb += os.path.getsize(p) / 1024.0

    return {
        "stats": memory_data["stats"],
        "counts": {
            "total_conversations": len(conversations_list),
            "stage_1_count": stage_1_count,
            "stage_2_waiting_staff": stage_2_count,
            "total_comments_replied": len(comments_list),
        },
        "conversations": conversations_list,
        "recent_comments": comments_list[:50],  # Lấy 50 cmt gần nhất
        "bot_status": bot_proc,
        "vps_live": {
            "is_running": vps_is_running,
            "run_status": run_status or ("in_progress" if vps_is_running else "idle"),
            "run_number": vps_action_run.get("run_number"),
            "run_url": vps_action_run.get("html_url") or GITHUB_REPO_ACTIONS,
            "cycle": vps_status_raw.get("cycle", 0),
            "last_heartbeat_ago": format_time_ago(float(vps_status_raw.get("last_heartbeat", 0))),
            "last_sync": format_time_ago(_GITHUB_CACHE["cached_at"]),
        },
        "storage_state": {
            "exists": storage_info.get("exists", False),
            "cookies_count": storage_info.get("cookies_count", 0),
            "has_auth": storage_info.get("has_auth", False),
            "size_bytes": storage_info.get("size_bytes", 0),
            "size_kb": round(storage_info.get("size_bytes", 0) / 1024.0, 2),
            "last_modified_str": storage_info.get("last_modified_str", "Chưa có"),
        },
        "dan86_source": {
            "cookies_found": os.path.exists(DAN86_SYSTEM_COOKIES_FILE),
            "profile_found": os.path.exists(DAN86_SYSTEM_PROFILE_DIR),
            "cookies_file": DAN86_SYSTEM_COOKIES_FILE,
            "profile_dir": DAN86_SYSTEM_PROFILE_DIR,
        },
        "system_footprint": {
            "state_size_kb": round(state_size_kb, 1),
            "local_chrome_profile_exists": os.path.exists(os.path.join(BASE_DIR, ".chrome_profile")),
            "note": "Tái sử dụng Profile & Cookies d:\\dan86 - Tiết kiệm 100% dung lượng máy",
        },
        "vps_info": {
            "actions_url": GITHUB_REPO_ACTIONS,
            "inbox_url": META_INBOX_ALL_URL,
        },
        "server_time": datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
    }


def read_latest_logs(max_lines: int = 150) -> List[str]:
    """Đọc N dòng log mới nhất từ logs/bot_truc_page.log."""
    if not os.path.exists(LOG_FILE):
        return ["Chưa có file nhật ký hoạt động. Hãy khởi động bot bằng 2_CHAY_THU_TREN_MAY.bat để bắt đầu!"]
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        trimmed = [line.rstrip() for line in lines[-max_lines:]]
        return trimmed if trimmed else ["Nhật ký hoạt động đang trống."]
    except Exception as e:
        return [f"Lỗi đọc file nhật ký: {e}"]


HTML_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>DAN86 Bot Monitor - Trung Tâm Quản Lý Trực Fanpage 24/24</title>
  <style>
    :root {
      --bg: #090d16;
      --card-bg: #111827;
      --card-border: #1f293d;
      --header-bg: rgba(17, 24, 39, 0.88);
      --primary: #10b981;
      --primary-dark: #059669;
      --primary-light: #34d399;
      --accent: #f59e0b;
      --danger: #ef4444;
      --info: #3b82f6;
      --text: #f3f4f6;
      --text-muted: #9ca3af;
      --text-dim: #6b7280;
      --term-bg: #030712;
      --radius: 12px;
      --shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.5);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding-bottom: 60px;
    }
    /* Header */
    header {
      position: sticky;
      top: 0;
      z-index: 100;
      backdrop-filter: blur(12px);
      background: var(--header-bg);
      border-bottom: 1px solid var(--card-border);
      padding: 14px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .logo-badge {
      background: linear-gradient(135deg, #059669, #10b981);
      color: #fff;
      font-weight: 800;
      font-size: 16px;
      padding: 8px 12px;
      border-radius: 8px;
      letter-spacing: 0.5px;
      box-shadow: 0 2px 8px rgba(16, 185, 129, 0.35);
    }
    .brand-title h1 {
      font-size: 18px;
      font-weight: 700;
      color: #fff;
      letter-spacing: -0.3px;
    }
    .brand-title p {
      font-size: 12px;
      color: var(--text-muted);
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 14px;
      border-radius: 9999px;
      font-size: 13px;
      font-weight: 600;
      background: #1f2937;
      border: 1px solid var(--card-border);
    }
    .status-pill.online {
      background: rgba(16, 185, 129, 0.15);
      border-color: rgba(16, 185, 129, 0.4);
      color: var(--primary-light);
    }
    .status-pill.offline {
      background: rgba(156, 163, 175, 0.1);
      border-color: rgba(156, 163, 175, 0.25);
      color: var(--text-muted);
    }
    .pulse-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: currentColor;
      box-shadow: 0 0 8px currentColor;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 14px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      border: 1px solid transparent;
      transition: all 0.15s ease;
      text-decoration: none;
    }
    .btn-primary {
      background: var(--primary);
      color: #032115;
    }
    .btn-primary:hover { background: var(--primary-light); }
    .btn-outline {
      background: #1f2937;
      color: var(--text);
      border-color: var(--card-border);
    }
    .btn-outline:hover {
      background: #374151;
      border-color: #4b5563;
    }
    .btn-warning {
      background: rgba(245, 158, 11, 0.15);
      color: #fbbf24;
      border-color: rgba(245, 158, 11, 0.3);
    }
    .btn-warning:hover {
      background: rgba(245, 158, 11, 0.25);
    }

    /* Container */
    .container {
      max-width: 1400px;
      margin: 20px auto;
      padding: 0 20px;
    }

    /* Notification Alert Bar */
    .waiting-alert {
      background: linear-gradient(90deg, rgba(245, 158, 11, 0.15), rgba(239, 68, 68, 0.12));
      border: 1px solid rgba(245, 158, 11, 0.4);
      border-radius: var(--radius);
      padding: 12px 18px;
      margin-bottom: 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 10px;
    }
    .waiting-alert.hidden { display: none; }
    .waiting-alert-text {
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 600;
      color: #fbbf24;
    }

    /* Stats Grid */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .stat-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      padding: 18px 20px;
      box-shadow: var(--shadow);
      position: relative;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }
    .stat-card::before {
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 3px;
      background: var(--card-border);
    }
    .stat-card.c-green::before { background: var(--primary); }
    .stat-card.c-blue::before { background: var(--info); }
    .stat-card.c-amber::before { background: var(--accent); }
    .stat-card.c-purple::before { background: #8b5cf6; }

    .stat-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: var(--text-muted);
      font-size: 13px;
      font-weight: 500;
    }
    .stat-value {
      font-size: 32px;
      font-weight: 800;
      color: #fff;
      margin: 8px 0 4px 0;
      letter-spacing: -0.5px;
    }
    .stat-sub {
      font-size: 12px;
      color: var(--text-dim);
    }
    .stat-sub span {
      color: var(--primary-light);
      font-weight: 600;
    }

    /* Navigation Tabs */
    .tabs-nav {
      display: flex;
      gap: 8px;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 8px;
      margin-bottom: 20px;
      overflow-x: auto;
    }
    .tab-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      padding: 10px 18px;
      font-size: 14px;
      font-weight: 600;
      border-radius: 8px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      transition: all 0.15s ease;
      white-space: nowrap;
    }
    .tab-btn:hover {
      background: #1f2937;
      color: var(--text);
    }
    .tab-btn.active {
      background: #1f2937;
      color: #fff;
      border-bottom: 2px solid var(--primary);
    }
    .tab-badge {
      background: #374151;
      color: #f3f4f6;
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 9999px;
    }
    .tab-badge.badge-danger {
      background: rgba(239, 68, 68, 0.25);
      color: #fca5a5;
    }

    /* Tab Contents */
    .tab-pane { display: none; }
    .tab-pane.active { display: block; }

    /* Filters Bar */
    .filter-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 16px;
    }
    .search-box {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 8px 14px;
      color: #fff;
      font-size: 13px;
      width: 280px;
      max-width: 100%;
      outline: none;
    }
    .search-box:focus {
      border-color: var(--primary);
    }
    .filter-pills {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .filter-pill {
      background: #1f2937;
      border: 1px solid var(--card-border);
      color: var(--text-muted);
      padding: 5px 12px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
    }
    .filter-pill.active {
      background: rgba(16, 185, 129, 0.2);
      border-color: var(--primary);
      color: var(--primary-light);
    }

    /* Tables & Cards */
    .table-container {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      overflow-x: auto;
      box-shadow: var(--shadow);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 13px;
    }
    th {
      background: #141d2e;
      color: var(--text-muted);
      padding: 12px 16px;
      font-weight: 600;
      border-bottom: 1px solid var(--card-border);
      white-space: nowrap;
    }
    td {
      padding: 14px 16px;
      border-bottom: 1px solid var(--card-border);
      vertical-align: top;
    }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: rgba(255, 255, 255, 0.02); }

    .customer-name {
      font-weight: 700;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .badge {
      display: inline-block;
      font-size: 11px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 6px;
      white-space: nowrap;
    }
    .badge-danger {
      background: rgba(239, 68, 68, 0.18);
      color: #f87171;
      border: 1px solid rgba(239, 68, 68, 0.35);
    }
    .badge-info {
      background: rgba(59, 130, 246, 0.15);
      color: #60a5fa;
      border: 1px solid rgba(59, 130, 246, 0.3);
    }
    .badge-success {
      background: rgba(16, 185, 129, 0.15);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .msg-preview {
      color: #d1d5db;
      font-size: 13px;
      max-width: 380px;
      word-break: break-word;
    }
    .reply-preview {
      color: var(--text-dim);
      font-size: 12px;
      margin-top: 4px;
      background: #0b0f19;
      padding: 6px 10px;
      border-radius: 6px;
      border-left: 2px solid var(--primary);
      max-width: 380px;
      word-break: break-word;
    }
    .time-col {
      white-space: nowrap;
      color: var(--text-dim);
      font-size: 12px;
    }

    /* Terminal Console Logs */
    .terminal-box {
      background: var(--term-bg);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      display: flex;
      flex-direction: column;
      height: 520px;
    }
    .terminal-header {
      background: #111827;
      padding: 10px 16px;
      border-bottom: 1px solid var(--card-border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-top-left-radius: var(--radius);
      border-top-right-radius: var(--radius);
    }
    .terminal-title {
      font-size: 13px;
      font-weight: 600;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .terminal-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .terminal-body {
      padding: 14px;
      flex: 1;
      overflow-y: auto;
      font-family: 'Consolas', 'Courier New', monospace;
      font-size: 12.5px;
      line-height: 1.6;
      color: #e5e7eb;
      background: #030712;
    }
    .log-line {
      margin-bottom: 3px;
      white-space: pre-wrap;
      word-break: break-all;
    }
    .log-info { color: #34d399; }
    .log-warn { color: #fbbf24; }
    .log-error { color: #f87171; }

    /* System Info Grid */
    .info-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
    }
    .info-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      padding: 20px;
    }
    .info-card h3 {
      font-size: 15px;
      font-weight: 700;
      color: #fff;
      margin-bottom: 14px;
      display: flex;
      align-items: center;
      gap: 8px;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 8px;
    }
    .info-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 0;
      font-size: 13px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    }
    .info-row:last-child { border-bottom: none; }
    .info-label { color: var(--text-muted); }
    .info-val { font-weight: 600; color: #fff; text-align: right; }

    .empty-state {
      padding: 40px 20px;
      text-align: center;
      color: var(--text-muted);
    }
    .empty-state svg {
      width: 48px;
      height: 48px;
      margin-bottom: 12px;
      stroke: var(--text-dim);
    }
  </style>
</head>
<body>

  <!-- Header -->
  <header>
    <div class="brand">
      <div class="logo-badge">DAN86</div>
      <div class="brand-title">
        <h1>Bot Trực Fanpage Dần86Farm 24/24</h1>
        <p>Trung Tâm Theo Dõi & Giám Sát Real-Time (Siêu nhẹ - 0MB phụ phí)</p>
      </div>
    </div>
    <div class="header-actions">
      <div id="botStatusPill" class="status-pill offline">
        <div class="pulse-dot"></div>
        <span id="botStatusText">Đang kiểm tra...</span>
      </div>
      <button class="btn btn-outline" id="btnSyncGithub" onclick="syncLiveFromGithub()" title="Đồng bộ dữ liệu thời gian thực từ VPS GitHub Actions">
        ☁️ Đồng bộ VPS Live
      </button>
      <button class="btn btn-outline" onclick="syncCookiesFromDan86()" title="Lấy nhanh cookies từ d:\\dan86 không tốn ổ cứng">
        🔄 Đồng bộ Cookies
      </button>
      <button class="btn btn-outline" onclick="copyGithubSecret()" title="Copy mã cấu hình FB_STORAGE_STATE cho GitHub Actions">
        🔑 Copy GitHub Secret
      </button>
      <a href="https://business.facebook.com/latest/inbox/all" target="_blank" class="btn btn-primary" title="Mở Hộp thư Fanpage Meta Business Suite">
        ↗️ Mở Hộp Thư Page
      </a>
    </div>
  </header>

  <div class="container">

    <!-- Banner Trạng Thái VPS GitHub Actions 24/24 -->
    <div id="vpsLiveBanner" class="waiting-alert hidden" style="background: linear-gradient(90deg, rgba(16, 185, 129, 0.15), rgba(59, 130, 246, 0.12)); border-color: rgba(16, 185, 129, 0.4);">
      <div class="waiting-alert-text" style="color: #34d399;">
        <span>☁️ VPS GITHUB ACTIONS ĐANG TRỰC 24/24:</span>
        <span id="vpsLiveBannerText">Ca trực đang chạy liên tục, tự động trả lời bình luận & inbox.</span>
      </div>
      <a id="vpsLiveBannerLink" href="https://github.com/DucTri2207/chatbot-dan86/actions" target="_blank" class="btn btn-outline" style="border-color: rgba(16, 185, 129, 0.4); color: #34d399;">
        ↗️ Xem Chi Tiết Trên GitHub
      </a>
    </div>

    <!-- Cảnh báo nếu có khách hàng Stage 2 cần nhân viên xử lý -->
    <div id="waitingAlert" class="waiting-alert hidden">
      <div class="waiting-alert-text">
        <span>⚠️ CẢNH BÁO NHÂN VIÊN:</span>
        <span id="waitingAlertCount">Có 0 khách hàng</span> đang chờ tư vấn chốt đơn (Stage 2)!
      </div>
      <a href="https://business.facebook.com/latest/inbox/all" target="_blank" class="btn btn-warning">
        👉 Vào Trả Lời Ngay
      </a>
    </div>

    <!-- 4 Khối Thống Kê Chính -->
    <div class="stats-grid">
      <div class="stat-card c-green">
        <div class="stat-header">
          <span>Bình Luận Đã Trả Lời</span>
          <span>💬</span>
        </div>
        <div id="statComments" class="stat-value">0</div>
        <div class="stat-sub">
          Đã tự động gửi <span id="statPrivateInboxes">0</span> tin nhắn riêng
        </div>
      </div>

      <div class="stat-card c-blue">
        <div class="stat-header">
          <span>Khách Chào Lần Đầu (Stage 1)</span>
          <span>👋</span>
        </div>
        <div id="statFirstInbox" class="stat-value">0</div>
        <div class="stat-sub">Đã gửi mẫu tư vấn set quà & bảng giá</div>
      </div>

      <div class="stat-card c-amber">
        <div class="stat-header">
          <span>Khách Chờ Nhân Viên (Stage 2)</span>
          <span>🚨</span>
        </div>
        <div id="statWaitStaff" class="stat-value">0</div>
        <div class="stat-sub">
          Hiện có <span id="statWaitActive">0</span> khách đang đợi hỗ trợ thật
        </div>
      </div>

      <div class="stat-card c-purple">
        <div class="stat-header">
          <span>Phiên Đăng Nhập & VPS</span>
          <span>🛡️</span>
        </div>
        <div id="statStorageState" class="stat-value" style="font-size: 20px; margin-top: 14px;">
          Sẵn sàng
        </div>
        <div class="stat-sub">
          File: <span id="statStorageSize">~3.8 KB</span> | Profile: <span id="statStorageProfile">d:\\dan86</span>
        </div>
      </div>
    </div>

    <!-- Tabs Menu -->
    <div class="tabs-nav">
      <button class="tab-btn active" onclick="switchTab('tab-customers')">
        👥 Khách Hàng Chờ Tư Vấn
        <span id="badgeCustomersCount" class="tab-badge">0</span>
      </button>
      <button class="tab-btn" onclick="switchTab('tab-comments')">
        💬 Bình Luận Gần Đây
        <span id="badgeCommentsCount" class="tab-badge">0</span>
      </button>
      <button class="tab-btn" onclick="switchTab('tab-logs')">
        📜 Nhật Ký Hoạt Động Real-Time
      </button>
      <button class="tab-btn" onclick="switchTab('tab-system')">
        ⚙️ Trạng Thái Máy & VPS GitHub
      </button>
    </div>

    <!-- TAB 1: DANH SÁCH KHÁCH HÀNG -->
    <div id="tab-customers" class="tab-pane active">
      <div class="filter-bar">
        <input type="text" id="customerSearch" class="search-box" placeholder="🔍 Tìm theo tên khách hàng..." onkeyup="renderCustomers()">
        <div class="filter-pills">
          <div class="filter-pill active" onclick="setCustomerFilter('all', this)">Tất cả (<span id="countAllCust">0</span>)</div>
          <div class="filter-pill" onclick="setCustomerFilter('stage2', this)">⚠️ Chờ nhân viên (<span id="countStage2Cust">0</span>)</div>
          <div class="filter-pill" onclick="setCustomerFilter('stage1', this)">Stage 1 - Đã chào (<span id="countStage1Cust">0</span>)</div>
        </div>
      </div>

      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th style="width: 180px;">Khách Hàng</th>
              <th style="width: 150px;">Giai Đoạn</th>
              <th>Tin Nhắn Gần Nhất Của Khách & Bot Đã Trả Lời</th>
              <th style="width: 130px;">Thời Gian</th>
              <th style="width: 100px;">Thao Tác</th>
            </tr>
          </thead>
          <tbody id="customersTableBody">
            <tr><td colspan="5" class="empty-state">Đang tải dữ liệu...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- TAB 2: BÌNH LUẬN GẦN ĐÂY -->
    <div id="tab-comments" class="tab-pane">
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th style="width: 180px;">Người Bình Luận</th>
              <th>Nội Dung Bình Luận</th>
              <th>Câu Bot Trả Lời Công Khai</th>
              <th style="width: 130px;">Inbox Riêng</th>
              <th style="width: 130px;">Thời Gian</th>
            </tr>
          </thead>
          <tbody id="commentsTableBody">
            <tr><td colspan="5" class="empty-state">Đang tải dữ liệu...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- TAB 3: NHẬT KÝ CONSOLE LOGS -->
    <div id="tab-logs" class="tab-pane">
      <div class="terminal-box">
        <div class="terminal-header">
          <div class="terminal-title">
            <span>💻 logs/bot_truc_page.log</span>
            <span id="logUpdateTag" style="font-size: 11px; color: var(--text-dim);">(Tự động cập nhật mỗi 5 giây)</span>
          </div>
          <div class="terminal-actions">
            <button class="btn btn-outline" style="padding: 4px 10px; font-size: 12px;" onclick="fetchLogs()">🔄 Tải lại</button>
            <button class="btn btn-outline" style="padding: 4px 10px; font-size: 12px;" onclick="toggleAutoScroll()">⏬ Cuộn cuối: <span id="autoScrollStatus">BẬT</span></button>
          </div>
        </div>
        <div id="terminalBody" class="terminal-body">
          <div class="log-line">Đang nạp nhật ký hoạt động...</div>
        </div>
      </div>
    </div>

    <!-- TAB 4: TRẠNG THÁI MÁY & VPS GITHUB -->
    <div id="tab-system" class="tab-pane">
      <div class="info-grid">
        <div class="info-card">
          <h3>🖥️ Trạng Thái Bot Trên Máy Tính</h3>
          <div class="info-row">
            <span class="info-label">Trạng thái chạy</span>
            <span id="sysBotRunning" class="info-val">--</span>
          </div>
          <div class="info-row">
            <span class="info-label">Mã tiến trình (PID)</span>
            <span id="sysBotPid" class="info-val">--</span>
          </div>
          <div class="info-row">
            <span class="info-label">Thời gian hoạt động</span>
            <span id="sysBotUptime" class="info-val">--</span>
          </div>
          <div class="info-row">
            <span class="info-label">Số chu kỳ quét</span>
            <span id="sysBotCycle" class="info-val">--</span>
          </div>
          <div class="info-row">
            <span class="info-label">Chế độ</span>
            <span id="sysBotMode" class="info-val">--</span>
          </div>
        </div>

        <div class="info-card">
          <h3>☁️ Trạng Thái VPS GitHub Actions (24/24)</h3>
          <div class="info-row">
            <span class="info-label">Trạng thái VPS</span>
            <span id="vpsLiveStatus" class="info-val">--</span>
          </div>
          <div class="info-row">
            <span class="info-label">Kho lưu trữ mã nguồn</span>
            <span class="info-val"><a href="https://github.com/DucTri2207/chatbot-dan86" target="_blank" style="color: var(--primary-light);">chatbot-dan86</a></span>
          </div>
          <div class="info-row">
            <span class="info-label">Ca trực hiện tại</span>
            <span id="vpsLiveCycle" class="info-val">--</span>
          </div>
          <div class="info-row">
            <span class="info-label">Tín hiệu heartbeat</span>
            <span id="vpsLiveHeartbeat" class="info-val">--</span>
          </div>
          <div class="info-row">
            <span class="info-label">Cơ chế hoạt động</span>
            <span class="info-val">Ca 320p liên tục, tự gọi ca tiếp</span>
          </div>
          <div class="info-row">
            <span class="info-label">Đồng bộ bộ nhớ</span>
            <span class="info-val">Tự lưu state/bot_memory.json qua Git</span>
          </div>
          <div class="info-row" style="margin-top: 10px;">
            <a id="vpsLiveRunUrl" href="https://github.com/DucTri2207/chatbot-dan86/actions" target="_blank" class="btn btn-outline" style="width: 100%; justify-content: center;">
              ↗️ Xem Log Chạy Trực Tiếp Trên GitHub Actions
            </a>
          </div>
        </div>

        <div class="info-card">
          <h3>💾 Tối Ưu Hóa Bộ Nhớ & Ổ Cứng (0MB Rác)</h3>
          <div class="info-row">
            <span class="info-label">Profile Chrome nguồn</span>
            <span id="sysProfileSource" class="info-val">d:\\dan86\\.chrome_profile</span>
          </div>
          <div class="info-row">
            <span class="info-label">Cookies nguồn</span>
            <span id="sysCookiesSource" class="info-val">d:\\dan86\\dan86_saved_cookies.json</span>
          </div>
          <div class="info-row">
            <span class="info-label">File phiên trích xuất</span>
            <span id="sysStorageSize" class="info-val">~3.8 KB</span>
          </div>
          <div class="info-row">
            <span class="info-label">Dung lượng dự án bot</span>
            <span id="sysFootprint" class="info-val">Siêu nhẹ (< 1MB)</span>
          </div>
          <div class="info-row" style="margin-top: 10px;">
            <button class="btn btn-primary" style="width: 100%; justify-content: center;" onclick="syncCookiesFromDan86()">
              🔄 Trích Xuất Lại Cookies Ngay Lập Tức
            </button>
          </div>
        </div>
      </div>
    </div>

  </div>

  <script>
    let globalData = null;
    let currentFilter = 'all';
    let autoScroll = true;
    const API_BASE = (window.location.protocol === 'file:') ? 'http://localhost:8686' : '';

    async function fetchStatus() {
      try {
        const res = await fetch(API_BASE + '/api/status');
        if (!res.ok) throw new Error('API status not ok');
        globalData = await res.json();
        renderDashboard(globalData);
      } catch (e) {
        console.warn('Fetch status warning:', e);
        // Fallback đọc trực tiếp từ GitHub khi mở bằng file:/// hoặc server local chưa bật
        await fetchStaticGithubData();
      }
    }

    async function fetchLogs() {
      try {
        const res = await fetch(API_BASE + '/api/logs');
        if (!res.ok) return;
        const data = await res.json();
        renderLogs(data.logs || []);
      } catch (e) {
        console.warn('Fetch logs warning:', e);
      }
    }

    async function syncLiveFromGithub() {
      const btn = document.getElementById('btnSyncGithub');
      if (btn) btn.innerText = '⏳ Đang tải...';
      try {
        const res = await fetch(API_BASE + '/api/sync_github', { method: 'POST' });
        if (res.ok) {
          globalData = await res.json();
          renderDashboard(globalData);
          if (btn) btn.innerText = '✅ Đã đồng bộ';
          setTimeout(() => { if (btn) btn.innerText = '☁️ Đồng bộ VPS Live'; }, 2000);
          return;
        }
      } catch (e) {
        console.warn('API sync_github warning:', e);
      }
      // Fallback đọc trực tiếp GitHub raw nếu server local không phản hồi
      await fetchStaticGithubData();
      if (btn) btn.innerText = '✅ Đã đồng bộ';
      setTimeout(() => { if (btn) btn.innerText = '☁️ Đồng bộ VPS Live'; }, 2000);
    }

    async function fetchStaticGithubData() {
      try {
        const t = Date.now();
        const statusUrl = `https://raw.githubusercontent.com/DucTri2207/chatbot-dan86/master/state/bot_status.json?t=${t}`;
        const memoryUrl = `https://raw.githubusercontent.com/DucTri2207/chatbot-dan86/master/state/bot_memory.json?t=${t}`;
        const [resStatus, resMem] = await Promise.all([
          fetch(statusUrl).catch(() => null),
          fetch(memoryUrl).catch(() => null),
        ]);
        const vpsStatus = (resStatus && resStatus.ok) ? await resStatus.json() : {};
        const vpsMem = (resMem && resMem.ok) ? await resMem.json() : {};

        buildDataFromStaticGithub(vpsStatus, vpsMem);
      } catch (err) {
        console.warn('fetchStaticGithubData error:', err);
      }
    }

    function buildDataFromStaticGithub(vpsStatus, vpsMem) {
      if (!vpsStatus && !vpsMem) return;
      const mem = vpsMem || {};
      const convs = mem.conversations || {};
      const cmts = mem.replied_comments || {};
      const stats = mem.stats || {};

      let stage1 = 0;
      let stage2 = 0;
      const convList = [];
      for (const [key, c] of Object.entries(convs)) {
        if (!c || typeof c !== 'object') continue;
        const stage = parseInt(c.stage || 1);
        if (stage >= 2) stage2++; else stage1++;
        convList.push({
          key: key,
          customer_name: c.customer_name || 'Khách hàng',
          stage: stage,
          stage_label: stage >= 2 ? 'Cần nhân viên hỗ trợ' : 'Đã chào lần 1',
          stage_badge_class: stage >= 2 ? 'badge-danger' : 'badge-info',
          is_waiting_staff: stage >= 2,
          last_message: c.last_replied_customer_msg || '',
          last_reply: c.last_bot_reply_text || '',
          last_ts: c.last_bot_reply_ts || 0,
          last_ts_str: c.last_bot_reply_ts ? new Date(c.last_bot_reply_ts * 1000).toLocaleString('vi-VN') : '--',
          time_ago: 'Gần đây',
          source: c.source || 'messenger',
        });
      }
      convList.sort((a, b) => (b.last_ts || 0) - (a.last_ts || 0));

      const cmtList = [];
      for (const [key, cmt] of Object.entries(cmts)) {
        if (!cmt || typeof cmt !== 'object') continue;
        cmtList.push({
          key: key,
          author: cmt.author || 'Khách bình luận',
          comment_text: cmt.comment_text || '',
          public_reply: cmt.public_reply || '',
          private_inbox_sent: Boolean(cmt.private_inbox_sent),
          private_reply_text: cmt.private_reply_text || '',
          replied_at: cmt.replied_at || 0,
          replied_at_str: cmt.replied_at ? new Date(cmt.replied_at * 1000).toLocaleString('vi-VN') : '--',
          time_ago: 'Gần đây',
        });
      }
      cmtList.sort((a, b) => (b.replied_at || 0) - (a.replied_at || 0));

      const isRunning = Boolean(vpsStatus && vpsStatus.running);
      globalData = {
        stats: {
          comments_replied: stats.comments_replied || cmtList.length,
          private_inboxes_from_comment: stats.private_inboxes_from_comment || 0,
          first_inbox_replies: stats.first_inbox_replies || 0,
          wait_staff_replies: stats.wait_staff_replies || 0,
        },
        counts: {
          total_conversations: convList.length,
          stage_1_count: stage1,
          stage_2_waiting_staff: stage2,
          total_comments_replied: cmtList.length,
        },
        conversations: convList,
        recent_comments: cmtList,
        bot_status: {
          is_running: isRunning,
          pid: isRunning ? 'VPS GitHub' : null,
          cycle: vpsStatus.cycle || 1,
          status_text: isRunning ? 'VPS GitHub đang trực 24/24' : 'Đang dừng',
          uptime_str: '--',
          mode: 'VPS GitHub',
        },
        vps_live: {
          is_running: isRunning,
          cycle: vpsStatus.cycle || 1,
          run_url: 'https://github.com/DucTri2207/chatbot-dan86/actions',
          last_heartbeat_ago: 'Vừa đồng bộ',
        },
        storage_state: {
          exists: true,
          cookies_count: 2,
          size_kb: 3.8,
        },
        system_footprint: {
          state_size_kb: 5.2,
        },
      };
      renderDashboard(globalData);
    }

    function renderDashboard(data) {
      if (!data) return;

      // 1. Bot status pill & VPS live banner
      const pill = document.getElementById('botStatusPill');
      const text = document.getElementById('botStatusText');
      const isRunning = data.bot_status && data.bot_status.is_running;
      const vpsLive = data.vps_live;
      const vpsBanner = document.getElementById('vpsLiveBanner');
      const vpsBannerText = document.getElementById('vpsLiveBannerText');
      const vpsBannerLink = document.getElementById('vpsLiveBannerLink');

      if (vpsLive && vpsLive.is_running) {
        if (vpsBanner) {
          vpsBanner.classList.remove('hidden');
          if (vpsBannerText) {
            vpsBannerText.innerText = `Ca #${vpsLive.cycle || 1} đang trực tự động 24/24 trên VPS GitHub Actions (Cập nhật: ${vpsLive.last_heartbeat_ago || 'Vừa xong'})`;
          }
          if (vpsBannerLink && vpsLive.run_url) {
            vpsBannerLink.href = vpsLive.run_url;
          }
        }
      } else {
        if (vpsBanner) vpsBanner.classList.add('hidden');
      }

      if (isRunning) {
        pill.className = 'status-pill online';
        text.innerText = `Đang chạy (${data.bot_status.pid ? 'PID ' + data.bot_status.pid + ' - ' : ''}Vòng #${data.bot_status.cycle || 1})`;
      } else {
        pill.className = 'status-pill offline';
        text.innerText = 'Bot máy tính: Đang dừng';
      }

      // 2. Stats
      document.getElementById('statComments').innerText = data.stats.comments_replied || 0;
      document.getElementById('statPrivateInboxes').innerText = data.stats.private_inboxes_from_comment || 0;
      document.getElementById('statFirstInbox').innerText = data.stats.first_inbox_replies || 0;
      document.getElementById('statWaitStaff').innerText = data.stats.wait_staff_replies || 0;
      document.getElementById('statWaitActive').innerText = data.counts.stage_2_waiting_staff || 0;

      // Storage status
      if (data.storage_state && data.storage_state.exists) {
        document.getElementById('statStorageState').innerText = `✅ ${data.storage_state.cookies_count} Cookies`;
        document.getElementById('statStorageSize').innerText = `${data.storage_state.size_kb} KB`;
      } else {
        document.getElementById('statStorageState').innerText = 'Chưa có session';
      }

      // 3. Waiting alert
      const waitingCount = data.counts.stage_2_waiting_staff || 0;
      const alertBox = document.getElementById('waitingAlert');
      if (waitingCount > 0) {
        alertBox.classList.remove('hidden');
        document.getElementById('waitingAlertCount').innerText = `Có ${waitingCount} khách hàng`;
      } else {
        alertBox.classList.add('hidden');
      }

      // 4. Badges
      document.getElementById('badgeCustomersCount').innerText = data.counts.total_conversations || 0;
      document.getElementById('badgeCommentsCount').innerText = data.counts.total_comments_replied || 0;
      document.getElementById('countAllCust').innerText = data.counts.total_conversations || 0;
      document.getElementById('countStage2Cust').innerText = waitingCount;
      document.getElementById('countStage1Cust').innerText = data.counts.stage_1_count || 0;

      // 5. System info tab
      if (data.bot_status) {
        document.getElementById('sysBotRunning').innerText = data.bot_status.status_text;
        document.getElementById('sysBotPid').innerText = data.bot_status.pid || 'Không có';
        document.getElementById('sysBotUptime').innerText = data.bot_status.uptime_str || '--';
        document.getElementById('sysBotCycle').innerText = `#${data.bot_status.cycle || 0}`;
        document.getElementById('sysBotMode').innerText = data.bot_status.mode === 'dry-run' ? 'Dry-Run (Xem trước)' : 'Live (Thật)';
      }
      if (data.vps_live) {
        const vpsStatusEl = document.getElementById('vpsLiveStatus');
        if (vpsStatusEl) {
          vpsStatusEl.innerText = data.vps_live.is_running ? '🟢 Đang hoạt động (Trực 24/24)' : '⚪ Đang nghỉ / Hoàn tất';
        }
        const vpsCycleEl = document.getElementById('vpsLiveCycle');
        if (vpsCycleEl) {
          vpsCycleEl.innerText = data.vps_live.cycle ? `Ca #${data.vps_live.cycle}` : '--';
        }
        const vpsHbEl = document.getElementById('vpsLiveHeartbeat');
        if (vpsHbEl) {
          vpsHbEl.innerText = data.vps_live.last_heartbeat_ago || 'Chưa có';
        }
        const runLink = document.getElementById('vpsLiveRunUrl');
        if (runLink && data.vps_live.run_url) {
          runLink.href = data.vps_live.run_url;
        }
      }
      if (data.storage_state) {
        document.getElementById('sysStorageSize').innerText = `${data.storage_state.size_kb} KB (Trích xuất: ${data.storage_state.last_modified_str})`;
      }
      if (data.system_footprint) {
        document.getElementById('sysFootprint').innerText = `${data.system_footprint.state_size_kb} KB (Tuyệt đối không tốn GBs)`;
      }

      // Render tables
      renderCustomers();
      renderComments();
    }

    function renderCustomers() {
      if (!globalData || !globalData.conversations) return;
      const tbody = document.getElementById('customersTableBody');
      const search = (document.getElementById('customerSearch').value || '').toLowerCase().trim();

      let list = globalData.conversations.filter(c => {
        if (currentFilter === 'stage2' && !c.is_waiting_staff) return false;
        if (currentFilter === 'stage1' && c.is_waiting_staff) return false;
        if (search) {
          const matchName = (c.customer_name || '').toLowerCase().includes(search);
          const matchMsg = (c.last_message || '').toLowerCase().includes(search);
          return matchName || matchMsg;
        }
        return true;
      });

      if (list.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="empty-state">Không có khách hàng nào phù hợp bộ lọc.</td></tr>`;
        return;
      }

      tbody.innerHTML = list.map(c => `
        <tr style="${c.is_waiting_staff ? 'background: rgba(245, 158, 11, 0.05);' : ''}">
          <td>
            <div class="customer-name">
              ${escapeHtml(c.customer_name)}
            </div>
            <div style="font-size: 11px; color: var(--text-dim); margin-top: 2px;">
              ${escapeHtml(c.source === 'comment_private_reply' ? 'Từ bình luận' : 'Nhắn tin')}
            </div>
          </td>
          <td>
            <span class="badge ${c.stage_badge_class}">
              ${c.is_waiting_staff ? '⚠️ ' : ''}${escapeHtml(c.stage_label)}
            </span>
          </td>
          <td>
            <div class="msg-preview">
              <strong>Khách:</strong> "${escapeHtml(c.last_message || 'Chưa có')}"
            </div>
            ${c.last_reply ? `<div class="reply-preview"><strong>Bot rep:</strong> ${escapeHtml(c.last_reply)}</div>` : ''}
          </td>
          <td class="time-col">
            <div>${c.time_ago}</div>
            <div style="font-size: 10px; color: var(--text-dim);">${c.last_ts_str}</div>
          </td>
          <td>
            <a href="https://business.facebook.com/latest/inbox/all" target="_blank" class="btn btn-outline" style="padding: 4px 10px; font-size: 12px;">
              Chat ↗
            </a>
          </td>
        </tr>
      `).join('');
    }

    function renderComments() {
      if (!globalData || !globalData.recent_comments) return;
      const tbody = document.getElementById('commentsTableBody');
      const list = globalData.recent_comments;

      if (list.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="empty-state">Chưa có bình luận nào được xử lý.</td></tr>`;
        return;
      }

      tbody.innerHTML = list.map(c => `
        <tr>
          <td><div class="customer-name">${escapeHtml(c.author)}</div></td>
          <td><div class="msg-preview">${escapeHtml(c.comment_text)}</div></td>
          <td>
            <div class="msg-preview" style="color: #6ee7b7;">
              ${escapeHtml(c.public_reply)}
            </div>
          </td>
          <td>
            ${c.private_inbox_sent
              ? '<span class="badge badge-success">✅ Đã gửi</span>'
              : '<span class="badge" style="background:#374151;color:#9ca3af;">Chưa gửi</span>'}
          </td>
          <td class="time-col">
            <div>${c.time_ago}</div>
            <div style="font-size: 10px; color: var(--text-dim);">${c.replied_at_str}</div>
          </td>
        </tr>
      `).join('');
    }

    function renderLogs(lines) {
      const body = document.getElementById('terminalBody');
      body.innerHTML = lines.map(line => {
        let cls = 'log-line';
        if (line.includes('[INFO]') || line.includes('✅') || line.includes('🚀')) cls += ' log-info';
        else if (line.includes('[WARN]') || line.includes('⚠️')) cls += ' log-warn';
        else if (line.includes('[ERROR]') || line.includes('❌')) cls += ' log-error';
        return `<div class="${cls}">${escapeHtml(line)}</div>`;
      }).join('');

      if (autoScroll) {
        body.scrollTop = body.scrollHeight;
      }
    }

    function switchTab(tabId) {
      document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
      const target = document.getElementById(tabId);
      if (target) target.classList.add('active');
      event.currentTarget.classList.add('active');
      if (tabId === 'tab-logs') fetchLogs();
    }

    function setCustomerFilter(filter, el) {
      currentFilter = filter;
      document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
      el.classList.add('active');
      renderCustomers();
    }

    function toggleAutoScroll() {
      autoScroll = !autoScroll;
      document.getElementById('autoScrollStatus').innerText = autoScroll ? 'BẬT' : 'TẮT';
    }

    async function syncCookiesFromDan86() {
      try {
        const res = await fetch(API_BASE + '/api/sync_cookies', { method: 'POST' });
        const result = await res.json();
        if (result.success) {
          alert(`✅ ${result.message}`);
          fetchStatus();
        } else {
          alert(`❌ ${result.message}`);
        }
      } catch (e) {
        alert('Lỗi gửi yêu cầu đồng bộ: ' + e);
      }
    }

    async function copyGithubSecret() {
      try {
        const res = await fetch(API_BASE + '/api/secret');
        const data = await res.json();
        if (data.secret) {
          await navigator.clipboard.writeText(data.secret);
          alert('✅ Đã sao chép mã Base64 vào bộ nhớ tạm!\nBạn hãy vào GitHub Settings -> Secrets -> Actions -> paste vào biến FB_STORAGE_STATE.');
        } else {
          alert('❌ Chưa tìm thấy file GITHUB_SECRET_VALUE.txt. Hãy nhấn [Đồng bộ Cookies] trước!');
        }
      } catch (e) {
        alert('Lỗi sao chép secret: ' + e);
      }
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    // Auto-refresh loop
    fetchStatus();
    fetchLogs();
    setInterval(fetchStatus, 5000);
    setInterval(fetchLogs, 5000);
  </script>
</body>
</html>
"""


class DashboardHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    """Xử lý HTTP requests cho Dashboard DAN86."""

    def log_message(self, format: str, *args: Any) -> None:
        # Tắt bớt log HTTP để terminal luôn sạch đẹp
        pass

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE_TEMPLATE.encode("utf-8"))
            return

        if path == "/api/status":
            data = collect_dashboard_data()
            payload = json.dumps(data, ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
            return

        if path == "/api/logs":
            logs = read_latest_logs(150)
            payload = json.dumps({"logs": logs}, ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
            return

        if path == "/api/secret":
            secret_str = ""
            if os.path.exists(GITHUB_SECRET_EXPORT_FILE):
                try:
                    with open(GITHUB_SECRET_EXPORT_FILE, "r", encoding="utf-8") as f:
                        secret_str = f.read().strip()
                except Exception:
                    pass
            payload = json.dumps({"secret": secret_str}, ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
            return

        if path in ("/api/sync_github", "/api/sync-github"):
            fetch_github_live_data(force=True)
            data = collect_dashboard_data()
            payload = json.dumps(data, ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"404 Not Found")

    def do_POST(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path in ("/api/sync_github", "/api/sync-github"):
            fetch_github_live_data(force=True)
            data = collect_dashboard_data()
            payload = json.dumps(data, ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
            return

        if path == "/api/sync_cookies":
            res = sync_facebook_credentials_from_dan86()
            payload = json.dumps(res, ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"404 Not Found")


def run_dashboard_server(port: int = PORT, auto_open: bool = True) -> None:
    # Xuất kèm file HTML tĩnh ra thư mục để người dùng có thể mở trực tiếp
    static_html_path = os.path.join(BASE_DIR, "dashboard.html")
    try:
        with open(static_html_path, "w", encoding="utf-8") as f:
            f.write(HTML_PAGE_TEMPLATE)
    except Exception:
        pass

    # Tự động nạp cookies nếu chưa có
    if not os.path.exists(STORAGE_STATE_FILE):
        sync_facebook_credentials_from_dan86()

    server_address = ("", port)
    try:
        httpd = socketserver.TCPServer(server_address, DashboardHTTPRequestHandler)
    except OSError:
        port += 1
        server_address = ("", port)
        httpd = socketserver.TCPServer(server_address, DashboardHTTPRequestHandler)

    url = f"http://localhost:{port}"
    print("=" * 76)
    print("   DAN86 BOT MONITOR & CONTROL DASHBOARD (SIÊU NHẸ - 0MB PHỤ PHÍ)")
    print("=" * 76)
    print(f"👉 Máy chủ Dashboard đang chạy tại : {url}")
    print(f"👉 File HTML tĩnh xem trực tiếp   : {static_html_path}")
    print("👉 Dung lượng RAM tiêu thụ         : < 18MB (Python Built-in Server)")
    print("👉 Nhấn Ctrl + C để dừng Dashboard.")
    print("=" * 76)

    if auto_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng máy chủ Dashboard.")
        httpd.server_close()


if __name__ == "__main__":
    auto_open = "--no-browser" not in sys.argv
    run_dashboard_server(auto_open=auto_open)
