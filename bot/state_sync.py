"""
Module đồng bộ trạng thái (State Sync) cho Bot Trực Fanpage DAN86 trên VPS GitHub Actions.
Chịu trách nhiệm:
1. Smart Merge dữ liệu bộ nhớ (state/bot_memory.json) đa chiều:
   - Hợp nhất toàn bộ bình luận đã trả lời (replied_comments) không làm mất bất kỳ bản ghi nào từ cả local và remote.
   - Hợp nhất lịch sử hội thoại Messenger (conversations), giữ lại mốc thời gian và giai đoạn (stage) tiến triển mới nhất.
   - Chuẩn hóa và làm mới toàn bộ thống kê (stats).
2. Đồng bộ không xung đột (Conflict-Free Git Sync):
   - Đảm bảo repo không bị shallow clone.
   - Trích xuất remote memory an toàn qua git show origin/master:state/bot_memory.json.
   - Kết hợp git reset --soft origin/master sau khi đã hợp nhất JSON, giúp commit đẩy lên luôn luôn là Fast-Forward sạch trên master.
   - Cơ chế Retry và xử lý ngoại lệ bền bỉ, chống mất dữ liệu khi chuyển giao giữa các ca VPS 24/24.
"""

import json
import logging
import os
import subprocess
import sys
import time
from typing import Any, Dict, Optional, Tuple

from bot.bot_config import BOT_STATUS_FILE, MEMORY_FILE, STATE_DIR

logger = logging.getLogger("dan86_state_sync")


def safe_load_json(file_path: str) -> Dict[str, Any]:
    """Đọc file JSON an toàn, trả về dict rỗng nếu lỗi hoặc file không tồn tại."""
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("Không thể đọc file JSON %s: %s", file_path, e)
        return {}


def safe_save_json(file_path: str, data: Dict[str, Any]) -> bool:
    """Ghi đĩa an toàn bằng cơ chế Atomic Write (.tmp -> os.replace)."""
    try:
        os.makedirs(os.path.dirname(file_path) or STATE_DIR, exist_ok=True)
        temp_path = f"{file_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, file_path)
        return True
    except Exception as e:
        logger.error("Lỗi ghi file JSON %s: %s", file_path, e)
        return False


def smart_merge_memory(
    local_data: Dict[str, Any], remote_data: Dict[str, Any]
) -> Tuple[Dict[str, Any], bool]:
    """
    Hợp nhất thông minh giữa bộ nhớ local và remote:
    - replied_comments: Hợp nhất Union set. Nếu cả 2 cùng có key, ưu tiên trạng thái đã gửi tin riêng (private_inbox_sent=True).
    - conversations: Hợp nhất Union set. Nếu trùng thread, ưu tiên stage cao hơn hoặc timestamp tương tác mới hơn.
    - stats: Đồng bộ số liệu đếm chính xác.
    Trả về: (merged_data, has_changes)
    """
    merged = {
        "replied_comments": dict(local_data.get("replied_comments", {})),
        "conversations": dict(local_data.get("conversations", {})),
        "stats": dict(local_data.get("stats", {})),
    }
    has_changes = False

    # 1. Hợp nhất bình luận đã phản hồi (replied_comments)
    remote_comments = remote_data.get("replied_comments", {})
    if isinstance(remote_comments, dict):
        for k, r_val in remote_comments.items():
            if not isinstance(r_val, dict):
                continue
            if k not in merged["replied_comments"]:
                merged["replied_comments"][k] = r_val
                has_changes = True
            else:
                l_val = merged["replied_comments"][k]
                if isinstance(l_val, dict):
                    # Nếu remote ghi nhận đã gửi inbox riêng mà local chưa ghi nhận -> cập nhật
                    if not l_val.get("private_inbox_sent") and r_val.get("private_inbox_sent"):
                        l_val["private_inbox_sent"] = True
                        if r_val.get("private_reply_text"):
                            l_val["private_reply_text"] = r_val["private_reply_text"]
                        has_changes = True

    # 2. Hợp nhất hội thoại Messenger (conversations)
    remote_convs = remote_data.get("conversations", {})
    if isinstance(remote_convs, dict):
        for t_key, r_conv in remote_convs.items():
            if not isinstance(r_conv, dict):
                continue
            if t_key not in merged["conversations"]:
                merged["conversations"][t_key] = r_conv
                has_changes = True
            else:
                l_conv = merged["conversations"][t_key]
                if isinstance(l_conv, dict):
                    l_ts = max(
                        float(l_conv.get("last_bot_reply_ts", 0)),
                        float(l_conv.get("last_interaction_ts", 0)),
                    )
                    r_ts = max(
                        float(r_conv.get("last_bot_reply_ts", 0)),
                        float(r_conv.get("last_interaction_ts", 0)),
                    )
                    if r_ts > l_ts:
                        merged["conversations"][t_key] = r_conv
                        has_changes = True
                    elif r_conv.get("stage", 0) > l_conv.get("stage", 0):
                        l_conv["stage"] = r_conv["stage"]
                        has_changes = True

    # 3. Đồng bộ và làm sạch stats
    total_comments = len(merged["replied_comments"])
    total_inboxes = sum(
        1
        for c in merged["replied_comments"].values()
        if isinstance(c, dict) and c.get("private_inbox_sent")
    )
    if merged["stats"].get("comments_replied", 0) != total_comments:
        merged["stats"]["comments_replied"] = total_comments
        has_changes = True
    if merged["stats"].get("private_inboxes_from_comment", 0) != total_inboxes:
        merged["stats"]["private_inboxes_from_comment"] = total_inboxes
        has_changes = True

    remote_stats = remote_data.get("stats", {})
    if isinstance(remote_stats, dict):
        for stat_key in ("first_inbox_replies", "wait_staff_replies"):
            r_val = remote_stats.get(stat_key, 0)
            if r_val > merged["stats"].get(stat_key, 0):
                merged["stats"][stat_key] = r_val
                has_changes = True

    return merged, has_changes


def run_git_cmd(args: list, timeout: int = 25) -> Tuple[int, str, str]:
    """Chạy lệnh git an toàn có giới hạn thời gian."""
    try:
        res = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def sync_state_to_github(
    log: Optional[logging.Logger] = None,
    force: bool = False,
    memory_instance: Optional[Any] = None,
    max_retries: int = 3,
) -> bool:
    """
    Thực hiện quy trình đồng bộ trạng thái an toàn tuyệt đối từ VPS về GitHub master:
    1. Chỉ chạy khi có biến môi trường GITHUB_ACTIONS hoặc khi force=True.
    2. Thiết lập thông tin tác giả commit.
    3. Kiểm tra và mở rộng shallow clone nếu cần.
    4. Fetch origin master để lấy dữ liệu mới nhất.
    5. Đọc remote state/bot_memory.json qua git show, hợp nhất không mất dữ liệu với local.
    6. Lưu file hợp nhất xuống đĩa và cập nhật vào memory_instance trong RAM nếu có.
    7. Reset soft về origin/master để mọi commit tiếp theo luôn là Fast-Forward sạch.
    8. Stage, commit và push lên origin/master với cơ chế retry.
    """
    l = log or logger
    if not os.environ.get("GITHUB_ACTIONS") and not force:
        return True

    # 1. Cấu hình định danh git bot
    run_git_cmd(["git", "config", "user.name", "dan86-bot"])
    run_git_cmd(["git", "config", "user.email", "bot@dan86.vn"])

    # 2. Xử lý shallow repository nếu có
    rc, stdout, _ = run_git_cmd(["git", "rev-parse", "--is-shallow-repository"])
    if rc == 0 and stdout == "true":
        l.info("Phát hiện shallow clone trên VPS, đang fetch unshallow...")
        run_git_cmd(["git", "fetch", "--unshallow", "origin", "master"], timeout=45)

    for attempt in range(1, max_retries + 1):
        try:
            # 3. Lấy commit mới nhất từ remote
            fetch_rc, _, fetch_err = run_git_cmd(["git", "fetch", "origin", "master"], timeout=30)
            if fetch_rc != 0:
                l.warning("Lần %d: git fetch origin master cảnh báo: %s", attempt, fetch_err)

            # 4. Trích xuất file memory từ origin/master
            show_rc, remote_json_text, _ = run_git_cmd(
                ["git", "show", "origin/master:state/bot_memory.json"], timeout=15
            )
            remote_data = {}
            if show_rc == 0 and remote_json_text:
                try:
                    remote_data = json.loads(remote_json_text)
                except Exception as e:
                    l.warning("Không thể parse remote bot_memory.json: %s", e)

            # 5. Đọc local memory và smart merge
            local_data = safe_load_json(MEMORY_FILE)
            merged_data, _ = smart_merge_memory(local_data, remote_data)

            # Lưu lại file đã hợp nhất
            safe_save_json(MEMORY_FILE, merged_data)

            # Cập nhật đối tượng BotMemoryStore trong RAM nếu có
            if memory_instance is not None:
                try:
                    memory_instance.load()
                except Exception:
                    pass

            # 6. Reset soft về origin/master
            # Di chuyển HEAD về origin/master nhưng giữ nguyên toàn bộ thay đổi ở working directory
            reset_rc, _, reset_err = run_git_cmd(["git", "reset", "--soft", "origin/master"], timeout=15)
            if reset_rc != 0:
                l.warning("Lần %d: git reset --soft origin/master cảnh báo: %s", attempt, reset_err)

            # 7. Stage 2 file trạng thái
            run_git_cmd(["git", "add", "state/bot_memory.json", "state/bot_status.json"], timeout=10)

            # 8. Kiểm tra xem có gì khác biệt so với origin/master không
            diff_rc, _, _ = run_git_cmd(["git", "diff", "--cached", "--quiet"], timeout=10)
            if diff_rc == 0:
                l.info("Trạng thái bộ nhớ và status trên VPS đã đồng bộ với GitHub.")
                return True

            # 9. Tạo commit mới
            commit_rc, _, commit_err = run_git_cmd(
                ["git", "commit", "-m", "chore: sync bot live status & memory [skip ci]"],
                timeout=15,
            )
            if commit_rc != 0:
                l.warning("Lần %d: git commit cảnh báo: %s", attempt, commit_err)

            # 10. Đẩy commit lên GitHub
            push_rc, _, push_err = run_git_cmd(["git", "push", "origin", "HEAD:master"], timeout=30)
            if push_rc == 0:
                l.info("Đã đồng bộ Live Status & Memory lên GitHub VPS thành công (Lần %d).", attempt)
                return True
            else:
                l.warning("Lần %d: git push bị từ chối: %s. Đang chuẩn bị thử lại...", attempt, push_err)
                time.sleep(2.0)

        except Exception as e_sync:
            l.warning("Lỗi ngoại lệ trong quá trình sync (Lần %d): %s", attempt, e_sync)
            time.sleep(2.0)

    l.error("Đã thử %d lần nhưng không thể đồng bộ trạng thái lên GitHub.", max_retries)
    return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    success = sync_state_to_github(force=True)
    sys.exit(0 if success else 1)
