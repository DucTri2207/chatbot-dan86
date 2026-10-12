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
    META_INBOX_COMMENTS_URL,
    SCAN_INTERVAL_SECONDS,
    STATE_DIR,
    STORAGE_STATE_FILE,
)
from bot.memory_store import BotMemoryStore
from bot.page_bot_engine import (
    create_bot_browser_context,
    process_facebook_comments_tab,
    process_messenger_inbox_tab,
    verify_logged_in,
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
    recent_logs = []
    log_file = os.path.join(LOGS_DIR, "bot_truc_page.log")
    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as lf:
                lines = lf.readlines()
            recent_logs = [ln.rstrip() for ln in lines[-60:] if ln.strip()]
        except Exception:
            pass

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
        "recent_logs": recent_logs,
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


def sync_state_to_github_if_vps(
    logger: logging.Logger,
    force: bool = False,
    memory: Optional[BotMemoryStore] = None,
) -> None:
    """
    Tự động commit & push state/bot_memory.json và state/bot_status.json lên GitHub
    ngay trong quá trình chạy trên VPS GitHub Actions bằng cơ chế Smart Merge và Fast-Forward,
    giúp Dashboard thời gian thực ở máy người dùng theo dõi được ngay lập tức từng bình luận, tin nhắn
    mà không bao giờ bị mất dữ liệu hay xung đột rebase!
    """
    if not os.environ.get("GITHUB_ACTIONS") and not force:
        return

    try:
        from bot.state_sync import sync_state_to_github

        sync_state_to_github(log=logger, force=force, memory_instance=memory)
    except Exception as e:
        logger.debug("Không thể đồng bộ live state lên GitHub: %s", e)


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

        # Bước 0: Làm ấm phiên đăng nhập Facebook và xác thực SSO trước khi bắt đầu quét
        logger.info("Đang kiểm tra và làm ấm phiên đăng nhập Facebook...")
        try:
            await page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2.0)
            logger.info("Đã kết nối máy chủ Facebook. Đang mở Meta Business Suite...")
            await page.goto(META_INBOX_COMMENTS_URL, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(3.0)
            logged_in_ok = await verify_logged_in(page)
            logger.info("Kết quả xác thực khởi động Meta Business Suite: %s (URL: %s)", logged_in_ok, page.url)
        except Exception as e_init:
            logger.warning("Cảnh báo khi làm ấm phiên khởi động: %s", e_init)

        cycle = 0
        try:
            while True:
                cycle += 1
                logger.info("--- Bắt đầu chu kỳ quét #%d ---", cycle)
                cmt_replied = 0
                inbox_replied = 0

                try:
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
                except Exception as e_cycle:
                    logger.error("Lỗi trong chu kỳ quét #%d: %s. Đang tự động hồi phục...", cycle, e_cycle)
                    try:
                        await page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=30000)
                    except Exception:
                        pass

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

                # Tự động đồng bộ Live Status & Memory lên GitHub VPS nếu có bình luận/tin nhắn mới hoặc định kỳ
                if cmt_replied > 0 or inbox_replied > 0 or cycle % 3 == 0:
                    sync_state_to_github_if_vps(logger, memory=memory)

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
            # Đồng bộ kết thúc ca lên GitHub
            sync_state_to_github_if_vps(logger, force=True, memory=memory)
            # Lưu lại trạng thái cookies mới nhất nếu phiên vẫn còn giữ quyền đăng nhập (c_user) và bảo toàn origins
            try:
                active_cookies = await context.cookies()
                if any(c.get("name") == "c_user" for c in active_cookies):
                    preserved_origins = []
                    if os.path.exists(STORAGE_STATE_FILE):
                        try:
                            with open(STORAGE_STATE_FILE, "r", encoding="utf-8") as f_prev:
                                preserved_origins = json.load(f_prev).get("origins", [])
                        except Exception:
                            pass
                    await context.storage_state(path=STORAGE_STATE_FILE)
                    if preserved_origins:
                        try:
                            with open(STORAGE_STATE_FILE, "r", encoding="utf-8") as f_new:
                                new_data = json.load(f_new)
                            new_origins_by_dom = {
                                o.get("origin"): o for o in new_data.get("origins", []) if isinstance(o, dict)
                            }
                            for prev_o in preserved_origins:
                                if isinstance(prev_o, dict):
                                    dom = prev_o.get("origin")
                                    if dom and (
                                        dom not in new_origins_by_dom
                                        or len(new_origins_by_dom[dom].get("localStorage", []))
                                        < len(prev_o.get("localStorage", []))
                                    ):
                                        new_origins_by_dom[dom] = prev_o
                            new_data["origins"] = list(new_origins_by_dom.values())
                            with open(STORAGE_STATE_FILE, "w", encoding="utf-8") as f_fix:
                                json.dump(new_data, f_fix, ensure_ascii=False, indent=2)
                        except Exception:
                            pass
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
