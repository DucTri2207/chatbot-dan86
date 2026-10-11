"""
Bước 2: Điểm khởi chạy trung tâm của Bot Trực Fanpage DAN86 (Dần86Farm) 24/24.
Hỗ trợ chạy trên cả Máy tính Windows cá nhân và VPS Linux trên GitHub Actions.

Tham số CLI:
  --dry-run            Chế độ xem trước (chỉ đọc bình luận/tin nhắn và in câu trả lời dự kiến, chưa bấm gửi).
  --headless           Chạy ngầm không hiện cửa sổ trình duyệt (tự động bật khi trên VPS GitHub).
  --once               Chỉ quét 1 vòng (Comment + Messenger) rồi dừng.
  --max-minutes 320    Thời gian chạy tối đa của 1 ca VPS trước khi bàn giao sang ca tiếp theo (mặc định 320 phút trên GitHub).
"""

import argparse
import asyncio
import json
import logging
import os
import random
import sys
import time
from typing import Optional

# Đảm bảo in tiếng Việt có dấu chuẩn UTF-8 trên Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from playwright.async_api import async_playwright

from bot.auth_helper import sync_facebook_credentials_from_dan86
from bot.bot_config import (
    BOT_STATUS_FILE,
    LOGS_DIR,
    SCAN_INTERVAL_SECONDS,
    STATE_DIR,
    STORAGE_STATE_FILE,
)
from bot.memory_store import BotMemoryStore
from bot.page_bot_engine import (
    create_bot_browser_context,
    process_facebook_comments_tab,
    process_messenger_inbox_tab,
)


def update_bot_heartbeat(
    running: bool,
    pid: Optional[int] = None,
    mode: str = "live",
    cycle: int = 0,
    started_at: float = 0.0,
    headless: bool = False,
    stats: Optional[dict] = None,
) -> None:
    """Ghi nhận trạng thái sống của Bot ra state/bot_status.json cho Dashboard theo dõi."""
    os.makedirs(STATE_DIR, exist_ok=True)
    payload = {
        "running": running,
        "pid": pid or os.getpid(),
        "mode": mode,
        "cycle": cycle,
        "headless": headless,
        "started_at": started_at or time.time(),
        "last_heartbeat": time.time(),
        "last_heartbeat_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stats": stats or {},
    }
    if not running:
        payload["stopped_at"] = time.time()
        payload["stopped_at_str"] = time.strftime("%Y-%m-%d %H:%M:%S")

    try:
        temp_file = f"{BOT_STATUS_FILE}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, BOT_STATUS_FILE)
    except Exception:
        pass


def setup_logging() -> None:
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_file = os.path.join(LOGS_DIR, "bot_truc_page.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


async def run_bot_loop(
    headless: bool = False,
    dry_run: bool = False,
    run_once: bool = False,
    max_minutes: float = 0.0,
) -> None:
    logger = logging.getLogger("dan86_page_bot")
    mode_str = "dry-run" if dry_run else "live"

    # Tự động nạp cookies từ d:\dan86 nếu chưa có
    if not os.path.exists(STORAGE_STATE_FILE):
        try:
            sync_res = sync_facebook_credentials_from_dan86()
            if sync_res.get("success"):
                logger.info("Tự động trích xuất cookies thành công từ d:\\dan86: %s", sync_res.get("message"))
        except Exception as e:
            logger.warning("Không thể tự động đồng bộ cookies từ d:\\dan86: %s", e)

    memory = BotMemoryStore()
    start_time = time.time()
    current_pid = os.getpid()

    update_bot_heartbeat(
        running=True,
        pid=current_pid,
        mode=mode_str,
        cycle=0,
        started_at=start_time,
        headless=headless,
        stats=memory.data.get("stats", {}),
    )

    logger.info("=" * 70)
    logger.info("🚀 KHỞI ĐỘNG BOT TRỰC FANPAGE DAN86 (DẦN86FARM) 24/24")
    logger.info("   - Chế độ Headless (Chạy ngầm) : %s", headless)
    logger.info("   - Chế độ Dry-Run (Xem trước)  : %s", dry_run)
    logger.info(
        "   - Thời lượng ca chạy tối đa   : %s",
        f"{max_minutes} phút" if max_minutes > 0 else "Không giới hạn (Liên tục)",
    )
    logger.info("=" * 70)

    async with async_playwright() as p:
        browser, context = await create_bot_browser_context(
            playwright=p,
            headless=headless,
            use_persistent_profile=False,
        )
        page = context.pages[0] if context.pages else await context.new_page()

        cycle = 0
        try:
            while True:
                cycle += 1
                logger.info("--- Bắt đầu chu kỳ quét #%d ---", cycle)

                # 1. Quét Tab Bình luận Facebook (Rep cmt random + Tự động Inbox người cmt)
                cmt_replied = await process_facebook_comments_tab(
                    page=page,
                    memory=memory,
                    dry_run=dry_run,
                )

                # 2. Quét Tab Messenger Inbox (Lần 1 chào random / Lần 2 báo đợi nhân viên random)
                inbox_replied = await process_messenger_inbox_tab(
                    page=page,
                    memory=memory,
                    dry_run=dry_run,
                )

                logger.info(
                    "Hoàn tất chu kỳ #%d: Đã xử lý %d bình luận & %d tin nhắn Inbox. Tổng thống kê: %s",
                    cycle,
                    cmt_replied,
                    inbox_replied,
                    memory.data.get("stats", {}),
                )

                update_bot_heartbeat(
                    running=True,
                    pid=current_pid,
                    mode=mode_str,
                    cycle=cycle,
                    started_at=start_time,
                    headless=headless,
                    stats=memory.data.get("stats", {}),
                )

                if run_once:
                    logger.info("Đã hoàn thành 1 vòng quét (--once). Kết thúc.")
                    break

                if max_minutes > 0:
                    elapsed_min = (time.time() - start_time) / 60.0
                    if elapsed_min >= max_minutes:
                        logger.info(
                            "Đã chạy đủ %.1f / %.1f phút của ca VPS hiện tại. Lưu bộ nhớ và chuyển ca mới...",
                            elapsed_min,
                            max_minutes,
                        )
                        break

                sleep_sec = random.uniform(SCAN_INTERVAL_SECONDS[0], SCAN_INTERVAL_SECONDS[1])
                logger.info("Nghỉ %.0f giây trước chu kỳ quét tiếp theo...", sleep_sec)
                await asyncio.sleep(sleep_sec)

        finally:
            memory.save()
            update_bot_heartbeat(
                running=False,
                pid=current_pid,
                mode=mode_str,
                cycle=cycle,
                started_at=start_time,
                headless=headless,
                stats=memory.data.get("stats", {}),
            )
            # Lưu lại trạng thái cookies mới nhất nếu phiên vẫn còn giữ quyền đăng nhập (c_user)
            try:
                active_cookies = await context.cookies()
                if any(c.get("name") == "c_user" for c in active_cookies):
                    await context.storage_state(path=STORAGE_STATE_FILE)
            except Exception:
                pass
            await context.close()
            if browser is not None:
                await browser.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bot Trực Fanpage DAN86 24/24")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chế độ xem trước: chỉ đọc và in câu trả lời dự kiến, không bấm gửi thật.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Chạy trình duyệt ngầm không hiện cửa sổ.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Chỉ quét 1 vòng rồi thoát.",
    )
    parser.add_argument(
        "--max-minutes",
        type=float,
        default=0.0,
        help="Số phút chạy tối đa trước khi thoát để chuyển ca VPS (ví dụ: 320).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    setup_logging()
    args = parse_args()
    is_headless = args.headless or bool(os.environ.get("GITHUB_ACTIONS"))
    try:
        asyncio.run(
            run_bot_loop(
                headless=is_headless,
                dry_run=args.dry_run,
                run_once=args.once,
                max_minutes=args.max_minutes,
            )
        )
    except KeyboardInterrupt:
        print("\nĐã dừng Bot theo yêu cầu người dùng.")
        sys.exit(0)
