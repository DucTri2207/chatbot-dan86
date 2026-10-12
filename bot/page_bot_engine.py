"""
Playwright Core Engine cho Bot Trực Fanpage DAN86 (Meta Business Suite).
Hỗ trợ:
1. Quét Tab Bình luận Facebook:
   - Thả Like + Random trả lời bình luận công khai (1 lần duy nhất).
   - Tự động bấm "Gửi tin nhắn" (Message) để Inbox riêng cho người bình luận đó (Random câu trả lời).
2. Quét Tab Messenger Inbox:
   - Khách nhắn lần đầu -> Random mẫu chào & tư vấn sản phẩm lần 1.
   - Khách im một thời gian rồi nhắn lại (hoặc nhắn tiếp) -> Random mẫu "Đợi nhân viên sẽ liên hệ lại ngay"
     rồi tạm dừng tự động trả lời để nhường cho nhân viên thật.
"""

import asyncio
import base64
import json
import logging
import os
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import Browser, BrowserContext, Locator, Page, Playwright

from bot.bot_config import (
    ACTION_COOLDOWN_SECONDS,
    CHROME_PROFILE_DIR,
    CUSTOMER_ANTI_SPAM_COOLDOWN_SECONDS,
    GITHUB_SECRET_EXPORT_FILE,
    LOGS_DIR,
    MAX_THREADS_PER_CYCLE,
    META_INBOX_COMMENTS_URL,
    META_INBOX_MESSENGER_URL,
    PAGE_NAMES,
    STORAGE_STATE_FILE,
    SYSTEM_BLACKLIST_STRINGS,
    TEST_ONLY_AUTHOR_WHITELIST,
    TYPING_DELAY_MS,
    clean_customer_name,
)
from bot.memory_store import BotMemoryStore, normalize_text

logger = logging.getLogger("dan86_page_bot")


def restore_storage_state_from_env() -> bool:
    """
    Khôi phục file state/fb_storage_state.json từ biến môi trường FB_STORAGE_STATE
    (dùng khi chạy tự động trên VPS GitHub Actions) hoặc tự khôi phục từ GITHUB_SECRET_VALUE.txt.
    """
    os.makedirs(os.path.dirname(STORAGE_STATE_FILE) or STATE_DIR, exist_ok=True)
    env_b64 = os.environ.get("FB_STORAGE_STATE", "").strip()

    if env_b64:
        try:
            # Hỗ trợ cả chuỗi JSON trực tiếp hoặc chuỗi Base64
            if env_b64.startswith("{"):
                raw_json = env_b64
            else:
                raw_json = base64.b64decode(env_b64).decode("utf-8")
            parsed = json.loads(raw_json)
            with open(STORAGE_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(parsed, f, ensure_ascii=False, indent=2)
            logger.info("Đã khôi phục phiên đăng nhập Facebook từ FB_STORAGE_STATE.")
            return True
        except Exception as e:
            logger.error("Lỗi giải mã FB_STORAGE_STATE: %s", e)

    # Nếu không có biến môi trường, kiểm tra xem file storage hiện tại có đầy đủ cookies và origins không
    is_storage_valid = False
    if os.path.exists(STORAGE_STATE_FILE):
        try:
            with open(STORAGE_STATE_FILE, "r", encoding="utf-8") as f:
                cur_data = json.load(f)
            c_names = {c.get("name") for c in cur_data.get("cookies", []) if isinstance(c, dict)}
            has_origins = any("business.facebook.com" in o.get("origin", "") for o in cur_data.get("origins", []) if isinstance(o, dict))
            if "c_user" in c_names and "xs" in c_names and has_origins:
                is_storage_valid = True
        except Exception:
            pass

    # Nếu file storage chưa hợp lệ nhưng có file GITHUB_SECRET_VALUE.txt lưu trữ phiên chuẩn
    if not is_storage_valid and os.path.exists(GITHUB_SECRET_EXPORT_FILE):
        try:
            with open(GITHUB_SECRET_EXPORT_FILE, "r", encoding="utf-8") as f_sec:
                sec_b64 = f_sec.read().strip()
            if sec_b64:
                sec_json = base64.b64decode(sec_b64).decode("utf-8")
                sec_parsed = json.loads(sec_json)
                with open(STORAGE_STATE_FILE, "w", encoding="utf-8") as f_out:
                    json.dump(sec_parsed, f_out, ensure_ascii=False, indent=2)
                logger.info("Đã tự động khôi phục fb_storage_state.json hoàn chỉnh từ GITHUB_SECRET_VALUE.txt!")
                return True
        except Exception as e_sec:
            logger.warning("Không thể khôi phục từ GITHUB_SECRET_VALUE.txt: %s", e_sec)

    return os.path.exists(STORAGE_STATE_FILE)


async def create_bot_browser_context(
    playwright: Playwright,
    headless: bool = False,
    use_persistent_profile: bool = False,
) -> Tuple[Optional[Browser], BrowserContext]:
    """Khởi tạo trình duyệt Playwright siêu nhẹ với phiên đăng nhập đã lưu."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    restore_storage_state_from_env()

    # Kiểm tra xem file storage hiện tại đã đầy đủ c_user, xs và origins chưa
    need_sync = True
    if os.path.exists(STORAGE_STATE_FILE):
        try:
            with open(STORAGE_STATE_FILE, "r", encoding="utf-8") as f_chk:
                chk_data = json.load(f_chk)
            chk_names = {c.get("name") for c in chk_data.get("cookies", []) if isinstance(c, dict)}
            chk_biz = any("business.facebook.com" in o.get("origin", "") for o in chk_data.get("origins", []) if isinstance(o, dict))
            if "c_user" in chk_names and "xs" in chk_names and chk_biz:
                need_sync = False
        except Exception:
            pass

    # Chỉ đồng bộ cookies khi chưa có phiên đăng nhập hoàn chỉnh
    if need_sync:
        try:
            from bot.auth_helper import sync_facebook_credentials_from_dan86
            sync_res = sync_facebook_credentials_from_dan86()
            if sync_res.get("success"):
                logger.info("Tự động đồng bộ cookies thành công (%d cookies).", sync_res.get("cookies_count", 0))
        except Exception as e:
            logger.warning("Không thể tự động đồng bộ cookies: %s", e)

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-notifications",
    ]
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    # Ưu tiên chế độ siêu nhẹ (Storage State ~3.8KB): Không tạo folder cache nặng máy, không bị xung đột Profile Lock
    if os.path.exists(STORAGE_STATE_FILE):
        browser = await playwright.chromium.launch(headless=headless, args=launch_args)
        context = await browser.new_context(
            storage_state=STORAGE_STATE_FILE,
            viewport={"width": 1440, "height": 900},
            locale="vi-VN",
            user_agent=user_agent,
        )
        return browser, context

    # Nếu chưa có storage_state và muốn mở trực tiếp Persistent Profile (d:\dan86\.chrome_profile)
    if use_persistent_profile and os.path.exists(CHROME_PROFILE_DIR) and not os.environ.get("GITHUB_ACTIONS"):
        try:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=CHROME_PROFILE_DIR,
                headless=headless,
                args=launch_args,
                viewport={"width": 1440, "height": 900},
                locale="vi-VN",
                user_agent=user_agent,
            )
            return None, context
        except Exception as e:
            logger.warning(
                "Không thể mở trực tiếp profile %s (có thể đang mở ở cửa sổ khác): %s. Mở trình duyệt mới.",
                CHROME_PROFILE_DIR,
                e,
            )

    # Trình duyệt mặc định
    browser = await playwright.chromium.launch(headless=headless, args=launch_args)
    context = await browser.new_context(
        viewport={"width": 1440, "height": 900},
        locale="vi-VN",
        user_agent=user_agent,
    )
    return browser, context


async def human_sleep(min_sec: float = 1.5, max_sec: float = 3.5) -> None:
    """Nghỉ ngơi ngẫu nhiên giống thao tác của người thật."""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def safe_click(
    locator: Locator,
    timeout: int = 2500,
    position: Optional[Dict[str, float]] = None,
) -> bool:
    """
    Thực hiện nhấp chuột an toàn chống lỗi pointer-events interception:
    1. Cuộn phần tử vào tầm nhìn (scroll_into_view_if_needed).
    2. Thử nhấp bằng Playwright với force=True và timeout quy định.
    3. Nếu gặp ngoại lệ / timeout (do bị phần tử khác che phủ / subtree intercepts pointer events),
       bắt ngoại lệ, ghi log cảnh báo và kích hoạt synthetic click bằng JavaScript DOM.
    """
    try:
        await locator.scroll_into_view_if_needed(timeout=1500)
    except Exception:
        pass

    try:
        if position:
            await locator.click(timeout=timeout, force=True, position=position)
        else:
            await locator.click(timeout=timeout, force=True)
        return True
    except Exception as e:
        logger.warning("safe_click: click tiêu chuẩn gặp lỗi (%s), kích hoạt fallback JavaScript...", e)
        try:
            await locator.evaluate(
                "el => { el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window})); el.click(); }"
            )
            return True
        except Exception as js_err:
            logger.warning("safe_click: fallback JavaScript cũng thất bại (%s)", js_err)
            return False


async def type_human_like(page: Page, locator: Locator, text: str) -> None:
    """
    Gõ văn bản vào ô chat giống người thật (hỗ trợ xuống dòng Shift+Enter
    để không bị gửi sớm khi mẫu câu có nhiều dòng).
    """
    await safe_click(locator, timeout=2500)
    await human_sleep(0.4, 0.9)

    lines = text.split("\n")
    for idx, line in enumerate(lines):
        if line:
            delay_ms = random.randint(TYPING_DELAY_MS[0], TYPING_DELAY_MS[1])
            await locator.press_sequentially(line, delay=delay_ms)
        if idx < len(lines) - 1:
            await page.keyboard.press("Shift+Enter")
            await asyncio.sleep(random.uniform(0.15, 0.35))

    await human_sleep(0.5, 1.2)


def is_page_author_name(text: str) -> bool:
    """Kiểm tra xem tên người gửi có phải là Fanpage Dần86Farm của mình không."""
    norm = normalize_text(text)
    if not norm:
        return False
    return any(p in norm for p in PAGE_NAMES)


async def verify_logged_in(page: Page) -> bool:
    """
    Kiểm tra xem trình duyệt đã đăng nhập vào Meta Business Suite chưa.
    Tự động xử lý nút bấm đăng nhập một chạm 'Tiếp tục bằng Facebook' / 'Tiếp tục dưới tên Đức Trí'
    nếu Meta Business Suite đang ở màn hình chuyển giao phiên (SSO bridge).
    Hoàn toàn chống deadlock, không chờ vô ích khi popup yêu cầu mật khẩu thủ công,
    và nhận diện chính xác giao diện Hộp thư/Bình luận của MBS ngay cả khi URL có query params chứa 'login'.
    """
    import urllib.parse

    parsed = urllib.parse.urlparse(page.url)
    path = parsed.path.lower()

    # 1. Kiểm tra nhanh giao diện Hộp thư / Bình luận MBS (Inbox indicators)
    # Nếu các phần tử chính của Meta Business Suite đã hiện diện, kết luận đã đăng nhập thành công ngay lập tức!
    inbox_indicators = [
        '[role="navigation"]',
        '[data-pagelet*="ThreadList"]',
        'div._a6ag._a6ah',
        'div[role="presentation"].x1ypdohk',
        'div:has-text("Bình luận trên Facebook")',
        'div:has-text("Tất cả tin nhắn")',
        'div:has-text("Hộp thư")',
    ]
    for ind in inbox_indicators:
        try:
            loc = page.locator(ind).first
            if await loc.count() > 0 and await loc.is_visible():
                return True
        except Exception:
            pass

    # 2. Nếu trang chứa form nhập tài khoản / mật khẩu thông thường trên trang chính
    try:
        login_form = await page.locator('input[name="email"], input[name="pass"]').count()
        if login_form > 0:
            return False
    except Exception:
        pass

    # 3. Kiểm tra xem có đang ở trang login thực sự không (dựa trên đường dẫn path)
    is_at_loginpage = "/business/loginpage" in path or path.startswith("/login") or path == "/login"

    if is_at_loginpage:
        logger.info("Phát hiện màn hình chuyển tiếp Meta Business (%s). Đang kiểm tra nút đăng nhập một chạm...", page.url[:80])
        sso_selectors = [
            'div:has-text("Tiếp tục bằng Facebook")',
            'button:has-text("Tiếp tục bằng Facebook")',
            'a:has-text("Tiếp tục bằng Facebook")',
            'div[role="button"]:has-text("Tiếp tục bằng Facebook")',
            'div:has-text("Tiếp tục dưới tên")',
            'button:has-text("Tiếp tục dưới tên")',
            'a:has-text("Tiếp tục dưới tên")',
            'div[role="button"]:has-text("Tiếp tục dưới tên")',
            'div:has-text("Log in with Facebook")',
            'button:has-text("Log in with Facebook")',
            'a:has-text("Log in with Facebook")',
        ]

        clicked = False
        sso_success = False
        for sel in sso_selectors:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                logger.info("Bấm nút bắc cầu phiên Facebook sang Meta: %s", sel)
                popup_future = asyncio.get_event_loop().create_future()
                def on_sso_page(new_p):
                    if not popup_future.done():
                        popup_future.set_result(new_p)

                page.context.on("page", on_sso_page)
                try:
                    await loc.click(timeout=5000, force=True)
                    try:
                        popup = await asyncio.wait_for(popup_future, timeout=6.0)
                        await popup.wait_for_load_state("domcontentloaded")
                        await asyncio.sleep(0.5)

                        # Bấm nút 'Tiếp tục' trong popup
                        p_btn = popup.locator(
                            'div[role="button"]:has-text("Tiếp tục"), '
                            'button:has-text("Tiếp tục"), '
                            'div:has-text("Tiếp tục"), '
                            'a:has-text("Tiếp tục"), '
                            '[aria-label*="Tiếp tục"], '
                            'button[name="__CONFIRM__"], '
                            'div[role="button"]:has-text("Continue"), '
                            'button:has-text("Continue")'
                        ).first
                        if await p_btn.count() > 0:
                            await p_btn.click(force=True)
                        else:
                            txt_loc = popup.locator('text="Tiếp tục"').first
                            if await txt_loc.count() > 0:
                                await txt_loc.click(force=True)

                        await asyncio.sleep(0.5)
                        # Kiểm tra xem popup có đòi mật khẩu thủ công không
                        if not popup.is_closed():
                            pass_count = await popup.locator('input[name="pass"], input[type="password"]').count()
                            if pass_count > 0:
                                logger.warning("Popup SSO yêu cầu nhập mật khẩu thủ công (chưa có token một chạm hoạt động). Đóng popup để không chặn vòng quét.")
                                try:
                                    await popup.close()
                                except Exception:
                                    pass
                                sso_success = False
                            else:
                                # Chờ tối đa 6s cho popup tự đóng hoặc chuyển hướng
                                try:
                                    await popup.wait_for_event("close", timeout=6000)
                                    sso_success = True
                                except Exception:
                                    if not popup.is_closed():
                                        pass_count = await popup.locator('input[name="pass"], input[type="password"]').count()
                                        if pass_count > 0:
                                            sso_success = False
                                        else:
                                            sso_success = True
                                        try:
                                            await popup.close()
                                        except Exception:
                                            pass
                                    else:
                                        sso_success = True
                    except Exception as e_pop:
                        logger.debug("Không mở popup SSO hoặc popup xử lý nội bộ: %s", e_pop)
                        # Kiểm tra xem chính tab hiện tại có đang tự chuyển hướng không (direct navigation)
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=3000)
                        except Exception:
                            pass
                        cur_p = urllib.parse.urlparse(page.url).path.lower()
                        if "/business/loginpage" not in cur_p and not cur_p.startswith("/login"):
                            logger.info("Trang chính đã tự chuyển hướng thành công mà không cần popup: %s", page.url[:80])
                            sso_success = True
                    finally:
                        try:
                            page.context.remove_listener("page", on_sso_page)
                        except Exception:
                            pass

                    clicked = True
                    break
                except Exception as e_click:
                    logger.debug("Lỗi bấm nút SSO: %s", e_click)
                    try:
                        page.context.remove_listener("page", on_sso_page)
                    except Exception:
                        pass

        if clicked and sso_success:
            # Chờ trang chính tự chuyển hướng hoặc chủ động điều hướng tới URL inbox mục tiêu
            try:
                for _ in range(6):
                    await asyncio.sleep(0.5)
                    cur_p = urllib.parse.urlparse(page.url).path.lower()
                    if "/business/loginpage" not in cur_p and not cur_p.startswith("/login"):
                        break
                cur_p = urllib.parse.urlparse(page.url).path.lower()
                if "/business/loginpage" in cur_p or cur_p.startswith("/login"):
                    await page.goto(META_INBOX_COMMENTS_URL, wait_until="domcontentloaded", timeout=30000)
                await human_sleep(2.0, 3.5)
            except Exception as e_nav:
                logger.debug("Lỗi điều hướng trang chính sau SSO: %s", e_nav)
        elif clicked and not sso_success:
            # Kiểm tra phòng vệ cuối cùng xem trang chính có tự về inbox không
            cur_p = urllib.parse.urlparse(page.url).path.lower()
            if "/business/loginpage" not in cur_p and not cur_p.startswith("/login"):
                pass
            else:
                return False

    # Đánh giá lại trạng thái sau chuyển hướng
    parsed = urllib.parse.urlparse(page.url)
    path = parsed.path.lower()

    if "checkpoint" in path:
        return False
    if "/business/loginpage" in path or path.startswith("/login"):
        return False

    # Kiểm tra xác nhận lần cuối qua sự tồn tại của UI Hộp thư
    for ind in inbox_indicators:
        try:
            if await page.locator(ind).first.count() > 0:
                break
        except Exception:
            pass
    else:
        # Nếu không có bất kỳ chỉ báo Hộp thư nào:
        # 1. Nếu có form đăng nhập: chắc chắn chưa đăng nhập
        if await page.locator('input[name="email"], input[name="pass"]').count() > 0:
            return False
        # 2. Nếu URL không phải là trang inbox của Meta: không xác nhận thành công bừa bãi
        if "/latest/inbox" not in path:
            return False

    # Lưu cố định toàn bộ cookies (gồm cả business.facebook.com) ngay sau khi xác thực/vào inbox thành công
    try:
        from bot.auth_helper import export_github_secret_file
        # Bảo toàn origins (localStorage business.facebook.com) hiện có
        preserved_origins = []
        if os.path.exists(STORAGE_STATE_FILE):
            try:
                with open(STORAGE_STATE_FILE, "r", encoding="utf-8") as f_prev:
                    p_data = json.load(f_prev)
                preserved_origins = p_data.get("origins", [])
            except Exception:
                pass

        await page.context.storage_state(path=str(STORAGE_STATE_FILE))

        # Bảo toàn mọi origins quan trọng (đặc biệt business.facebook.com) từ preserved_origins
        try:
            with open(STORAGE_STATE_FILE, "r", encoding="utf-8") as f_new:
                new_data = json.load(f_new)
            new_origins_by_dom = {o.get("origin"): o for o in new_data.get("origins", []) if isinstance(o, dict)}
            for prev_o in preserved_origins:
                if isinstance(prev_o, dict):
                    dom = prev_o.get("origin")
                    if dom:
                        if dom not in new_origins_by_dom or len(new_origins_by_dom[dom].get("localStorage", [])) < len(prev_o.get("localStorage", [])):
                            new_origins_by_dom[dom] = prev_o
            new_data["origins"] = list(new_origins_by_dom.values())
            with open(STORAGE_STATE_FILE, "w", encoding="utf-8") as f_fix:
                json.dump(new_data, f_fix, ensure_ascii=False, indent=2)
        except Exception:
            pass

        export_github_secret_file(str(STORAGE_STATE_FILE))
        logger.info("Đã lưu cố định fb_storage_state.json và cập nhật GITHUB_SECRET_VALUE.txt thành công!")
    except Exception as e_save:
        logger.warning("Không thể lưu storage_state sau xác thực: %s", e_save)

    return True


def clean_comment_text(text: str) -> str:
    """
    Cắt bỏ sạch tiền tố thời gian khỏi nội dung bình luận:
    Ví dụ: '1 năm Ib' -> 'Ib'
           '2 giờ Giá sao bạn' -> 'Giá sao bạn'
           '15 giây Cho e xin giá' -> 'Cho e xin giá'
           'vừa xong Cho e xin giá' -> 'Cho e xin giá'
    """
    if not text:
        return ""
    # Cắt bỏ tiền tố thời gian dạng: '1 năm', '2 tháng', '10 tuần', '3 ngày', '2 giờ', '15 phút', '30 giây', etc.
    cleaned = re.sub(
        r'^\s*\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm|s|m|h|d|w|y|secs?|mins?|hours?|days?|weeks?|months?|years?)\s*(?:trước|ago)?\s*',
        '',
        text,
        flags=re.IGNORECASE,
    ).strip()
    # Cắt bỏ các tiền tố như 'vừa xong', 'just now', 'hôm qua', 'yesterday'
    cleaned = re.sub(
        r'^\s*(?:vừa xong|just now|hôm qua|yesterday)\s*',
        '',
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned if cleaned else text.strip()


def is_old_comment_timestamp(text: str, aria: str = "") -> bool:
    """
    Kiểm tra xem bình luận có phải là bình luận cũ không:
    - Bình luận cũ: có dấu thời gian 'tuần', 'tháng', 'năm' (hoặc 'week', 'month', 'year', 'w', 'y')
    - Hoặc số ngày > 3 ngày (ví dụ: '4 ngày', '5 ngày', '10 ngày'...).
    - Chỉ xử lý bình luận MỚI: 'vừa xong', 'giây', 'phút', 'giờ', 'hôm qua', '1 ngày'..'3 ngày'.
    """
    combined = f"{text or ''} {aria or ''}".lower()

    # 1. Tuần, tháng, năm (bao gồm w, y)
    if re.search(r'\b\d+\s*(?:tuần|tháng|năm|week|month|year|w|y)s?\b', combined):
        return True
    if any(k in combined for k in [
        "năm trước", "tháng trước", "tuần trước",
        "years ago", "months ago", "weeks ago",
        "1 năm", "2 năm", "3 năm", "4 năm", "5 năm",
    ]):
        return True

    # 2. Số ngày > 3
    day_match = re.search(r'\b(\d+)\s*(?:ngày|days?|d)\b', combined)
    if day_match:
        try:
            num_days = int(day_match.group(1))
            if num_days > 3:
                return True
        except ValueError:
            pass

    return False


async def ensure_newest_comments_filter(page: Page) -> bool:
    """
    Chuyển chế độ sắp xếp bình luận bài viết sang 'Mới nhất' (Newest) hoặc 'Tất cả bình luận' (All comments).
    """
    try:
        filter_btn_selectors = [
            'div[role="button"]:has-text("Phù hợp nhất")',
            'span:has-text("Phù hợp nhất")',
            'div[role="button"]:has-text("Most relevant")',
            'span:has-text("Most relevant")',
            'div[role="button"]:has-text("Bình luận hàng đầu")',
            'span:has-text("Bình luận hàng đầu")',
            'div[role="button"]:has-text("Top comments")',
        ]
        btn = None
        for sel in filter_btn_selectors:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                btn = loc
                break

        if btn is not None:
            logger.info("Phát hiện bộ lọc bình luận 'Phù hợp nhất', đang chuyển sang 'Mới nhất' / 'Tất cả bình luận'...")
            await btn.click(timeout=2500)
            await human_sleep(0.8, 1.5)

            opt_selectors = [
                'div[role="menuitem"]:has-text("Mới nhất")',
                'div[role="button"]:has-text("Mới nhất")',
                'span:has-text("Mới nhất")',
                'div[role="menuitem"]:has-text("Newest")',
                'div[role="menuitem"]:has-text("Tất cả bình luận")',
                'div[role="button"]:has-text("Tất cả bình luận")',
                'span:has-text("Tất cả bình luận")',
                'div[role="menuitem"]:has-text("All comments")',
            ]
            for o_sel in opt_selectors:
                o_loc = page.locator(o_sel).first
                if await o_loc.count() > 0 and await o_loc.is_visible():
                    await o_loc.click(timeout=2500)
                    await human_sleep(1.5, 2.5)
                    logger.info("Đã chuyển bộ lọc bình luận thành công: %s", o_sel)
                    return True
    except Exception as e:
        logger.debug("Không thể đổi bộ lọc bình luận: %s", e)
    return False


# ==============================================================================
# ==============================================================================
# PHẦN 1: QUÉT & TRẢ LỜI BÌNH LUẬN FACEBOOK + TỰ ĐỘNG INBOX NGƯỜI BÌNH LUẬN
# ==============================================================================
async def expand_all_comment_replies(page: Page) -> int:
    """
    Tự động bấm mở rộng các phản hồi bị ẩn dưới nút:
    'Xem ... phản hồi', 'Xem thêm phản hồi', 'Xem 1 phản hồi', 'Xem thêm bình luận', 'View replies'
    để kiểm tra chính xác 100% bình luận nào đã có Page trả lời.
    """
    expanded_count = 0
    try:
        see_more_selectors = [
            'button:has-text("Xem"):has-text("phản hồi")',
            'div[role="button"]:has-text("Xem"):has-text("phản hồi")',
            'span:has-text("Xem"):has-text("phản hồi")',
            'button:has-text("Xem thêm bình luận")',
            'div[role="button"]:has-text("Xem thêm bình luận")',
            'span:has-text("Xem thêm bình luận")',
            'button:has-text("View"):has-text("repl")',
            'div[role="button"]:has-text("View"):has-text("repl")',
        ]
        for sel in see_more_selectors:
            btns = page.locator(sel)
            cnt = await btns.count()
            for idx in range(min(cnt, 5)):
                btn = btns.nth(idx)
                if await btn.is_visible():
                    txt = (await btn.inner_text() or "").strip().lower()
                    if any(k in txt for k in ["xem", "view"]):
                        try:
                            await btn.click(timeout=1500)
                            expanded_count += 1
                            await asyncio.sleep(0.5)
                        except Exception:
                            pass
        if expanded_count > 0:
            await human_sleep(1.0, 2.0)
    except Exception as e:
        logger.debug("Không thể mở rộng phản hồi bình luận: %s", e)
    return expanded_count


async def inspect_comment_panel(page: Page) -> Dict[str, Any]:
    """
    Phân tích khung chi tiết bình luận bên phải của Meta Business Suite:
    - Trích xuất Post ID từ tham số selected_item_id trong URL.
    - Tìm và phân tích tất cả các bình luận của khách trên bài viết.
    - Hỗ trợ đầy đủ mọi bình luận kể cả 1 ký tự ('.', emoji, icon, số, chữ ngắn).
    - Nhận diện chính xác bình luận nào ngay bên dưới CHƯA có câu trả lời của Page (!hasReplyBelow).
    - Đánh dấu data-attributes lên DOM để Playwright định vị chính xác:
      + data-dan86-reply-target: article bình luận cần trả lời
      + data-dan86-reply-btn: nút Trả lời lồng nhau (Reply)
      + data-dan86-msg-btn: nút Nhắn tin / See Chat riêng
    """
    js_code = r"""
    (pageNames) => {
        const blacklist = [
            "chỉ báo trạng thái online",
            "online status indicator",
            "đang hoạt động",
            "đang có mặt",
            "hộp thư",
            "chưa đọc",
            "bình luận trên trang",
            "trao đổi thêm",
            "tạo quảng cáo",
            "thông tin chi tiết",
            "quy trình tự động hóa",
            "quảng bá",
            "theo dõi lại",
            "theo dõi",
            "mới nhất",
            "phù hợp nhất",
            "tất cả bình luận",
            "xem thêm",
            "xem 1 phản hồi",
            "xem phản hồi",
            "ẩn",
            "trả lời",
            "phản hồi",
        ];

        const isSystemString = (s) => {
            if (!s) return true;
            const low = s.toLowerCase().trim();
            return blacklist.some(b => low.includes(b)) || pageNames.some(p => low.startsWith(p));
        };

        // Tìm tất cả articles trong vùng hiển thị chi tiết bài viết (x > 300)
        const allArticles = Array.from(document.querySelectorAll('[role="article"]'))
            .filter(el => {
                const r = el.getBoundingClientRect();
                return r.left > 300 && r.height > 15;
            });

        // Lọc bỏ article chứa nhãn online indicator
        const commentArticles = allArticles.filter(art => {
            const aria = (art.getAttribute('aria-label') || '').toLowerCase();
            const text = (art.innerText || '').toLowerCase();
            return !aria.includes('chỉ báo trạng thái online') && !text.includes('chỉ báo trạng thái online');
        });

        const isReplyBtn = (el) => {
            const t = (el.innerText || '').trim().toLowerCase();
            const a = (el.getAttribute('aria-label') || '').trim().toLowerCase();
            const combo = (t + ' ' + a).trim();
            if (combo.includes('xem') || combo.includes('ẩn') || combo.includes('view') || combo.includes('hide')) {
                return false;
            }
            return t === 'trả lời' || t === 'reply' || t === 'phản hồi' ||
                   a === 'trả lời' || a === 'reply' || a === 'phản hồi' ||
                   a.startsWith('trả lời') || a.startsWith('reply') || a.startsWith('phản hồi') ||
                   a.includes('trả lời bình luận') || a.includes('reply to comment') || a.includes('phản hồi bình luận');
        };

        const isMsgBtn = (el) => {
            const t = (el.innerText || '').trim().toLowerCase();
            const a = (el.getAttribute('aria-label') || '').trim().toLowerCase();
            const combo = t + ' ' + a;
            return combo.includes('see chat') || combo.includes('gửi tin nhắn') ||
                   combo.includes('nhắn tin') || combo.includes('send message') ||
                   combo.includes('tin nhắn') || combo.includes('message') || combo.includes('chat');
        };

        const parsedComments = [];
        for (let i = 0; i < commentArticles.length; i++) {
            const art = commentArticles[i];
            const aria = (art.getAttribute('aria-label') || '').trim();
            const inner = (art.innerText || '').trim();
            const lowerAria = aria.toLowerCase();
            const lowerInner = inner.toLowerCase();

            // Kiểm tra xem article này là phản hồi của chính Fanpage
            const isPageReply = lowerAria.includes("dưới tên dần86farm") ||
                                lowerAria.includes("dưới tên dan86") ||
                                pageNames.some(p => lowerInner.startsWith(p) || lowerInner.includes(p + "\n") || lowerInner.includes("tác giả\n" + p));

            // Trích xuất tên tác giả
            let authorName = "";
            const mAria = aria.match(/Bình luận dưới tên\s+(.+?)(?:\s+vào\s+|$)/i) ||
                          aria.match(/Comment by\s+(.+?)(?:\s+ago|\s+at|\s+on|$)/i);
            if (mAria && mAria[1]) {
                authorName = mAria[1].trim();
            }

            const lines = inner.split('\n').map(s => s.trim()).filter(Boolean);

            if (!authorName || isSystemString(authorName)) {
                const authorBtn = art.querySelector('div[role="button"]:not([aria-label]), a[role="link"], span[dir="auto"]');
                if (authorBtn && authorBtn.innerText) {
                    const cand = authorBtn.innerText.trim();
                    if (!isSystemString(cand) && cand.length >= 2 && cand.length <= 50) {
                        authorName = cand;
                    }
                }
            }

            if (!authorName || isSystemString(authorName)) {
                for (const line of lines) {
                    if (!isSystemString(line) && line.length >= 2 && line.length <= 50 && !line.includes('tuần') && !line.includes('ngày') && !line.includes('phút') && !line.includes('giờ') && line !== '·') {
                        authorName = line;
                        break;
                    }
                }
            }

            // Trích xuất dấu thời gian độc lập để kiểm tra bình luận cũ (tránh lọc nhầm nội dung khách)
            let timeStr = "";
            const tAria = aria.match(/(?:vào|at|on)\s+(.+?)(?:$)/i);
            if (tAria && tAria[1]) {
                timeStr = tAria[1].trim();
            }
            if (!timeStr) {
                const timeLine = lines.find(l => /^\s*\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm|m|h|d|w|y|mins?|hours?|days?|weeks?|months?|years?)\s*(?:trước|ago)?\s*$/i.test(l.trim()) || /^(?:vừa xong|just now|hôm qua|yesterday)$/i.test(l.trim()));
                if (timeLine) {
                    timeStr = timeLine.trim();
                }
            }

            const checkTime = (timeStr || aria).toLowerCase();
            let isOldComment = false;

            // Kiểm tra các mốc thời gian cũ: tuần, tháng, năm
            if (/(\d+)\s*(tuần|tháng|năm|w|y|weeks?|months?|years?)\b/i.test(checkTime) ||
                checkTime.includes("năm trước") || checkTime.includes("tháng trước") || checkTime.includes("tuần trước") ||
                checkTime.includes("years ago") || checkTime.includes("months ago") || checkTime.includes("weeks ago")) {
                isOldComment = true;
            }

            // Kiểm tra nếu là ngày nhưng > 3 ngày
            const dayMatch = checkTime.match(/(\d+)\s*(ngày|days?)\b/i);
            if (dayMatch && parseInt(dayMatch[1], 10) > 3) {
                isOldComment = true;
            }

            // Trích xuất nội dung bình luận (cho phép bình luận 1 ký tự, icon, số, chữ ngắn)
            const contentLines = lines.filter(l => {
                const low = l.toLowerCase();
                const trimmed = l.trim();
                const isTimestampLine = /^\s*\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm|s|m|h|d|w|y|secs?|mins?|hours?|days?|weeks?|months?|years?)\s*(?:trước|ago)?\s*$/i.test(trimmed) || /^(?:vừa xong|just now|hôm qua|yesterday|·)$/i.test(trimmed);
                if (l === authorName || isTimestampLine) return false;
                if (/^\d+(\s+(?:phản hồi|bình luận|replies|reply))?$/i.test(trimmed)) return false;
                if (['trả lời', 'reply', 'phản hồi', 'ẩn', 'hide', 'see chat', 'nhắn tin', 'gửi tin nhắn', 'send message', 'thích', 'like', 'bày tỏ cảm xúc', 'theo dõi lại', 'theo dõi', 'tác giả'].includes(low)) return false;
                return true;
            });
            let commentText = contentLines.join(" ").trim();
            if (!commentText) {
                if (inner.includes('Sticker') || inner.includes('GIPHY') || inner.includes('sticker') || inner.includes('gif')) {
                    commentText = "[Sticker / GIPHY]";
                } else {
                    commentText = ".";
                }
            }

            // Cắt bỏ sạch tiền tố thời gian khỏi commentText
            commentText = commentText.replace(/^\s*\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm|s|m|h|d|w|y|secs?|mins?|hours?|days?|weeks?|months?|years?)\s*(?:trước|ago)?\s*/i, '').trim();
            commentText = commentText.replace(/^\s*(?:vừa xong|just now|hôm qua|yesterday)\s*/i, '').trim();
            if (!commentText) {
                commentText = ".";
            }

            // Kiểm tra nút Trả lời / Phản hồi & Nút Nhắn tin (Ưu tiên các phần tử bấm được)
            const candidateEls = Array.from(art.querySelectorAll('button, [role="button"], a[role="link"], a, [role="tab"]'));
            if (candidateEls.length === 0) {
                candidateEls.push(...Array.from(art.querySelectorAll('span, div')).filter(el => el.children.length === 0 && (el.innerText || '').trim().length <= 30));
            }
            const rBtn = candidateEls.find(isReplyBtn);
            const mBtn = candidateEls.find(isMsgBtn);
            const rect = art.getBoundingClientRect();
            parsedComments.push({
                domIndex: allArticles.indexOf(art),
                isPageReply: isPageReply,
                isOldComment: isOldComment,
                timeStr: timeStr,
                authorName: authorName || "bạn",
                commentText: commentText,
                hasReplyBtn: !!rBtn,
                msgBtnText: mBtn ? ((mBtn.innerText || '').trim() || (mBtn.getAttribute('aria-label') || '').trim()) : "",
                innerPreview: inner.slice(0, 100),
                articleEl: art,
                left: rect.left,
                top: rect.top
            });
        }

        // Đánh giá xem bình luận nào có phản hồi của Page lồng ngay bên dưới
        for (let j = 0; j < parsedComments.length; j++) {
            const item = parsedComments[j];
            if (item.isPageReply) {
                item.hasPageReply = true;
                continue;
            }

            let hasReplyBelow = false;
            // Chỉ coi article tiếp theo là phản hồi của item này nếu:
            // 1. Article tiếp theo là của Page (isPageReply == true)
            // VÀ 2. Article tiếp theo PHẢI THỤT LỀ (nested reply): nextItem.left > item.left + 15!
            // Nếu nextItem.left <= item.left + 10, đó là bình luận cấp 1 tiếp theo -> kết thúc nhánh
            for (let k = j + 1; k < parsedComments.length; k++) {
                const nextItem = parsedComments[k];
                if (nextItem.left <= item.left + 10) {
                    // Đã chạm đến bình luận cấp 1 tiếp theo -> kết thúc nhánh phản hồi
                    break;
                }
                if (nextItem.left > item.left + 15 && nextItem.isPageReply) {
                    hasReplyBelow = true;
                    break;
                }
            }
            item.hasPageReply = hasReplyBelow;
        }

        // Lấy danh sách tất cả các bình luận khách MỚI (!c.isOldComment) chưa có Page trả lời HOẶC chưa được gửi tin nhắn riêng
        const unrepliedList = parsedComments.filter(c => {
            if (c.isPageReply || c.isOldComment) return false;
            if (!c.hasPageReply) return true;
            const mText = (c.msgBtnText || '').toLowerCase();
            const hasMsgBtn = mText.includes('gửi tin nhắn') || mText.includes('nhắn tin') || mText.includes('send message') || mText.includes('see chat') || mText.includes('xem đoạn chat') || !!c.msgBtnText;
            return hasMsgBtn;
        });

        let target = null;
        let targetArticleNode = null;
        if (unrepliedList.length > 0) {
            target = unrepliedList[0];
            targetArticleNode = target.articleEl;
        }

        // Đánh dấu trực tiếp các data-attributes lên DOM cho comment đầu tiên
        document.querySelectorAll('[data-dan86-reply-target]').forEach(e => e.removeAttribute('data-dan86-reply-target'));
        document.querySelectorAll('[data-dan86-reply-btn]').forEach(e => e.removeAttribute('data-dan86-reply-btn'));
        document.querySelectorAll('[data-dan86-msg-btn]').forEach(e => e.removeAttribute('data-dan86-msg-btn'));

        if (targetArticleNode) {
            targetArticleNode.setAttribute('data-dan86-reply-target', 'true');
            const candidateEls = Array.from(targetArticleNode.querySelectorAll('button, [role="button"], a[role="link"], a, [role="tab"], span, div'));
            const rBtn = candidateEls.find(isReplyBtn);
            if (rBtn) {
                const clickNode = rBtn.closest('button, [role="button"], a') || rBtn;
                const clickCombo = ((clickNode.innerText || '') + ' ' + (clickNode.getAttribute('aria-label') || '')).toLowerCase();
                if (!clickCombo.includes('xem') && !clickCombo.includes('ẩn') && !clickCombo.includes('view') && !clickCombo.includes('hide')) {
                    clickNode.setAttribute('data-dan86-reply-btn', 'true');
                } else {
                    rBtn.setAttribute('data-dan86-reply-btn', 'true');
                }
            }
            const mBtn = candidateEls.find(isMsgBtn);
            if (mBtn) {
                const msgNode = mBtn.closest('button, [role="button"], a') || mBtn;
                msgNode.setAttribute('data-dan86-msg-btn', 'true');
            }
        }

        const urlParams = new URLSearchParams(window.location.search);
        const postId = urlParams.get("selected_item_id") || urlParams.get("comment_id") || "";

        const unrepliedSummaries = unrepliedList.map(c => ({
            dom_index: c.domIndex,
            author_name: c.authorName,
            comment_text: c.commentText,
            time_str: c.timeStr || "",
            is_old_comment: c.isOldComment,
            has_page_reply: !!c.hasPageReply,
            has_reply_btn: c.hasReplyBtn,
            has_msg_btn: !!c.msgBtnText,
            msg_btn_text: c.msgBtnText,
        }));

        if (target) {
            return {
                post_id: postId,
                author_name: target.authorName,
                comment_text: target.commentText,
                target_article_index: target.domIndex,
                has_page_reply: !!target.hasPageReply,
                has_msg_btn: !!target.msgBtnText,
                msg_btn_text: target.msgBtnText,
                unreplied_count: unrepliedList.length,
                unreplied_comments: unrepliedSummaries,
                total_comments: parsedComments.length
            };
        }

        return {
            post_id: postId,
            author_name: "bạn",
            comment_text: "",
            target_article_index: -1,
            has_page_reply: parsedComments.length > 0,
            has_msg_btn: false,
            msg_btn_text: "",
            unreplied_count: 0,
            unreplied_comments: [],
            total_comments: parsedComments.length
        };
    }
    """
    try:
        raw_res = await page.evaluate(js_code, PAGE_NAMES)
        raw_res["author_name"] = clean_customer_name(raw_res.get("author_name", ""))
        raw_res["comment_text"] = clean_comment_text(raw_res.get("comment_text", ""))
        for uc in raw_res.get("unreplied_comments", []):
            uc["author_name"] = clean_customer_name(uc.get("author_name", ""))
            uc["comment_text"] = clean_comment_text(uc.get("comment_text", ""))
        return raw_res
    except Exception as e:
        logger.debug("Không thể phân tích DOM bình luận: %s", e)
        return {
            "post_id": "",
            "author_name": "bạn",
            "comment_text": "",
            "target_article_index": -1,
            "has_page_reply": False,
            "has_msg_btn": False,
            "msg_btn_text": "",
            "unreplied_count": 0,
            "unreplied_comments": [],
            "total_comments": 0,
        }


async def tag_comment_target_in_dom(page: Page, dom_index: int) -> bool:
    """
    Đánh dấu thuộc tính data-dan86-* lên DOM cho article tại dom_index cụ thể.
    """
    js_tag = """
    (idx) => {
        const allArticles = Array.from(document.querySelectorAll('[role="article"]'))
            .filter(el => {
                const r = el.getBoundingClientRect();
                return r.left > 300 && r.height > 15;
            });

        document.querySelectorAll('[data-dan86-reply-target]').forEach(e => e.removeAttribute('data-dan86-reply-target'));
        document.querySelectorAll('[data-dan86-reply-btn]').forEach(e => e.removeAttribute('data-dan86-reply-btn'));
        document.querySelectorAll('[data-dan86-msg-btn]').forEach(e => e.removeAttribute('data-dan86-msg-btn'));

        if (idx < 0 || idx >= allArticles.length) return false;
        const target = allArticles[idx];
        try {
            target.scrollIntoView({ behavior: 'instant', block: 'center' });
        } catch (_) {}
        target.setAttribute('data-dan86-reply-target', 'true');

        const isReplyBtn = (el) => {
            const t = (el.innerText || '').trim().toLowerCase();
            const a = (el.getAttribute('aria-label') || '').trim().toLowerCase();
            const combo = (t + ' ' + a).trim();
            if (combo.includes('xem') || combo.includes('ẩn') || combo.includes('view') || combo.includes('hide')) {
                return false;
            }
            return t === 'trả lời' || t === 'reply' || t === 'phản hồi' ||
                   a === 'trả lời' || a === 'reply' || a === 'phản hồi' ||
                   a.startsWith('trả lời') || a.startsWith('reply') || a.startsWith('phản hồi') ||
                   a.includes('trả lời bình luận') || a.includes('reply to comment') || a.includes('phản hồi bình luận');
        };

        const isMsgBtn = (el) => {
            const t = (el.innerText || '').trim().toLowerCase();
            const a = (el.getAttribute('aria-label') || '').trim().toLowerCase();
            const combo = t + ' ' + a;
            return combo.includes('see chat') || combo.includes('gửi tin nhắn') ||
                   combo.includes('nhắn tin') || combo.includes('send message') ||
                   combo.includes('tin nhắn') || combo.includes('message') || combo.includes('chat');
        };

        const candidateEls = Array.from(target.querySelectorAll('button, [role="button"], a[role="link"], a, [role="tab"], span, div'));
        const rBtn = candidateEls.find(isReplyBtn);
        if (rBtn) {
            const clickNode = rBtn.closest('button, [role="button"], a') || rBtn;
            const clickCombo = ((clickNode.innerText || '') + ' ' + (clickNode.getAttribute('aria-label') || '')).toLowerCase();
            if (!clickCombo.includes('xem') && !clickCombo.includes('ẩn') && !clickCombo.includes('view') && !clickCombo.includes('hide')) {
                clickNode.setAttribute('data-dan86-reply-btn', 'true');
            } else {
                rBtn.setAttribute('data-dan86-reply-btn', 'true');
            }
        }

        const mBtn = candidateEls.find(isMsgBtn);
        if (mBtn) {
            const msgNode = mBtn.closest('button, [role="button"], a') || mBtn;
            msgNode.setAttribute('data-dan86-msg-btn', 'true');
        }

        return true;
    }
    """
    try:
        return bool(await page.evaluate(js_tag, dom_index))
    except Exception:
        return False


async def send_inbox_via_messenger_search(
    page: Page,
    author_name: str,
    private_reply_text: str,
    return_url: str = META_INBOX_COMMENTS_URL,
) -> bool:
    """
    Fallback gửi tin nhắn riêng cho khách khi nút dưới bình luận không bấm được:
    1. Chuyển sang Tab Messenger Inbox (META_INBOX_MESSENGER_URL).
    2. Tìm hội thoại có tên khách author_name ở cột trái (hoặc gõ vào ô tìm kiếm).
    3. Nhấp vào hội thoại và gửi private_reply_text.
    4. Quay lại URL ban đầu (return_url) để tiếp tục quét bình luận.
    """
    clean_name = clean_customer_name(author_name)
    if not clean_name or clean_name == "bạn":
        logger.info("Tên khách không xác định ('%s'), bỏ qua fallback Messenger.", author_name)
        return False

    try:
        logger.info("Chuyển đến Messenger để tìm kiếm hội thoại của [%s]...", clean_name)
        await page.goto(META_INBOX_MESSENGER_URL, wait_until="domcontentloaded", timeout=45000)
        await human_sleep(3.5, 5.0)

        # 1. Thử tìm kiếm trực tiếp trong danh sách hội thoại cột trái
        thread_items = page.locator('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="navigation"] [role="listitem"], [role="grid"] [role="row"], div[role="listitem"]')
        found_item = False
        item_count = min(await thread_items.count(), 15)

        for i in range(item_count):
            item = thread_items.nth(i)
            txt = (await item.inner_text() or "").lower()
            if clean_name.lower() in txt:
                logger.info("Tìm thấy hội thoại của [%s] trong danh sách gần nhất!", clean_name)
                # Click tại x=150, y=40 để mở chat an toàn, không bấm vào menu phụ
                await safe_click(item, timeout=3000, position={"x": 150, "y": 40})
                found_item = True
                await human_sleep(2.0, 3.5)
                break

        # 2. Nếu không thấy trong danh sách gần nhất, dùng ô tìm kiếm
        if not found_item:
            search_box = page.locator('input[placeholder*="Tìm kiếm"], input[placeholder*="Search"]').first
            if await search_box.count() > 0 and await search_box.is_visible():
                logger.info("Dùng ô tìm kiếm Messenger gõ tên: %s", clean_name)
                await safe_click(search_box, timeout=2500)
                await search_box.fill(clean_name)
                await human_sleep(2.5, 4.0)

                result_items = page.locator('div[role="presentation"].x1ypdohk, [role="navigation"] [role="listitem"], [role="listbox"] [role="option"]')
                if await result_items.count() > 0:
                    first_res = result_items.first
                    if await first_res.is_visible():
                        await safe_click(first_res, timeout=3000, position={"x": 150, "y": 40})
                        found_item = True
                        await human_sleep(2.0, 3.5)

        # 3. Gửi tin nhắn nếu đã mở được hội thoại (duyệt qua TẤT CẢ các textbox)
        if found_item:
            composers = page.locator(
                'div[role="textbox"][contenteditable="true"], '
                'textarea[placeholder*="tin nhắn"], '
                'textarea[placeholder*="message"]'
            )
            c_cnt = await composers.count()
            sent_msg = False
            for ci in range(c_cnt):
                c_target = composers.nth(ci)
                if await c_target.is_visible():
                    aria = (await c_target.get_attribute("aria-label") or "").lower()
                    ph = (await c_target.get_attribute("placeholder") or "").lower()
                    if not any(k in aria or k in ph for k in ["bình luận", "comment", "phản hồi"]):
                        try:
                            await type_human_like(page, c_target, private_reply_text)
                            await page.keyboard.press("Enter")
                            await human_sleep(2.0, 3.5)
                            sent_msg = True
                            logger.info("Đã gửi tin nhắn riêng cho [%s] qua Fallback Messenger (ô %d) thành công!", clean_name, ci)
                            break
                        except Exception as e_send:
                            logger.debug("Lỗi nhập composer %d trong Messenger: %s", ci, e_send)

            if sent_msg:
                # Quay lại trang ban đầu
                await page.goto(return_url, wait_until="domcontentloaded", timeout=45000)
                await human_sleep(3.0, 5.0)
                return True

        logger.warning("Không tìm thấy hội thoại Messenger cho khách [%s].", clean_name)
        # Quay lại trang ban đầu
        await page.goto(return_url, wait_until="domcontentloaded", timeout=45000)
        await human_sleep(3.0, 5.0)
        return False

    except Exception as e:
        logger.warning("Lỗi trong fallback Messenger cho [%s]: %s", clean_name, e)
        try:
            await page.goto(return_url, wait_until="domcontentloaded", timeout=45000)
            await human_sleep(2.0, 3.5)
        except Exception:
            pass
        return False


async def dismiss_blocking_modals(page: Page) -> None:
    """Tự động đóng các popup modal / upsell / banner quảng cáo che khuất giao diện (chỉ đóng bên trong dialog đang hiển thị, tuyệt đối không bấm nút trên trang chính)."""
    try:
        dialogs = page.locator('div[role="dialog"]')
        cnt = await dialogs.count()
        for i in range(cnt):
            dlg = dialogs.nth(i)
            if await dlg.is_visible():
                close_btn = dlg.locator('[aria-label="Đóng"], [aria-label="Close"]').first
                if await close_btn.count() > 0 and await close_btn.is_visible():
                    await close_btn.click(timeout=1000)
                    await asyncio.sleep(0.3)
    except Exception:
        pass


async def send_private_inbox_to_commenter(
    page: Page,
    post_url: str = META_INBOX_COMMENTS_URL,
    author_name: str = "",
    private_reply_text: str = "",
    comment_text: str = "",
    dom_index: int = -1,
    dry_run: bool = False,
) -> bool:
    """
    Bấm nút 'Gửi tin nhắn' / 'Nhắn tin' / 'See Chat' dưới bình luận của khách
    để gửi tin nhắn riêng vào Inbox cho người đó.
    Xử lý đầy đủ 3 trường hợp thực tế:
    1. Hiện popup modal (div[role="dialog"]): nhập text, bấm Gửi.
    2. Nút 'See Chat' (đã có thread Messenger): mở khung chat, nhập text vào composer,
       gửi, sau đó quay lại URL bài viết (post_url).
    3. Fallback (không có nút hoặc không gửi được): chuyển sang tab Messenger,
       tìm hội thoại theo author_name, gửi tin nhắn, sau đó quay lại URL bài viết (post_url).
    """
    if dry_run:
        logger.info("[DRY-RUN] Sẽ gửi tin nhắn riêng cho [%s]: %s", author_name or "khách", private_reply_text[:80])
        return True

    clicked_btn = False
    btn_text_lower = ""

    # 1. Thử click nút tin nhắn đã được gán data-dan86-msg-btn
    marked_msg_btn = page.locator('[data-dan86-msg-btn="true"]').first
    if await marked_msg_btn.count() > 0 and await marked_msg_btn.is_visible():
        try:
            btn_text_lower = (await marked_msg_btn.inner_text() or "").lower()
            await safe_click(marked_msg_btn, timeout=2500)
            clicked_btn = True
            await human_sleep(2.0, 3.5)
        except Exception as e_mbtn:
            logger.debug("Lỗi bấm nút tin nhắn đánh dấu: %s", e_mbtn)

    # 2. Nếu chưa click được (hoặc DOM re-render sau khi post comment), dùng JS tìm nút tin nhắn của chính comment này
    if not clicked_btn:
        js_click_msg = """
        (args) => {
            const { targetIdx, targetAuthor } = args;
            const articles = Array.from(document.querySelectorAll('[role="article"]'))
                .filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.left > 300 && r.height > 15;
                });

            let target = null;
            if (targetIdx >= 0 && targetIdx < articles.length) {
                const candArt = articles[targetIdx];
                if (!targetAuthor || targetAuthor === 'bạn' || (candArt.innerText || '').toLowerCase().includes(targetAuthor.toLowerCase())) {
                    target = candArt;
                }
            }
            if (!target && targetAuthor && targetAuthor !== 'bạn') {
                const matching = articles.filter(a => (a.innerText || '').toLowerCase().includes(targetAuthor.toLowerCase()));
                if (matching.length > 0) {
                    target = matching[matching.length - 1];
                }
            }
            if (!target && articles.length > 0) {
                target = articles[0];
            }
            if (!target) return { clicked: false, text: '' };

            const isMsgBtn = (el) => {
                const t = (el.innerText || '').trim().toLowerCase();
                const a = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                const combo = t + ' ' + a;
                return combo.includes('see chat') || combo.includes('gửi tin nhắn') ||
                       combo.includes('nhắn tin') || combo.includes('send message') ||
                       combo.includes('tin nhắn') || combo.includes('message') || combo.includes('chat');
            };

            const candidateEls = Array.from(target.querySelectorAll('button, [role="button"], a[role="link"], a, [role="tab"]'));
            if (candidateEls.length === 0) {
                candidateEls.push(...Array.from(target.querySelectorAll('span, div')).filter(el => el.children.length === 0 && (el.innerText || '').trim().length <= 30));
            }
            const btn = candidateEls.find(isMsgBtn);
            if (btn) {
                const clickNode = btn.closest('button, [role="button"], a') || btn;
                clickNode.scrollIntoView();
                clickNode.click();
                const foundText = (btn.innerText || btn.getAttribute('aria-label') || '').trim();
                return { clicked: true, text: foundText };
            }
            return { clicked: false, text: '' };
        }
        """
        try:
            res_click = await page.evaluate(js_click_msg, {"targetIdx": dom_index, "targetAuthor": author_name})
            if res_click.get("clicked"):
                clicked_btn = True
                btn_text_lower = res_click.get("text", "").lower()
                await human_sleep(2.0, 3.5)
        except Exception as e_js_click:
            logger.debug("Lỗi JS click nút tin nhắn: %s", e_js_click)

    # TRƯỜNG HỢP 1: Hiện popup dialog (div[role="dialog"])
    dialogs = page.locator('div[role="dialog"]')
    if await dialogs.count() > 0:
        dialog = dialogs.last
        if await dialog.is_visible():
            dialog_box = dialog.locator('div[role="textbox"][contenteditable="true"], textarea').first
            if await dialog_box.count() > 0 and await dialog_box.is_visible():
                box_aria = (await dialog_box.get_attribute("aria-label") or "").lower()
                box_holder = (await dialog_box.get_attribute("placeholder") or "").lower()
                # Kiểm tra nghiêm ngặt: Tuyệt đối không được là ô bình luận hoặc trả lời bài viết
                if not any(k in box_aria or k in box_holder for k in ["bình luận", "comment", "phản hồi", "trả lời", "reply"]):
                    await type_human_like(page, dialog_box, private_reply_text)
                    send_btn = dialog.locator(
                        '[aria-label*="Gửi"], [aria-label*="Send"], '
                        'div[role="button"]:has-text("Gửi"), div[role="button"]:has-text("Send"), '
                        'button:has-text("Gửi"), button:has-text("Send")'
                    ).last
                    if await send_btn.count() > 0 and await send_btn.is_visible():
                        await safe_click(send_btn, timeout=2500)
                    else:
                        await page.keyboard.press("Enter")
                    await human_sleep(2.0, 3.5)
                    # Đóng dialog nếu còn hiển thị
                    close_btn = dialog.locator('[aria-label*="Đóng"], [aria-label*="Close"], button:has-text("Đóng"), button:has-text("Close")').first
                    if await close_btn.count() > 0 and await close_btn.is_visible():
                        try:
                            await close_btn.click(timeout=1500)
                        except Exception:
                            pass
                    await dismiss_blocking_modals(page)
                    logger.info("Đã gửi tin nhắn riêng cho [%s] qua Popup Modal thành công!", author_name)
                    return True
                else:
                    logger.warning("Dialog hiện tại là ô bình luận bài viết, bỏ qua để không gửi nhầm tin nhắn riêng công khai!")

    # TRƯỜNG HỢP 2: Bấm nút 'See Chat' (chỉ khi trang ĐÃ CHUYỂN HẲN sang URL Messenger, KHÔNG CÒN ở trang bình luận)
    current_url = page.url.lower()
    is_at_comments_page = "inbox/facebook" in current_url or (post_url and current_url == post_url.lower())

    is_chat_view = False
    if not is_at_comments_page:
        is_chat_view = "messenger" in current_url or ("inbox" in current_url and "facebook" not in current_url)
        chat_panel = page.locator('[data-pagelet="ChatTab"], [role="main"]:has(div[role="textbox"][aria-label*="tin nhắn"])').first
        if not is_chat_view and await chat_panel.count() > 0 and await chat_panel.is_visible():
            is_chat_view = True

    if is_chat_view:
        composer_selectors = [
            'div[role="textbox"][contenteditable="true"]:not([aria-label*="bình luận"]):not([aria-label*="phản hồi"]):not([aria-label*="trả lời"]):not([placeholder*="bình luận"])',
            'textarea[placeholder*="tin nhắn"]',
            'textarea[placeholder*="message"]',
        ]
        sent_in_chat = False
        for c_sel in composer_selectors:
            composers = page.locator(c_sel)
            cnt = await composers.count()
            for ci in range(cnt):
                target_composer = composers.nth(ci)
                if await target_composer.is_visible():
                    aria = (await target_composer.get_attribute("aria-label") or "").lower()
                    placeholder = (await target_composer.get_attribute("placeholder") or "").lower()
                    if not any(k in aria or k in placeholder for k in ["bình luận", "comment", "phản hồi", "trả lời", "reply"]):
                        try:
                            await type_human_like(page, target_composer, private_reply_text)
                            await page.keyboard.press("Enter")
                            await human_sleep(2.0, 3.5)
                            logger.info("Đã gửi tin nhắn riêng cho [%s] qua giao diện See Chat (ô %d) thành công!", author_name, ci)
                            sent_in_chat = True
                            break
                        except Exception as e_send_chat:
                            logger.debug("Lỗi gửi tin qua See Chat composer %d: %s", ci, e_send_chat)
            if sent_in_chat:
                break

        if sent_in_chat:
            # Quay lại trang bài viết ban đầu
            if page.url != post_url:
                logger.info("Đang quay lại URL bài viết để tiếp tục quét: %s", post_url)
                await page.goto(post_url, wait_until="domcontentloaded", timeout=45000)
                await human_sleep(3.0, 5.0)
            return True

    # TRƯỜNG HỢP 3: Fallback chuyển sang tab Messenger tìm kiếm author_name
    if author_name and author_name != "bạn":
        logger.info("Kích hoạt fallback: Chuyển sang Messenger để tìm và nhắn riêng cho [%s]...", author_name)
        sent_fallback = await send_inbox_via_messenger_search(
            page=page,
            author_name=author_name,
            private_reply_text=private_reply_text,
            return_url=post_url,
        )
        if sent_fallback:
            return True

    logger.warning("Không thể gửi tin nhắn riêng cho khách [%s] qua cả 3 phương thức.", author_name)
    return False


async def locate_nested_reply_box(
    page: Page,
    target_art: Optional[Locator],
    timeout_seconds: float = 2.5,
) -> Optional[Locator]:
    """
    Định vị ô nhập phản hồi lồng nhau cấp 2 độc quyền cho target_art.
    BẮT BUỘC ô nhập này phải có quan hệ hình học và DOM trực tiếp với target_art:
    - Ưu tiên 1: target_art.locator('xpath=following::div[@role="textbox"][1]') hoặc target_art.locator('div[role="textbox"]')
    - Ưu tiên 2: Element đang :focus (document.activeElement) NHƯNG PHẢI nằm trong phạm vi dọc gần target_art:
      (bounding box Y: box_y >= target_y - 10 và box_y <= target_y + target_h + 250)
    CẤM TUYỆT ĐỐI việc dùng selector toàn cục page.locator('div:has-text("Trả lời với vai trò") div[role="textbox"]')
    bắt nhầm ô bình luận bài viết ở đáy trang.
    """
    if target_art is None:
        logger.warning("target_art không tồn tại (None) để định vị ô reply lồng nhau.")
        return None

    try:
        if await target_art.count() == 0:
            logger.warning("target_art không có phần tử DOM nào tương ứng.")
            return None
    except Exception as e:
        logger.warning("Lỗi kiểm tra target_art: %s", e)
        return None

    try:
        await target_art.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass

    art_box = await target_art.bounding_box()
    if not art_box:
        logger.warning("Không thể lấy bounding box của target_art.")
        return None

    async def is_valid_nested_candidate(cand: Locator) -> bool:
        try:
            if await cand.count() == 0 or not await cand.is_visible():
                return False
            cand_box = await cand.bounding_box()
            if not cand_box:
                return False

            # Bounding box của comment article hiện tại
            cur_art_box = await target_art.bounding_box()
            if not cur_art_box:
                return False

            t_y = cur_art_box["y"]
            t_h = cur_art_box["height"]
            t_x = cur_art_box["x"]

            box_y = cand_box["y"]
            box_h = cand_box["height"]
            box_x = cand_box["x"]

            # 1. Quan hệ hình học dọc: BẮT BUỘC nằm sát bên dưới target_art
            # box_y >= target_y - 10 và box_y <= target_y + target_h + 250
            if not (t_y - 10 <= box_y <= t_y + t_h + 250):
                return False
            if box_h < 12:
                return False

            # 2. Quan hệ hình học ngang: Cùng cột với comment article (cho phép thụt lề phải)
            if box_x < t_x - 50 or abs(box_x - t_x) > 300:
                return False

            # 3. Kiểm tra tính năng gõ chữ (contentEditable hoặc input/textarea/role=textbox)
            is_edit = await cand.evaluate(
                "el => el.isContentEditable || el.getAttribute('role') === 'textbox' || el.tagName === 'TEXTAREA' || el.tagName === 'INPUT'"
            )
            if not is_edit:
                return False

            # 4. Fail-safe Guard: Loại trừ ô bình luận cấp 1 của bài viết ở đáy trang
            aria = (await cand.get_attribute("aria-label") or "").lower()
            placeholder = (await cand.get_attribute("placeholder") or "").lower()
            combo = f"{aria} {placeholder}"
            if ("bình luận công khai" in combo or "bình luận dưới tên" in combo or "viết bình luận" in combo) and not any(
                k in combo for k in ["trả lời", "câu trả lời", "phản hồi", "reply"]
            ):
                logger.debug("Bỏ qua ô nhập vì là ô bình luận bài viết cấp 1: %s", combo)
                return False

            return True
        except Exception:
            return False

    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        # Ưu tiên 1A: Ô textbox nằm ngay sau target_art (following XPath)
        following_box = target_art.locator('xpath=following::div[@role="textbox"][1]').first
        if await is_valid_nested_candidate(following_box):
            logger.info("Tìm thấy ô nested reply lồng nhau (Ưu tiên 1: following role=textbox).")
            return following_box

        following_edit = target_art.locator('xpath=following::div[@contenteditable="true"][1]').first
        if await is_valid_nested_candidate(following_edit):
            logger.info("Tìm thấy ô nested reply lồng nhau (Ưu tiên 1: following contenteditable).")
            return following_edit

        # Ưu tiên 1B: Ô textbox nằm ngay bên trong target_art
        inside_box = target_art.locator('div[role="textbox"], div[contenteditable="true"]').first
        if await is_valid_nested_candidate(inside_box):
            logger.info("Tìm thấy ô nested reply lồng nhau (Ưu tiên 1: inside target_art).")
            return inside_box

        # Ưu tiên 2: Element đang :focus (document.activeElement) có quan hệ hình học sát target_art
        focused_el = page.locator('div[role="textbox"]:focus, div[contenteditable="true"]:focus, :focus').first
        if await is_valid_nested_candidate(focused_el):
            logger.info("Tìm thấy ô nested reply lồng nhau (Ưu tiên 2: :focus activeElement).")
            return focused_el

        # Ưu tiên 3: Quét các textbox đang hiển thị nằm trong phạm vi hình học gần target_art
        near_boxes = page.locator('div[role="textbox"], div[contenteditable="true"]')
        near_count = min(await near_boxes.count(), 10)
        for nb_idx in range(near_count):
            cand_nb = near_boxes.nth(nb_idx)
            if await is_valid_nested_candidate(cand_nb):
                logger.info("Tìm thấy ô nested reply lồng nhau (Ưu tiên 3: near geometric match #%d).", nb_idx)
                return cand_nb

        await asyncio.sleep(0.3)

    return None


async def process_facebook_comments_tab(
    page: Page,
    memory: BotMemoryStore,
    dry_run: bool = False,
) -> int:
    """
    Quét tab Bình luận Facebook trên Meta Business Suite:
    1. Lọc sạch tên khách hàng (chống lấy nhầm 'Chỉ báo trạng thái online').
    2. Chọn bài viết an toàn ở cột trái tại position x=150, y=40 (không bấm x=490, không đụng xóa/ẩn bài).
    3. Tự động chuyển sắp xếp sang 'Mới nhất' (Newest) / 'Tất cả bình luận'.
    4. Tự động mở rộng các phản hồi bị ẩn dưới nút 'Xem ... phản hồi'.
    5. Chỉ xử lý bình luận MỚI (vừa xong, phút, giờ, hôm qua, 1-3 ngày), BỎ QUA 100% bình luận cũ (tuần, tháng, năm).
    6. Thả Like bình luận.
    7. Random câu trả lời công khai lồng dưới bình luận (Nested Reply).
    8. Tự động gửi tin nhắn riêng (Inbox) cho người bình luận đó:
       - Hỗ trợ Popup Modal
       - Hỗ trợ giao diện See Chat (duyệt mọi textbox)
       - Hỗ trợ Fallback tìm kiếm trong Messenger
    """
    replied_count = 0
    logger.info("Đang kiểm tra Tab Bình luận Facebook: %s", META_INBOX_COMMENTS_URL)
    await page.goto(META_INBOX_COMMENTS_URL, wait_until="domcontentloaded", timeout=45000)
    await human_sleep(4.0, 6.0)

    if not await verify_logged_in(page):
        logger.warning("Phiên đăng nhập Facebook chưa sẵn sàng hoặc đã hết hạn!")
        return 0

    # Tìm danh sách các bài viết / bài đăng có bình luận ở cột bên trái
    thread_selectors = [
        'div._a6ag._a6ah',
        '[role="grid"] [role="row"]',
        '[role="navigation"] [role="listitem"]',
        '[data-pagelet*="ThreadList"] [role="button"]',
        'div[role="listitem"]',
    ]

    items_locator: Optional[Locator] = None
    for sel in thread_selectors:
        loc = page.locator(sel)
        if await loc.count() > 0:
            items_locator = loc
            break

    if items_locator is None:
        logger.info("Chưa tìm thấy danh sách bình luận mới nào trong hộp thư.")
        return 0

    total_items = min(await items_locator.count(), MAX_THREADS_PER_CYCLE)
    logger.info("Tìm thấy %d mục bài viết có bình luận cần kiểm tra.", total_items)

    for i in range(total_items):
        try:
            await dismiss_blocking_modals(page)
            item = items_locator.nth(i)
            if not await item.is_visible():
                continue

            preview_text = (await item.inner_text() or "").strip()
            # Bấm vào dòng bài viết tại position x=150, y=40 để mở chi tiết bình luận, tuyệt đối không bấm x=490 (nút xóa/menu)
            try:
                await safe_click(item, timeout=3000, position={"x": 150, "y": 40})
            except Exception:
                await dismiss_blocking_modals(page)
                await safe_click(item, timeout=3000, position={"x": 150, "y": 40})
            await human_sleep(2.0, 3.5)
            current_post_url = page.url

            # Đảm bảo bài viết hiển thị bình luận mới nhất
            await ensure_newest_comments_filter(page)

            # Lặp xử lý HẾT tất cả bình luận chưa trả lời trong bài viết đang mở
            max_comments_per_post = 10
            post_comment_cycle = 0

            while post_comment_cycle < max_comments_per_post:
                post_comment_cycle += 1

                # Tự động mở rộng các phản hồi bị ẩn để kiểm tra chính xác 100%
                await expand_all_comment_replies(page)

                info = await inspect_comment_panel(page)
                post_id = info.get("post_id") or ""
                unreplied_candidates = info.get("unreplied_comments", [])

                # Nếu bài viết này không còn bình luận nào chưa trả lời -> Chuyển sang bài viết tiếp theo
                if not unreplied_candidates:
                    logger.debug("Bài viết này không còn bình luận nào cần trả lời.")
                    break

                # Tìm candidate đầu tiên cần trả lời hoặc cần gửi tin nhắn riêng theo bộ nhớ (memory)
                target_candidate = None
                target_key = None
                needs_inbox_only = False
                for cand in unreplied_candidates:
                    cand_author = cand.get("author_name") or "bạn"
                    cand_text = cand.get("comment_text") or preview_text
                    cand_idx = int(cand.get("dom_index", 0))
                    cand_has_reply = bool(cand.get("has_page_reply", False))

                    if is_page_author_name(cand_author):
                        continue

                    # BỎ QUA 100% nếu bình luận cũ (tuần, tháng, năm hoặc > 3 ngày)
                    if cand.get("is_old_comment") or is_old_comment_timestamp(cand.get("time_str", "")):
                        logger.info("Bình luận cũ từ [%s] (Thời gian: '%s'). BỎ QUA 100%!", cand_author, cand.get("time_str", "") or cand.get("innerPreview", "")[:30])
                        continue

                    # CHẾ ĐỘ THỬ NGHIỆM AN TOÀN TRONG PHIÊN SỬA LỖI:
                    # Người dùng chỉ đạo: "đừng gửi tin cmt cho bất cứ ai ngoài đức trí trong phiên sửa lỗi này"
                    if TEST_ONLY_AUTHOR_WHITELIST:
                        c_norm = normalize_text(cand_author)
                        if not any(w in c_norm for w in TEST_ONLY_AUTHOR_WHITELIST):
                            logger.info("Chế độ thử nghiệm an toàn: Bỏ qua khách [%s] (Chỉ tương tác với Đức Trí trong phiên sửa lỗi này).", cand_author)
                            continue

                    # Bổ sung cơ chế Cooldown chống Spam lặp cùng bình luận trên cùng bài viết
                    if memory.is_customer_in_cooldown(
                        cand_author,
                        cooldown_seconds=CUSTOMER_ANTI_SPAM_COOLDOWN_SECONDS,
                        post_id=post_id,
                        comment_text=cand_text,
                    ):
                        logger.info(
                            "Khách hàng [%s] vừa được phản hồi bình luận này trên bài [%s] (Cooldown %.0fs). Bỏ qua lặp!",
                            cand_author,
                            post_id,
                            CUSTOMER_ANTI_SPAM_COOLDOWN_SECONDS,
                        )
                        continue

                    should_rep, comment_key = memory.should_reply_comment(
                        author_name=cand_author,
                        comment_text=cand_text,
                        has_page_reply_in_dom=cand_has_reply,
                        post_id=post_id,
                        dom_index=cand_idx,
                    )

                    # BẮT BUỘC kiểm tra if should_rep: trước khi gán target_candidate = cand
                    if should_rep:
                        target_candidate = cand
                        target_key = comment_key
                        needs_inbox_only = False
                        break

                    # Nếu trong memory ĐÃ TỒN TẠI bản ghi (đã rep công khai rồi) nhưng chưa gửi inbox thành công:
                    if comment_key:
                        existing_rec = memory.get_comment_record(
                            comment_key=comment_key,
                            author_name=cand_author,
                            comment_text=cand_text,
                            post_id=post_id,
                        )
                        if existing_rec and not existing_rec.get("private_inbox_sent"):
                            target_candidate = cand
                            target_key = comment_key
                            needs_inbox_only = True
                            break

                # Nếu tất cả các candidate đều đã được xử lý trong memory hoặc không hợp lệ -> Dừng vòng lặp bài này
                if target_candidate is None:
                    logger.debug("Tất cả bình luận chưa rep trên bài viết này đã được xử lý trong memory hoặc không hợp lệ.")
                    break

                cand_author = clean_customer_name(target_candidate.get("author_name") or "bạn")
                cand_text = clean_comment_text(target_candidate.get("comment_text") or preview_text)
                cand_idx = int(target_candidate.get("dom_index", 0))

                public_reply, private_inbox_reply = memory.prepare_comment_and_inbox_replies(cand_author)
                logger.info(
                    "Phát hiện bình luận mới từ [%s] (Post ID: %s, DOM Index: %d, Chỉ gửi Inbox: %s): %s",
                    cand_author,
                    post_id,
                    cand_idx,
                    needs_inbox_only,
                    cand_text[:80],
                )

                if dry_run:
                    if not needs_inbox_only:
                        logger.info("[DRY-RUN] Sẽ rep cmt công khai lồng bên dưới: %s", public_reply)
                    logger.info("[DRY-RUN] Sẽ tự động inbox riêng: %s", private_inbox_reply[:90])
                    replied_count += 1
                    break

                # Đánh dấu article mục tiêu trên DOM
                await tag_comment_target_in_dom(page, cand_idx)

                # Xác định article bình luận mục tiêu
                target_art: Optional[Locator] = None
                marked_target = page.locator('[data-dan86-reply-target="true"]').first
                if await marked_target.count() > 0 and await marked_target.is_visible():
                    target_art = marked_target
                elif cand_idx >= 0:
                    all_arts = page.locator('[role="article"]')
                    if await all_arts.count() > cand_idx:
                        target_art = all_arts.nth(cand_idx)

                if needs_inbox_only:
                    # Bình luận đã có câu trả lời công khai bên dưới -> Chỉ gửi trực tiếp 1 tin nhắn riêng (Inbox)
                    inbox_sent = await send_private_inbox_to_commenter(
                        page=page,
                        post_url=current_post_url,
                        author_name=cand_author,
                        private_reply_text=private_inbox_reply,
                        comment_text=cand_text,
                        dom_index=cand_idx,
                        dry_run=dry_run,
                    )
                    memory.mark_comment_replied(
                        comment_key=target_key,
                        author_name=cand_author,
                        comment_text=cand_text,
                        public_reply="(Đã phản hồi bình luận công khai)",
                        private_inbox_sent=inbox_sent,
                        private_reply_text=private_inbox_reply,
                        post_id=post_id,
                        dom_index=cand_idx,
                    )
                    replied_count += 1
                    if page.url != current_post_url:
                        try:
                            await page.goto(current_post_url, wait_until="domcontentloaded", timeout=45000)
                            await human_sleep(2.0, 3.5)
                        except Exception:
                            pass
                    await human_sleep(ACTION_COOLDOWN_SECONDS[0], ACTION_COOLDOWN_SECONDS[1])
                    continue

                # Bước 1: Thả Like bình luận của khách
                if target_art is not None:
                    like_btn = target_art.locator('div[role="button"]:has-text("Thích"), div[role="button"]:has-text("Like")').first
                    if await like_btn.count() > 0 and await like_btn.is_visible():
                        try:
                            await safe_click(like_btn, timeout=2000)
                            await human_sleep(0.8, 1.5)
                        except Exception:
                            pass

                # Bước 2: Bấm chính xác nút "Trả lời" / "Phản hồi" (Reply) của bình luận khách
                reply_clicked = False
                marked_reply_btn = page.locator('[data-dan86-reply-btn="true"]').first
                if await marked_reply_btn.count() > 0 and await marked_reply_btn.is_visible():
                    try:
                        reply_clicked = await safe_click(marked_reply_btn, timeout=2500)
                    except Exception as e_reply:
                        logger.debug("Lỗi bấm nút Trả lời đánh dấu: %s", e_reply)

                if not reply_clicked and target_art is not None:
                    # Tìm chính xác nút 'Trả lời' / 'Reply' / 'Phản hồi' nằm BÊN TRONG comment article của khách
                    cand_buttons = target_art.locator('div[role="button"], button, a, span')
                    b_count = min(await cand_buttons.count(), 20)
                    for b_idx in range(b_count):
                        b_el = cand_buttons.nth(b_idx)
                        if not await b_el.is_visible():
                            continue
                        b_text = (await b_el.inner_text() or "").strip().lower()
                        b_aria = (await b_el.get_attribute("aria-label") or "").strip().lower()
                        b_combo = f"{b_text} {b_aria}"
                        if any(bad in b_combo for bad in ["xem", "ẩn", "view", "hide"]):
                            continue
                        if (
                            b_text in ["trả lời", "reply", "phản hồi"]
                            or b_aria in ["trả lời", "reply", "phản hồi"]
                            or b_aria.startswith("trả lời")
                            or "trả lời bình luận" in b_aria
                            or "reply to comment" in b_aria
                        ):
                            try:
                                reply_clicked = await safe_click(b_el, timeout=2500)
                                if reply_clicked:
                                    logger.info("Đã bấm nút Trả lời trong comment article.")
                                    break
                            except Exception as e_b:
                                logger.debug("Lỗi bấm nút Trả lời dự phòng: %s", e_b)

                # Chờ 1.0 - 2.0 giây để DOM chèn ô nhập phản hồi lồng nhau
                if reply_clicked:
                    await human_sleep(1.2, 2.0)
                else:
                    await human_sleep(0.8, 1.2)

                # Định vị ô nhập phản hồi lồng nhau cấp 2 độc quyền cho target_art
                nested_box = await locate_nested_reply_box(page, target_art, timeout_seconds=2.5)

                # Cơ chế Bảo vệ Chống Đăng Nhầm Ra Ngoài (Fail-safe Guard):
                # Nếu KHÔNG tìm thấy ô reply lồng nhau hợp lệ nằm sát bên dưới target_art, TUYỆT ĐỐI KHÔNG GÕ VÀO Ô BÌNH LUẬN BÀI VIẾT!
                if nested_box is None:
                    logger.warning(
                        "Không tìm thấy ô nested reply lồng nhau hợp lệ gần bình luận của [%s], hủy cmt để chống đăng nhầm ra ngoài bài viết!",
                        cand_author,
                    )
                    # Hủy bỏ bước rep công khai, chỉ gửi tin nhắn riêng Messenger
                    inbox_sent = await send_private_inbox_to_commenter(
                        page=page,
                        post_url=current_post_url,
                        author_name=cand_author,
                        private_reply_text=private_inbox_reply,
                        comment_text=cand_text,
                        dom_index=cand_idx,
                        dry_run=dry_run,
                    )

                    memory.mark_comment_replied(
                        comment_key=target_key,
                        author_name=cand_author,
                        comment_text=cand_text,
                        public_reply="(Bỏ qua cmt công khai - Không tìm thấy ô lồng nhau)",
                        private_inbox_sent=inbox_sent,
                        private_reply_text=private_inbox_reply,
                        post_id=post_id,
                        dom_index=cand_idx,
                    )
                    replied_count += 1
                    if page.url != current_post_url:
                        try:
                            await page.goto(current_post_url, wait_until="domcontentloaded", timeout=45000)
                            await human_sleep(2.0, 3.5)
                        except Exception:
                            pass
                    await human_sleep(ACTION_COOLDOWN_SECONDS[0], ACTION_COOLDOWN_SECONDS[1])
                    continue

                # Nếu tìm thấy ô nested reply lồng nhau hợp lệ:
                if TEST_ONLY_AUTHOR_WHITELIST:
                    c_norm = normalize_text(cand_author)
                    if not any(w in c_norm for w in TEST_ONLY_AUTHOR_WHITELIST):
                        logger.info("Chế độ thử nghiệm an toàn: Bỏ qua gửi cmt công khai cho [%s] (Chỉ tương tác với Đức Trí).", cand_author)
                        continue

                await type_human_like(page, nested_box, public_reply)
                await page.keyboard.press("Enter")
                await human_sleep(2.5, 4.0)
                logger.info("Đã gửi phản hồi bình luận công khai cho [%s] (Nested Reply: True).", cand_author)

                # Bước 3: Tự động gửi tin nhắn riêng (Private Reply) cho người vừa bình luận
                inbox_sent = await send_private_inbox_to_commenter(
                    page=page,
                    post_url=current_post_url,
                    author_name=cand_author,
                    private_reply_text=private_inbox_reply,
                    comment_text=cand_text,
                    dom_index=cand_idx,
                    dry_run=dry_run,
                )

                # Lưu vào bộ nhớ với khóa định danh kết hợp post_id + dom_index
                memory.mark_comment_replied(
                    comment_key=target_key,
                    author_name=cand_author,
                    comment_text=cand_text,
                    public_reply=public_reply,
                    private_inbox_sent=inbox_sent,
                    private_reply_text=private_inbox_reply,
                    post_id=post_id,
                    dom_index=cand_idx,
                )
                replied_count += 1

                # Đảm bảo trở lại đúng bài viết đang mở nếu URL bị đổi
                if page.url != current_post_url:
                    try:
                        await page.goto(current_post_url, wait_until="domcontentloaded", timeout=45000)
                        await human_sleep(2.0, 3.5)
                    except Exception:
                        pass

                await human_sleep(ACTION_COOLDOWN_SECONDS[0], ACTION_COOLDOWN_SECONDS[1])

        except Exception as e:
            logger.warning("Lỗi khi xử lý bình luận thứ %d: %s", i, e)

    return replied_count


# ==============================================================================
# PHẦN 2: QUÉT & TRẢ LỜI MESSENGER INBOX (LẦN 1 CHÀO / LẦN 2 HẸN NHÂN VIÊN)
# ==============================================================================
async def inspect_messenger_conversation(page: Page) -> Dict[str, Any]:
    """
    Phân tích cuộc hội thoại Messenger đang mở trên Meta Business Suite để xác định:
    - Tên khách hàng (`customer_name`) trích xuất chính xác và làm sạch
    - Tin nhắn cuối cùng (`last_message_text`)
    - Tin nhắn cuối cùng là của Fanpage hay của khách (`last_sender_is_page`)
    - Trước đó Fanpage đã từng gửi tin nhắn nào trong cuộc trò chuyện này chưa (`has_prior_page_messages`)
    - Mã hội thoại (`thread_id`)
    """
    js_code = """
    (pageNames) => {
        const blacklist = [
            "chỉ báo trạng thái online",
            "online status indicator",
            "đang hoạt động",
            "đang có mặt",
            "hộp thư",
            "chưa đọc",
            "tạo quảng cáo",
            "thông tin chi tiết",
            "quy trình tự động hóa",
            "quảng bá"
        ];

        const isCleanName = (name) => {
            if (!name) return false;
            const low = name.toLowerCase().trim();
            if (low.length < 2 || low.length > 50) return false;
            if (blacklist.some(b => low.includes(b))) return false;
            if (pageNames.some(p => low.includes(p))) return false;
            return true;
        };

        const info = {
            customer_name: "bạn",
            last_message_text: "",
            last_sender_is_page: false,
            has_prior_page_messages: false,
            thread_id: ""
        };

        const urlParams = new URLSearchParams(window.location.search);
        info.thread_id = urlParams.get("selected_item_id") || "";

        // Cách 1: Tiêu đề ở cột chi tiết bên phải (role="complementary" hoặc x > 1100)
        const rightHeadings = Array.from(document.querySelectorAll('[role="complementary"] h2, [role="complementary"] h1, [role="heading"]'))
            .filter(el => {
                const r = el.getBoundingClientRect();
                return r.left > 1100 && r.top < 220;
            });
        for (const h of rightHeadings) {
            const t = (h.innerText || "").trim().split("\\n")[0].trim();
            if (isCleanName(t)) {
                info.customer_name = t;
                break;
            }
        }

        // Cách 2: Tiêu đề trên thanh header chat ở giữa (x: 400..900, y: 120..260)
        if (info.customer_name === "bạn") {
            const centerEls = Array.from(document.querySelectorAll('h1, h2, h3, [role="heading"], div._4ik4, div._4ik5'))
                .filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.left > 400 && r.left < 900 && r.top > 120 && r.top < 260 && el.children.length === 0;
                });
            for (const el of centerEls) {
                const t = (el.innerText || "").trim().split("\\n")[0].trim();
                if (isCleanName(t)) {
                    info.customer_name = t;
                    break;
                }
            }
        }

        // Tìm tất cả các bong bóng tin nhắn trong khung chat (x: 380..1120, y: 120..885), loại trừ ô soạn tin
        const chatNodes = Array.from(document.querySelectorAll('[dir="auto"], [role="row"]'))
            .filter(el => {
                if (el.closest('[role="textbox"], textarea, input')) return false;
                const r = el.getBoundingClientRect();
                return r.left > 380 && r.right < 1120 && r.top > 120 && r.bottom < 885 && r.height >= 16;
            });

        const messages = [];
        for (const node of chatNodes) {
            const txt = (node.innerText || "").trim();
            if (!txt || txt.length < 1) continue;
            const lower = txt.toLowerCase();
            if (
                lower.includes('đoạn chat này chứa tin trả lời') ||
                lower.includes('đã trả lời một quảng cáo') ||
                lower.includes('bạn có muốn được chỉ định') ||
                lower.includes('chỉ định cuộc trò chuyện')
            ) {
                continue;
            }

            const r = node.getBoundingClientRect();
            // Tin nhắn của Fanpage: nằm bên phải (r.left > 620) hoặc có chữ ký shop
            const hasBrandSignature = (
                lower.includes("dan86.vn") ||
                lower.includes("0933 133 516") ||
                lower.includes("nhân viên tư vấn") ||
                lower.includes("bộ phận tư vấn")
            );
            const isRightAligned = r.left > 620;
            const isPage = hasBrandSignature || isRightAligned;

            messages.push({ text: txt, isPage: isPage });
        }

        if (messages.length > 0) {
            const lastMsg = messages[messages.length - 1];
            info.last_message_text = lastMsg.text;
            info.last_sender_is_page = lastMsg.isPage;
            info.has_prior_page_messages = messages.slice(0, -1).some(m => m.isPage);
        }

        return info;
    }
    """
    try:
        raw = await page.evaluate(js_code, PAGE_NAMES)
        raw["customer_name"] = clean_customer_name(raw.get("customer_name", ""))
        return raw
    except Exception as e:
        logger.debug("Không thể phân tích DOM Messenger: %s", e)
        return {
            "customer_name": "bạn",
            "last_message_text": "",
            "last_sender_is_page": True,
            "has_prior_page_messages": False,
            "thread_id": "",
        }


async def process_messenger_inbox_tab(
    page: Page,
    memory: BotMemoryStore,
    dry_run: bool = False,
) -> int:
    """
    Quét tab Messenger trên Meta Business Suite:
    - Khách nhắn lần đầu -> Random mẫu chào & tư vấn sản phẩm lần 1.
    - Khách im một thời gian rồi nhắn lại (hoặc nhắn tiếp) -> Random mẫu "Đợi nhân viên sẽ liên hệ lại ngay"
      đúng 1 lần rồi giữ im lặng nhường cho nhân viên thật.
    """
    replied_count = 0
    logger.info("Đang kiểm tra Tab Messenger Inbox: %s", META_INBOX_MESSENGER_URL)
    await page.goto(META_INBOX_MESSENGER_URL, wait_until="domcontentloaded", timeout=45000)
    await human_sleep(4.0, 6.0)

    if not await verify_logged_in(page):
        logger.warning("Phiên đăng nhập Facebook chưa sẵn sàng hoặc đã hết hạn!")
        return 0

    thread_selectors = [
        'div[role="presentation"].x1ypdohk',
        'div._a6ag._a6ah',
        '[role="navigation"] [role="listitem"]',
        '[role="grid"] [role="row"]',
        'div[role="listitem"]',
    ]

    items_locator: Optional[Locator] = None
    for sel in thread_selectors:
        loc = page.locator(sel)
        if await loc.count() > 0:
            items_locator = loc
            break

    if items_locator is None:
        logger.info("Chưa tìm thấy cuộc hội thoại nào trong danh sách Messenger.")
        return 0

    total_items = min(await items_locator.count(), MAX_THREADS_PER_CYCLE)
    logger.info("Đang kiểm tra %d cuộc hội thoại Messenger gần nhất.", total_items)

    for i in range(total_items):
        try:
            await dismiss_blocking_modals(page)
            item = items_locator.nth(i)
            if not await item.is_visible():
                continue

            try:
                await safe_click(item, timeout=3000, position={"x": 150, "y": 40})
            except Exception:
                await safe_click(item, timeout=3000)
            await human_sleep(2.0, 3.5)

            conv = await inspect_messenger_conversation(page)
            customer_name = conv.get("customer_name") or "bạn"
            last_msg_text = conv.get("last_message_text") or ""
            last_sender_is_page = bool(conv.get("last_sender_is_page", False))
            has_prior_page_msgs = bool(conv.get("has_prior_page_messages", False))
            thread_id = conv.get("thread_id") or ""

            if last_sender_is_page:
                memory.touch_staff_interaction(customer_name=customer_name, thread_id=thread_id)
                continue

            # CHẾ ĐỘ THỬ NGHIỆM AN TOÀN TRONG PHIÊN SỬA LỖI:
            # Người dùng chỉ đạo: "đừng gửi tin cmt cho bất cứ ai ngoài đức trí trong phiên sửa lỗi này"
            if TEST_ONLY_AUTHOR_WHITELIST:
                c_norm = normalize_text(customer_name)
                if not any(w in c_norm for w in TEST_ONLY_AUTHOR_WHITELIST):
                    logger.info("Chế độ thử nghiệm an toàn: Bỏ qua hội thoại Messenger từ [%s] (Chỉ tương tác với Đức Trí trong phiên sửa lỗi này).", customer_name)
                    continue

            action, reply_text, thread_key = memory.decide_inbox_action(
                customer_name=customer_name,
                last_message_text=last_msg_text,
                last_sender_is_page=last_sender_is_page,
                has_prior_page_messages_in_dom=has_prior_page_msgs,
                thread_id=thread_id,
            )

            if action == "NONE" or not reply_text:
                continue

            logger.info(
                "Hội thoại [%s] -> Hành động [%s]: Khách nhắn '%s'",
                customer_name,
                action,
                last_msg_text[:60],
            )

            if dry_run:
                logger.info("[DRY-RUN] Sẽ gửi tin nhắn (%s): %s", action, reply_text)
                replied_count += 1
                continue

            composer = page.locator(
                'div[role="textbox"][contenteditable="true"], '
                'textarea[placeholder*="tin nhắn"], '
                'textarea[placeholder*="message"]'
            ).last

            if await composer.count() > 0 and await composer.is_visible():
                await type_human_like(page, composer, reply_text)
                await page.keyboard.press("Enter")
                await human_sleep(2.0, 3.5)

                memory.record_inbox_reply(
                    thread_key=thread_key,
                    customer_name=customer_name,
                    customer_message_text=last_msg_text,
                    action_type=action,
                    reply_text=reply_text,
                )
                replied_count += 1
                logger.info("Đã gửi phản hồi [%s] cho khách [%s] thành công!", action, customer_name)
                await human_sleep(ACTION_COOLDOWN_SECONDS[0], ACTION_COOLDOWN_SECONDS[1])

        except Exception as e:
            logger.warning("Lỗi khi xử lý hội thoại Messenger thứ %d: %s", i, e)

    return replied_count
