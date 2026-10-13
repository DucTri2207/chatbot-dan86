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
    META_NOTIFICATIONS_URL,
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
    Khôi phục file state/fb_storage_state.json từ:
    1. GitHub Actions Cache (đã khôi phục sẵn trên đĩa và có phiên hợp lệ).
    2. Biến môi trường FB_STORAGE_STATE (nếu đĩa chưa có phiên hợp lệ hoặc secret mới được cung cấp).
    3. File state/GITHUB_SECRET_VALUE.txt lưu trữ phiên chuẩn.
    """
    os.makedirs(os.path.dirname(STORAGE_STATE_FILE) or STATE_DIR, exist_ok=True)
    env_b64 = os.environ.get("FB_STORAGE_STATE", "").strip()

    # Kiểm tra xem file storage hiện tại trên đĩa (từ cache) đã có phiên hợp lệ (c_user, xs, origins) chưa
    disk_is_valid = False
    disk_origins = []
    if os.path.exists(STORAGE_STATE_FILE):
        try:
            with open(STORAGE_STATE_FILE, "r", encoding="utf-8") as f:
                cur_data = json.load(f)
            c_names = {c.get("name") for c in cur_data.get("cookies", []) if isinstance(c, dict)}
            disk_origins = cur_data.get("origins", [])
            has_origins = any("business.facebook.com" in o.get("origin", "") for o in disk_origins if isinstance(o, dict))
            if "c_user" in c_names and "xs" in c_names and has_origins:
                disk_is_valid = True
        except Exception:
            pass

    # Nếu trên đĩa đã có phiên hợp lệ từ cache:
    # Chỉ ghi đè từ FB_STORAGE_STATE nếu FB_STORAGE_STATE khác với GITHUB_SECRET_VALUE.txt
    # (nghĩa là người dùng vừa chủ động cập nhật secret mới trong GitHub repo settings)
    if disk_is_valid:
        user_updated_secret = False
        if env_b64 and os.path.exists(GITHUB_SECRET_EXPORT_FILE):
            try:
                with open(GITHUB_SECRET_EXPORT_FILE, "r", encoding="utf-8") as f_sec:
                    cached_b64 = f_sec.read().strip()
                if env_b64 != cached_b64:
                    user_updated_secret = True
            except Exception:
                pass

        if not user_updated_secret:
            logger.info("File fb_storage_state.json đã có sẵn phiên đăng nhập hợp lệ (từ Cache). Tiếp tục sử dụng.")
            return True

    # Khôi phục từ FB_STORAGE_STATE (nếu có)
    if env_b64:
        try:
            if env_b64.startswith("{"):
                raw_json = env_b64
            else:
                raw_json = base64.b64decode(env_b64).decode("utf-8")
            parsed = json.loads(raw_json)

            # Bảo toàn origins từ đĩa nếu parsed không có origins
            if disk_origins and not parsed.get("origins"):
                parsed["origins"] = disk_origins

            with open(STORAGE_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(parsed, f, ensure_ascii=False, indent=2)
            logger.info("Đã khôi phục phiên đăng nhập Facebook từ FB_STORAGE_STATE.")
            return True
        except Exception as e:
            logger.error("Lỗi giải mã FB_STORAGE_STATE: %s", e)

    # Nếu không có biến môi trường hoặc lỗi, kiểm tra GITHUB_SECRET_VALUE.txt
    if not disk_is_valid and os.path.exists(GITHUB_SECRET_EXPORT_FILE):
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


async def is_dangerous_hide_button(element: Any) -> bool:
    """
    Bộ lọc phòng thủ cấp cao: Tuyệt đối không bao giờ click vào nút 'Ẩn' / 'Hide' bình luận.
    Nếu bất kỳ nút nào có text, aria-label, hoặc title chứa 'ẩn', 'hide', 'ẩn bình luận', 'hide comment',
    tuyệt đối bỏ qua, không được click!
    """
    if element is None:
        return False
    try:
        eval_fn = getattr(element, "evaluate", None)
        if callable(eval_fn):
            raw = await element.evaluate("""el => {
                const t = (el.innerText || '').trim().toLowerCase();
                const a = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                const title = (el.getAttribute('title') || '').trim().toLowerCase();
                return t + ' ' + a + ' ' + title;
            }""")
            check_str = (raw or "").lower()
            if not check_str:
                return False
            bad_phrases = ["ẩn bình luận", "hide comment", "ẩn phản hồi", "hide reply", "hide this comment"]
            if any(b in check_str for b in bad_phrases):
                return True
            tokens = re.split(r'[\s\.,;:\-_/|]+', check_str)
            if "ẩn" in tokens or "hide" in tokens:
                return True
    except Exception:
        pass
    return False


async def safe_click(
    locator: Locator,
    timeout: int = 2500,
    position: Optional[Dict[str, float]] = None,
) -> bool:
    """
    Thực hiện nhấp chuột an toàn chống lỗi pointer-events interception:
    1. Kiểm tra phòng thủ: Tuyệt đối không bấm nút Ẩn/Hide bình luận.
    2. Cuộn phần tử vào tầm nhìn (scroll_into_view_if_needed).
    3. Thử nhấp bằng Playwright với force=True và timeout quy định.
    4. Nếu gặp ngoại lệ / timeout (do bị phần tử khác che phủ / subtree intercepts pointer events),
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


async def get_element_coordinates(element: Any) -> Optional[Dict[str, float]]:
    """
    Trích xuất tọa độ DOM pixel thực tế {x, y, width, height, left, top, right, bottom}
    từ getBoundingClientRect() của phần tử (tương đương F12 Console).
    """
    if element is None:
        return None
    try:
        count_fn = getattr(element, "count", None)
        if callable(count_fn):
            cnt = await element.count()
            if cnt == 0:
                return None
        vis_fn = getattr(element, "is_visible", None)
        if callable(vis_fn):
            if not await element.is_visible():
                return None
    except Exception:
        pass

    # 1. Thử evaluate getBoundingClientRect() trực tiếp trên DOM
    try:
        eval_fn = getattr(element, "evaluate", None)
        if callable(eval_fn):
            res = await element.evaluate("""el => {
                try {
                    const r = el.getBoundingClientRect();
                    return {
                        x: r.x !== undefined ? r.x : r.left,
                        y: r.y !== undefined ? r.y : r.top,
                        width: r.width,
                        height: r.height,
                        left: r.left,
                        top: r.top,
                        right: r.right,
                        bottom: r.bottom
                    };
                } catch (_) {
                    return null;
                }
            }""")
            if isinstance(res, dict) and isinstance(res.get("width"), (int, float)) and isinstance(res.get("height"), (int, float)):
                if res.get("width", 0) > 0 and res.get("height", 0) > 0:
                    return {
                        "x": float(res.get("x", 0.0)),
                        "y": float(res.get("y", 0.0)),
                        "width": float(res.get("width", 0.0)),
                        "height": float(res.get("height", 0.0)),
                        "left": float(res.get("left", res.get("x", 0.0))),
                        "top": float(res.get("top", res.get("y", 0.0))),
                        "right": float(res.get("right", res.get("x", 0.0) + res.get("width", 0.0))),
                        "bottom": float(res.get("bottom", res.get("y", 0.0) + res.get("height", 0.0))),
                    }
    except Exception as e:
        logger.debug("get_element_coordinates evaluate: %s", e)

    # 2. Fallback sang element.bounding_box()
    try:
        bbox_fn = getattr(element, "bounding_box", None)
        if callable(bbox_fn):
            box = await element.bounding_box()
            if isinstance(box, dict) and isinstance(box.get("width"), (int, float)) and isinstance(box.get("height"), (int, float)):
                if box.get("width", 0) > 0 and box.get("height", 0) > 0:
                    return {
                        "x": float(box.get("x", 0.0)),
                        "y": float(box.get("y", 0.0)),
                        "width": float(box.get("width", 0.0)),
                        "height": float(box.get("height", 0.0)),
                        "left": float(box.get("x", 0.0)),
                        "top": float(box.get("y", 0.0)),
                        "right": float(box.get("x", 0.0) + box.get("width", 0.0)),
                        "bottom": float(box.get("y", 0.0) + box.get("height", 0.0)),
                    }
    except Exception as e:
        logger.debug("get_element_coordinates bounding_box: %s", e)

    return None


async def physical_mouse_click(page: Any, x: float, y: float) -> bool:
    """Click chuột máy tính vật lý tại tọa độ pixel (x, y) bằng page.mouse.click."""
    try:
        mouse = getattr(page, "mouse", None)
        if mouse is not None:
            click_fn = getattr(mouse, "click", None)
            if callable(click_fn):
                res = click_fn(x, y)
                if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                    await res
                return True
    except Exception as e:
        logger.debug("Lỗi physical_mouse_click tại (%s, %s): %s", x, y, e)
    return False


async def click_element_at_physical_coordinates(
    page: Any,
    element: Any,
    timeout_ms: int = 2500,
) -> bool:
    """
    Trích xuất tọa độ DOM vật lý qua getBoundingClientRect() và dùng chuột máy tính
    click vật lý (page.mouse.click(center_x, center_y)).
    """
    try:
        scroll_fn = getattr(element, "scroll_into_view_if_needed", None)
        if callable(scroll_fn):
            res_s = scroll_fn(timeout=1500)
            if asyncio.iscoroutine(res_s) or hasattr(res_s, "__await__"):
                await res_s
    except Exception:
        pass

    coords = await get_element_coordinates(element)
    if coords and coords.get("width", 0) > 0 and coords.get("height", 0) > 0:
        cx = coords["x"] + coords["width"] / 2.0
        cy = coords["y"] + coords["height"] / 2.0
        clicked = await physical_mouse_click(page, cx, cy)
        if clicked:
            return True

    return await safe_click(element, timeout=timeout_ms)


def parse_notification_text(text: str) -> Dict[str, Any]:
    """
    Phân tích nội dung văn bản của một thông báo Facebook:
    - author_name: Tên người bình luận (làm sạch qua clean_customer_name)
    - time_str: Thời gian tương đối ('vừa xong', '1 phút', '2 giờ',...)
    - comment_snippet: Trích đoạn nội dung bình luận (nếu có)
    - is_comment_notif: Có phải thông báo bình luận/phản hồi không
    - is_old: Bình luận cũ (> 3 ngày, tuần, tháng, năm)
    """
    if not text:
        return {
            "is_comment_notif": False,
            "author_name": "bạn",
            "time_str": "",
            "comment_snippet": "",
            "is_old": False,
        }

    clean_raw = " ".join(text.strip().split())
    lower = clean_raw.lower()

    # 1. Kiểm tra từ khóa thông báo bình luận / phản hồi
    comment_keywords = [
        "đã bình luận",
        "commented",
        "đã phản hồi",
        "replied",
        "đã trả lời",
        "bình luận về",
        "phản hồi về",
        "bình luận của",
        "trả lời bình luận",
        "trả lời một bình luận",
        "đã nhắc đến bạn trong một bình luận",
        "đã nhắc đến trang của bạn trong một bình luận",
        "đã nhắc đến bạn",
        "nhắc đến bạn trong một bình luận",
        "mentioned you in a comment",
        "mentioned your page in a comment",
        "đã gắn thẻ bạn trong một bình luận",
        "đã gắn thẻ trang của bạn trong một bình luận",
        "đã gắn thẻ bạn",
        "gắn thẻ bạn trong một bình luận",
        "gắn thẻ trang của bạn trong một bình luận",
        "gắn thẻ bạn",
        "đã gắn thẻ",
        "gắn thẻ",
        "tagged you in a comment",
        "tagged your page in a comment",
        "tagged you",
        "tagged your page",
        "đã thêm một bình luận",
        "thêm một bình luận",
        "đã viết một bình luận",
        "viết một bình luận",
    ]
    has_kw = any(kw in lower for kw in comment_keywords)
    if not has_kw:
        return {
            "is_comment_notif": False,
            "author_name": "bạn",
            "time_str": "",
            "comment_snippet": "",
            "is_old": False,
        }

    # 2. Trích xuất tên tác giả
    author_name = ""
    match_author = re.search(
        r"^(.+?)\s+(?:đã bình luận|commented|đã phản hồi|replied|đã trả lời|bình luận về|phản hồi về|trả lời bình luận|đã nhắc đến|nhắc đến|mentioned|đã gắn thẻ|gắn thẻ|tagged|đã thêm một bình luận|thêm một bình luận|đã viết một bình luận|viết một bình luận)\b",
        clean_raw,
        re.IGNORECASE,
    )
    if match_author:
        raw_author = match_author.group(1).strip()
        raw_author = re.sub(r"^(?:thông báo mới|notification):\s*", "", raw_author, flags=re.IGNORECASE)
        author_name = clean_customer_name(raw_author)
    else:
        # Fallback tìm dạng 'bình luận từ/by/của X'
        match_author_alt = re.search(
            r"(?:từ|by|của)\s+([^\n:·•]+?)(?::|\s+[·•]|\s+\d+\s*(?:giây|phút|giờ|ngày|tuần)|$)",
            clean_raw,
            re.IGNORECASE,
        )
        if match_author_alt:
            author_name = clean_customer_name(match_author_alt.group(1).strip())
        else:
            author_name = "bạn"

    # 3. Trích xuất snippet nội dung bình luận (nằm trong ngoặc kép hoặc sau dấu hai chấm)
    snippet = ""
    quote_match = re.search(r"['\"“](.+?)['\"”]", clean_raw)
    if quote_match:
        snippet = quote_match.group(1).strip()
    else:
        colon_match = re.search(
            r":\s*([^·•\n]+?)(?:\s*[·•]|\s+\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm|m|h|d|w|y)|\s+vừa xong|$)",
            clean_raw,
            re.IGNORECASE,
        )
        if colon_match:
            snippet = colon_match.group(1).strip()

    snippet = clean_comment_text(snippet)

    # Tạo chuỗi text loại bỏ snippet bình luận để regex thời gian không bắt nhầm số/đơn vị thời gian trong câu của khách
    text_for_time = clean_raw
    if quote_match:
        text_for_time = clean_raw[:quote_match.start()] + " " + clean_raw[quote_match.end():]
    elif colon_match:
        text_for_time = clean_raw[:colon_match.start()] + " " + clean_raw[colon_match.end():]

    # 4. Trích xuất timestamp tương đối
    time_str = ""
    dot_match = re.search(r"[·•]\s*([^\n]+)$", text_for_time)
    if dot_match:
        cand_time = dot_match.group(1).strip()
        if re.search(
            r"\b(?:\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm|s|m|h|d|w|y|secs?|mins?|hours?|days?|weeks?|months?|years?)|vừa xong|just now|vài giây)\b",
            cand_time,
            re.IGNORECASE,
        ):
            time_str = cand_time

    if not time_str:
        # Tìm match cuối cùng trong text_for_time để ưu tiên timestamp ở đuôi thông báo
        all_time_matches = list(re.finditer(
            r"\b(\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm|s|m|h|d|w|y|secs?|mins?|hours?|days?|weeks?|months?|years?)(?:\s+(?:trước|ago))?|vừa xong|just now|vài giây)\b",
            text_for_time,
            re.IGNORECASE,
        ))
        if all_time_matches:
            time_str = all_time_matches[-1].group(1).strip()

    # 5. Kiểm tra thời gian cũ
    is_old = is_old_comment_timestamp(time_str)

    return {
        "is_comment_notif": True,
        "author_name": author_name or "bạn",
        "time_str": time_str,
        "comment_snippet": snippet,
        "is_old": is_old,
    }


async def type_human_like(page: Page, locator: Locator, text: str) -> None:
    """
    Gõ văn bản vào ô chat giống người thật (hỗ trợ xuống dòng Shift+Enter
    để không bị gửi sớm khi mẫu câu có nhiều dòng).
    Sử dụng click chuột vật lý vào tọa độ DOM trước khi gõ.
    """
    await click_element_at_physical_coordinates(page, locator, timeout_ms=2500)
    await human_sleep(0.4, 0.9)

    # Xóa sạch bất kỳ văn bản cũ hoặc gợi ý có sẵn trước khi gõ
    try:
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await asyncio.sleep(0.1)
    except Exception:
        pass

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


async def _safe_eval_count(loc) -> int:
    if loc is None or not hasattr(loc, "count"):
        return 0
    try:
        cnt_val = loc.count()
        if asyncio.iscoroutine(cnt_val) or hasattr(cnt_val, "__await__"):
            cnt_val = await cnt_val
        if isinstance(cnt_val, (int, float)):
            return int(cnt_val)
        return 0
    except Exception:
        return 0


async def _safe_eval_visible(loc) -> bool:
    if loc is None or not hasattr(loc, "is_visible"):
        return False
    try:
        vis_val = loc.is_visible()
        if asyncio.iscoroutine(vis_val) or hasattr(vis_val, "__await__"):
            vis_val = await vis_val
        return bool(vis_val)
    except Exception:
        return False


async def submit_credentials_on_page(target_page, email: str = "", password: str = "") -> bool:
    """
    Điền tài khoản FB_EMAIL và mật khẩu FB_PASSWORD vào form đăng nhập và gửi an toàn.
    BẢO MẬT 100%: Tuyệt đối không log tài khoản email hoặc mật khẩu ra màn hình hay exception logs.
    """
    clean_email = (email or "").strip()
    if (clean_email.startswith('"') and clean_email.endswith('"')) or (
        clean_email.startswith("'") and clean_email.endswith("'")
    ):
        clean_email = clean_email[1:-1].strip()

    clean_pass = (password or "").strip()
    if (clean_pass.startswith('"') and clean_pass.endswith('"')) or (
        clean_pass.startswith("'") and clean_pass.endswith("'")
    ):
        clean_pass = clean_pass[1:-1].strip()

    if not clean_pass:
        logger.warning("Không thể điền form đăng nhập do biến môi trường FB_PASSWORD chưa được cấu hình.")
        return False

    try:
        # 1. Tìm và điền ô nhập email/tài khoản (nếu có)
        email_sel = (
            'input[name="email"], input[type="email"], input#email, '
            'input#m_login_email, input[name="m_login_email"], input[data-sigil*="m_login_email"], '
            'input[name="login"], input[autocomplete="username"], '
            'input[aria-label*="email" i], input[placeholder*="email" i], '
            'input[placeholder*="số di động" i], input[placeholder*="phone" i], '
            'input[aria-label*="phone" i]'
        )
        email_loc = target_page.locator(email_sel).first
        email_count = await _safe_eval_count(email_loc)
        if email_count > 0 and clean_email:
            await email_loc.fill(clean_email)
            await asyncio.sleep(0.3)

        # 2. Tìm và điền ô nhập mật khẩu
        pass_sel = (
            'input[name="pass"], input[type="password"], input#pass, '
            'input#m_login_password, input[name="m_login_password"], input[data-sigil*="m_login_password"], '
            'input[autocomplete="current-password"], '
            'input[aria-label*="mật khẩu" i], input[placeholder*="mật khẩu" i], '
            'input[aria-label*="password" i], input[placeholder*="password" i]'
        )
        pass_loc = target_page.locator(pass_sel).first
        pass_count = await _safe_eval_count(pass_loc)
        if pass_count > 0:
            await pass_loc.fill(clean_pass)
            await asyncio.sleep(0.3)
        else:
            # Nếu là form chia bước (bước 1 nhập email -> bấm Tiếp tục -> bước 2 nhập mật khẩu)
            next_btn = target_page.locator(
                'button[type="submit"], input[type="submit"], '
                'button:has-text("Tiếp tục"), div[role="button"]:has-text("Tiếp tục"), '
                'button:has-text("Next"), div[role="button"]:has-text("Next")'
            ).first
            if await _safe_eval_count(next_btn) > 0:
                await next_btn.click(timeout=4000, force=True)
                await asyncio.sleep(1.0)
                pass_loc = target_page.locator(pass_sel).first
                if await _safe_eval_count(pass_loc) > 0:
                    await pass_loc.fill(clean_pass)
                    await asyncio.sleep(0.3)
                    pass_count = 1

        if pass_count == 0:
            logger.warning("Không tìm thấy ô nhập mật khẩu trên trang đăng nhập.")
            return False

        # 3. Gửi form đăng nhập
        sub_sel = (
            'button[name="login"], button[type="submit"], button#loginbutton, '
            'input[type="submit"], button[name="__CONFIRM__"], '
            '[data-testid*="royal_login_button"], [data-testid*="login"], '
            'button[data-sigil*="m_login_button"], input[data-sigil*="m_login_button"], '
            'button:has-text("Đăng nhập"), div[role="button"]:has-text("Đăng nhập"), '
            'button:has-text("Log In"), button:has-text("Log in"), div[role="button"]:has-text("Log In"), '
            'button:has-text("Tiếp tục"), div[role="button"]:has-text("Tiếp tục"), '
            'button:has-text("Continue"), div[role="button"]:has-text("Continue")'
        )
        sub_btn = target_page.locator(sub_sel).first
        sub_count = await _safe_eval_count(sub_btn)
        if sub_count > 0:
            try:
                await sub_btn.click(timeout=5000, force=True)
            except Exception:
                if pass_count > 0 and hasattr(pass_loc, "press"):
                    await pass_loc.press("Enter")
                elif email_count > 0 and hasattr(email_loc, "press"):
                    await email_loc.press("Enter")
        elif pass_count > 0 and hasattr(pass_loc, "press"):
            await pass_loc.press("Enter")
        elif email_count > 0 and hasattr(email_loc, "press"):
            await email_loc.press("Enter")

        return True
    except Exception as e_fill:
        err_msg = str(e_fill)
        for p in (clean_pass, password):
            if p and p in err_msg:
                err_msg = err_msg.replace(p, "[REDACTED_PASSWORD]")
        for e in (clean_email, email):
            if e and e in err_msg:
                err_msg = err_msg.replace(e, "[REDACTED_EMAIL]")
        logger.warning("Lỗi điền thông tin form đăng nhập: %s", err_msg)
        return False


async def verify_logged_in(page: Page) -> bool:
    """
    Kiểm tra xem trình duyệt đã đăng nhập vào Meta Business Suite chưa.
    Tự động xử lý nút bấm đăng nhập một chạm 'Tiếp tục bằng Facebook' / 'Tiếp tục dưới tên...'
    nếu Meta Business Suite đang ở màn hình chuyển giao phiên (SSO bridge).
    - Xử lý song song: Chờ popup HOẶC chờ trang chính tự chuyển hướng trực tiếp (tránh timeout trên headless VPS).
    - Thoát khỏi định kiến cứng ngắc: Chấp nhận cả /latest/notifications, /latest/home, /latest/inbox.
    - Kích hoạt phiên: Nếu kẹt loginpage nhưng đã có cookies Facebook, điều hướng qua facebook.com
      để đồng bộ session giữa hai domain.
    """
    import urllib.parse

    parsed = urllib.parse.urlparse(page.url)
    path = parsed.path.lower()

    # 1. Kiểm tra nghiêm ngặt xem trang có đang ở màn hình đăng nhập / mật khẩu không
    is_at_loginpage = "/business/loginpage" in path or path.startswith("/login") or path == "/login" or "checkpoint" in path
    has_login_form = False
    try:
        has_login_form = await page.locator('input[name="email"], input[name="pass"], input[type="password"]').count() > 0
    except Exception:
        pass

    mbs_indicators = [
        '[data-pagelet*="ThreadList"]',
        'div._a6ag._a6ah',
        'div[role="presentation"].x1ypdohk',
        'div:has-text("Bình luận trên Facebook")',
        'div:has-text("Tất cả tin nhắn")',
        'div:has-text("Hộp thư")',
        '[data-dan86-notif-idx]',
        '[data-pagelet*="Notifications"]',
        'div:has-text("Thông báo")',
        '[aria-label*="Thông báo"]',
        '[aria-label*="Hộp thư"]',
        'div:has-text("Trang chủ")',
        'div:has-text("Meta Business Suite")',
    ]

    # Nếu KHÔNG ở màn hình đăng nhập và không có login form:
    if not is_at_loginpage and not has_login_form:
        for ind in mbs_indicators:
            try:
                loc = page.locator(ind).first
                if await loc.count() > 0 and await loc.is_visible():
                    return True
            except Exception:
                pass
        # Nếu URL đã nằm trên các trang quản trị hợp lệ của Meta Business Suite (/latest/...)
        if (
            path.startswith("/latest/")
            or "/latest/notifications" in path
            or "/latest/home" in path
            or "/latest/inbox" in path
        ):
            return True
    elif has_login_form and not is_at_loginpage:
        # Trang thường chứa form login -> Chưa đăng nhập
        return False

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
            'div[role="button"]:has-text("Log in with Facebook")',
        ]

        clicked = False
        sso_success = False
        for sel in sso_selectors:
            loc = page.locator(sel).first
            if await _safe_eval_count(loc) > 0 and await _safe_eval_visible(loc):
                logger.info("Bấm nút bắc cầu phiên Facebook sang Meta: %s", sel)
                popup_future = asyncio.get_event_loop().create_future()
                def on_sso_page(new_p):
                    if not popup_future.done():
                        popup_future.set_result(new_p)

                page.context.on("page", on_sso_page)
                try:
                    await loc.click(timeout=5000, force=True)
                    clicked = True

                    # XỬ LÝ SONG SONG: Chờ popup HOẶC chờ trang chính chuyển hướng (tránh timeout vô ích trên Headless VPS)
                    async def wait_popup():
                        return await popup_future

                    async def watch_main_page_nav():
                        while True:
                            await asyncio.sleep(0.4)
                            c_p = urllib.parse.urlparse(page.url).path.lower()
                            if "/business/loginpage" not in c_p and not c_p.startswith("/login") and "checkpoint" not in c_p:
                                return True
                            try:
                                if await page.locator('input[name="pass"], input[type="password"]').count() > 0:
                                    return "inline_form"
                            except Exception:
                                pass

                    popup_task = asyncio.create_task(wait_popup())
                    redirect_task = asyncio.create_task(watch_main_page_nav())

                    done, pending = await asyncio.wait(
                        [popup_task, redirect_task],
                        timeout=15.0,
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    for p in pending:
                        p.cancel()

                    if popup_task in done and not popup_task.cancelled() and popup_task.exception() is None:
                        try:
                            popup = popup_task.result()
                            load_state_fn = getattr(popup, "wait_for_load_state", None)
                            if callable(load_state_fn):
                                ls_res = load_state_fn("domcontentloaded")
                                if asyncio.iscoroutine(ls_res) or hasattr(ls_res, "__await__"):
                                    await ls_res
                            await asyncio.sleep(0.3)

                            # Hàm an toàn xử lý xác thực mật khẩu SSO (Bảo mật 100%, không rò rỉ secret)
                            async def handle_sso_password(p_target) -> bool:
                                fb_password = os.environ.get("FB_PASSWORD", "").strip()
                                if (fb_password.startswith('"') and fb_password.endswith('"')) or (
                                    fb_password.startswith("'") and fb_password.endswith("'")
                                ):
                                    fb_password = fb_password[1:-1].strip()

                                fb_email = os.environ.get("FB_EMAIL", "").strip()
                                if (fb_email.startswith('"') and fb_email.endswith('"')) or (
                                    fb_email.startswith("'") and fb_email.endswith("'")
                                ):
                                    fb_email = fb_email[1:-1].strip()

                                if not fb_password:
                                    logger.warning(
                                        "Popup SSO yêu cầu nhập mật khẩu thủ công nhưng biến môi trường FB_PASSWORD chưa được cấu hình. "
                                        "Đóng popup để không chặn vòng quét."
                                    )
                                    try:
                                        await p_target.close()
                                    except Exception:
                                        pass
                                    return False

                                logger.info("Popup SSO yêu cầu xác nhận mật khẩu. Đang tự động nạp mật khẩu an toàn từ biến môi trường...")
                                try:
                                    # Nếu popup có ô email (inline login trong popup)
                                    if fb_email:
                                        try:
                                            em_loc = p_target.locator('input[name="email"], input[type="email"], input#email').first
                                            if await em_loc.count() > 0:
                                                await em_loc.fill(fb_email)
                                                await asyncio.sleep(0.3)
                                        except Exception:
                                            pass

                                    p_input = p_target.locator('input[name="pass"], input[type="password"]').first
                                    await p_input.fill(fb_password)
                                    await asyncio.sleep(0.3)

                                    sub_btn = p_target.locator(
                                        'button[type="submit"], '
                                        'button[name="login"], '
                                        'button[name="__CONFIRM__"], '
                                        'input[type="submit"], '
                                        'div[role="button"]:has-text("Tiếp tục"), '
                                        'button:has-text("Tiếp tục"), '
                                        'div[role="button"]:has-text("Xác nhận"), '
                                        'button:has-text("Xác nhận"), '
                                        'button:has-text("Đăng nhập"), '
                                        'div[role="button"]:has-text("Continue"), '
                                        'button:has-text("Continue"), '
                                        'div[role="button"]:has-text("Confirm"), '
                                        'button:has-text("Confirm")'
                                    ).first
                                    sub_count = await sub_btn.count() if hasattr(sub_btn, "count") else 0
                                    if sub_count > 0:
                                        try:
                                            await sub_btn.click(timeout=4000, force=True)
                                        except Exception:
                                            await p_input.press("Enter")
                                    else:
                                        await p_input.press("Enter")

                                    # Chờ popup xử lý và đóng lại sau khi gửi mật khẩu (tối đa 12s)
                                    try:
                                        await p_target.wait_for_event("close", timeout=12000)
                                        logger.info("Popup SSO xác nhận mật khẩu thành công và đã tự đóng.")
                                        return True
                                    except Exception:
                                        if not getattr(p_target, "is_closed", lambda: False)():
                                            # Nếu form chưa submit, thử gửi phím Enter dự phòng
                                            rem_pass = await p_target.locator('input[name="pass"], input[type="password"]').count()
                                            if rem_pass > 0:
                                                try:
                                                    await p_input.press("Enter")
                                                    await asyncio.sleep(2.0)
                                                except Exception:
                                                    pass

                                            if getattr(p_target, "is_closed", lambda: False)():
                                                logger.info("Popup SSO đã hoàn tất xác nhận mật khẩu và tự đóng.")
                                                return True

                                            pop_url = getattr(p_target, "url", "").lower()
                                            rem_pass_after = await p_target.locator('input[name="pass"], input[type="password"]').count()
                                            has_checkpoint = (
                                                "checkpoint" in pop_url
                                                or await p_target.locator('input[name="approvals_code"]').count() > 0
                                            )
                                            if rem_pass_after > 0 or has_checkpoint:
                                                logger.warning(
                                                    "Popup SSO xác nhận mật khẩu không thành công (mật khẩu không đúng hoặc gặp checkpoint/2FA). Đóng popup."
                                                )
                                                try:
                                                    await p_target.close()
                                                except Exception:
                                                    pass
                                                return False
                                            else:
                                                logger.info("Popup SSO đã hoàn tất xác nhận mật khẩu.")
                                                try:
                                                    await p_target.close()
                                                except Exception:
                                                    pass
                                                return True
                                        return True
                                except Exception as e_pw:
                                    err_msg = str(e_pw)
                                    if fb_password and fb_password in err_msg:
                                        err_msg = err_msg.replace(fb_password, "[REDACTED_PASSWORD]")
                                    if fb_email and fb_email in err_msg:
                                        err_msg = err_msg.replace(fb_email, "[REDACTED_EMAIL]")
                                    logger.warning("Lỗi trong quá trình tự động xác thực mật khẩu SSO: %s", err_msg)
                                    try:
                                        await p_target.close()
                                    except Exception:
                                        pass
                                    return False

                            # 1. Kiểm tra nếu popup hiển thị ô nhập mật khẩu hoặc email ngay khi mở
                            is_cl = getattr(popup, "is_closed", lambda: False)()
                            if not is_cl:
                                pass_count = await popup.locator('input[name="pass"], input[type="password"]').count()
                                email_count = await popup.locator('input[name="email"], input[type="email"], input#email').count()
                                if pass_count > 0 or email_count > 0:
                                    sso_success = await handle_sso_password(popup)
                                else:
                                    # Bấm nút 'Tiếp tục' hoặc profile người dùng trong popup
                                    p_btn = popup.locator(
                                        'div[role="button"]:has-text("Tiếp tục"), '
                                        'button:has-text("Tiếp tục"), '
                                        'a[role="button"]:has-text("Tiếp tục"), '
                                        '[aria-label*="Tiếp tục"], '
                                        'div[role="button"]:has-text("Đức Trí"), '
                                        'button:has-text("Đức Trí"), '
                                        '[aria-label*="Đức Trí"], '
                                        'button[name="__CONFIRM__"], '
                                        'button[name="login"], '
                                        'input[type="submit"], '
                                        'div[role="button"]:has-text("Continue"), '
                                        'button:has-text("Continue"), '
                                        'a[role="button"]:has-text("Continue"), '
                                        '[aria-label*="Continue"]'
                                    ).first
                                    p_count = await p_btn.count() if hasattr(p_btn, "count") else 0
                                    if p_count > 0:
                                        await p_btn.click(timeout=4000, force=True)
                                    else:
                                        txt_loc = popup.locator(
                                            '[role="button"]:has-text("Tiếp tục"), '
                                            'button:has-text("Tiếp tục"), '
                                            '[role="button"]:has-text("Continue"), '
                                            'button:has-text("Continue")'
                                        ).first
                                        if hasattr(txt_loc, "count") and await txt_loc.count() > 0:
                                            await txt_loc.click(timeout=4000, force=True)

                                    await asyncio.sleep(0.3)
                                    # Chờ popup đóng lại (thành công) HOẶC xuất hiện ô nhập mật khẩu
                                    if not getattr(popup, "is_closed", lambda: False)():
                                        has_pass_prompt = False
                                        for _ in range(20):  # Tối đa 10s (mỗi 0.5s)
                                            if getattr(popup, "is_closed", lambda: False)():
                                                break
                                            if (
                                                await popup.locator('input[name="pass"], input[type="password"]').count() > 0
                                                or await popup.locator('input[name="email"], input[type="email"], input#email').count() > 0
                                            ):
                                                has_pass_prompt = True
                                                break
                                            await asyncio.sleep(0.5)

                                        if has_pass_prompt:
                                            sso_success = await handle_sso_password(popup)
                                        else:
                                            if not getattr(popup, "is_closed", lambda: False)():
                                                pop_url = getattr(popup, "url", "").lower()
                                                has_checkpoint = (
                                                    "checkpoint" in pop_url
                                                    or await popup.locator('input[name="approvals_code"]').count() > 0
                                                )
                                                if has_checkpoint:
                                                    logger.warning("Popup SSO chuyển sang trang checkpoint/2FA. Đóng popup.")
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

                    elif redirect_task in done and not redirect_task.cancelled() and redirect_task.exception() is None:
                        res_nav = redirect_task.result()
                        if res_nav is True:
                            logger.info("Trang chính đã tự chuyển hướng thành công mà không cần popup: %s", page.url[:80])
                            sso_success = True
                        elif res_nav == "inline_form":
                            logger.info("Nút SSO mở ra form đăng nhập inline trên trang. Đang tự động nạp thông tin đăng nhập...")
                            fb_email = os.environ.get("FB_EMAIL", "").strip()
                            if (fb_email.startswith('"') and fb_email.endswith('"')) or (
                                fb_email.startswith("'") and fb_email.endswith("'")
                            ):
                                fb_email = fb_email[1:-1].strip()

                            fb_password = os.environ.get("FB_PASSWORD", "").strip()
                            if (fb_password.startswith('"') and fb_password.endswith('"')) or (
                                fb_password.startswith("'") and fb_password.endswith("'")
                            ):
                                fb_password = fb_password[1:-1].strip()

                            if fb_password:
                                inline_ok = await submit_credentials_on_page(page, fb_email, fb_password)
                                if inline_ok:
                                    for _ in range(8):
                                        await asyncio.sleep(0.5)
                                        c_p = urllib.parse.urlparse(page.url).path.lower()
                                        if "/business/loginpage" not in c_p and not c_p.startswith("/login") and "checkpoint" not in c_p:
                                            sso_success = True
                                            break

                except Exception as e_click:
                    err_msg = str(e_click)
                    pw = os.environ.get("FB_PASSWORD", "").strip().strip('"').strip("'")
                    em = os.environ.get("FB_EMAIL", "").strip().strip('"').strip("'")
                    for s in (pw, em):
                        if s and s in err_msg:
                            err_msg = err_msg.replace(s, "[REDACTED]")
                    logger.debug("Lỗi bấm nút SSO: %s", err_msg)
                finally:
                    try:
                        page.context.remove_listener("page", on_sso_page)
                    except Exception:
                        pass

                cur_p = urllib.parse.urlparse(page.url).path.lower()
                if "/business/loginpage" not in cur_p and not cur_p.startswith("/login") and "checkpoint" not in cur_p:
                    sso_success = True
                break

        if clicked and sso_success:
            # Chờ trang chính tự chuyển hướng hoặc chủ động điều hướng tới URL inbox mục tiêu
            try:
                for _ in range(6):
                    await asyncio.sleep(0.5)
                    cur_p = urllib.parse.urlparse(page.url).path.lower()
                    if "/business/loginpage" not in cur_p and not cur_p.startswith("/login"):
                        break
                cur_parsed = urllib.parse.urlparse(page.url)
                cur_p = cur_parsed.path.lower()
                cur_host = cur_parsed.netloc.lower()
                if (
                    "/business/loginpage" in cur_p
                    or cur_p.startswith("/login")
                    or "business.facebook.com" not in cur_host
                    or not cur_p.startswith("/latest/")
                ):
                    await page.goto(META_INBOX_COMMENTS_URL, wait_until="domcontentloaded", timeout=30000)
                await human_sleep(1.0, 2.0)
            except Exception as e_nav:
                logger.debug("Lỗi điều hướng trang chính sau SSO: %s", e_nav)

        # BỔ SUNG CƠ CHẾ KÍCH HOẠT PHIÊN:
        # Nếu bị kẹt tại loginpage dù cookie Facebook đã có, điều hướng qua https://www.facebook.com/
        # rồi quay lại META_INBOX_COMMENTS_URL để cookies đồng bộ giữa hai domain.
        cur_p = urllib.parse.urlparse(page.url).path.lower()
        if "/business/loginpage" in cur_p or cur_p.startswith("/login"):
            try:
                cookies_fn = getattr(page.context, "cookies", None)
                cookies = []
                if callable(cookies_fn):
                    c_res = cookies_fn()
                    if asyncio.iscoroutine(c_res) or hasattr(c_res, "__await__"):
                        cookies = await c_res
                    elif isinstance(c_res, list):
                        cookies = c_res
                has_fb_auth_cookie = any(c.get("name") in ("c_user", "xs") for c in cookies if isinstance(c, dict))
                if has_fb_auth_cookie:
                    logger.info("Phát hiện cookies Facebook (c_user/xs) hợp lệ nhưng Meta Business Suite kẹt tại loginpage. Kích hoạt bắc cầu phiên: Truy cập facebook.com để đồng bộ...")
                    try:
                        await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30000)
                        await human_sleep(1.5, 2.5)
                        logger.info("Đã đồng bộ session Facebook.com. Điều hướng lại về Meta Business Suite: %s", META_INBOX_COMMENTS_URL)
                        await page.goto(META_INBOX_COMMENTS_URL, wait_until="domcontentloaded", timeout=45000)
                        await human_sleep(2.0, 3.5)
                    except Exception as e_sync:
                        logger.warning("Lỗi kích hoạt bắc cầu session facebook.com: %s", e_sync)

                    cur_p = urllib.parse.urlparse(page.url).path.lower()
                    if "/business/loginpage" in cur_p or cur_p.startswith("/login"):
                        for sel in sso_selectors:
                            loc = page.locator(sel).first
                            if await loc.count() > 0 and await loc.is_visible():
                                logger.info("Bấm nút SSO lần 2 sau khi đồng bộ session: %s", sel)
                                await loc.click(timeout=5000, force=True)
                                await human_sleep(2.0, 3.5)
                                break
            except Exception as e_auth_check:
                logger.debug("Lỗi kiểm tra auth cookies: %s", e_auth_check)

        cur_p = urllib.parse.urlparse(page.url).path.lower()
        if "/business/loginpage" in cur_p or cur_p.startswith("/login"):
            # R1 & R2: TỰ ĐỘNG TÁI XÁC THỰC (AUTO RE-AUTHENTICATION)
            # Khi phiên Facebook thực sự đã hết hạn hoặc nút bắc cầu một chạm bị timeout
            fb_email = os.environ.get("FB_EMAIL", "").strip()
            if (fb_email.startswith('"') and fb_email.endswith('"')) or (
                fb_email.startswith("'") and fb_email.endswith("'")
            ):
                fb_email = fb_email[1:-1].strip()

            fb_password = os.environ.get("FB_PASSWORD", "").strip()
            if (fb_password.startswith('"') and fb_password.endswith('"')) or (
                fb_password.startswith("'") and fb_password.endswith("'")
            ):
                fb_password = fb_password[1:-1].strip()

            if fb_email and fb_password:
                logger.info(
                    "Phiên làm việc Facebook đã hết hạn. Đang kích hoạt cơ chế Auto Re-Authentication an toàn từ biến môi trường..."
                )
                reauth_success = False

                # 1. Kiểm tra nếu ngay trên loginpage có form đăng nhập inline
                try:
                    has_inline_login = await page.locator('input[name="pass"], input[type="password"]').count() > 0
                    if has_inline_login:
                        logger.info("Phát hiện form đăng nhập inline trên loginpage. Đang gửi thông tin đăng nhập an toàn...")
                        inline_ok = await submit_credentials_on_page(page, fb_email, fb_password)
                        if inline_ok:
                            for _ in range(20):
                                await asyncio.sleep(0.5)
                                c_p = urllib.parse.urlparse(page.url).path.lower()
                                if "/business/loginpage" not in c_p and not c_p.startswith("/login") and "checkpoint" not in c_p:
                                    reauth_success = True
                                    break
                                try:
                                    c_list = await page.context.cookies()
                                    if any(c.get("name") == "c_user" and c.get("value") for c in c_list if isinstance(c, dict)):
                                        reauth_success = True
                                        break
                                except Exception:
                                    pass

                            if reauth_success:
                                logger.info("Đăng nhập inline thành công! Đang lưu session mới và chuyển hướng tới Meta Business Suite...")
                                try:
                                    from bot.auth_helper import export_github_secret_file, sync_storage_secret_to_github
                                    os.makedirs(os.path.dirname(STORAGE_STATE_FILE) or STATE_DIR, exist_ok=True)
                                    await page.context.storage_state(path=str(STORAGE_STATE_FILE))
                                    export_github_secret_file(str(STORAGE_STATE_FILE))
                                    sync_storage_secret_to_github()
                                except Exception as e_mid_save:
                                    logger.debug("Lỗi lưu storage_state sau inline login: %s", e_mid_save)

                                if hasattr(page, "goto"):
                                    goto_res = page.goto(META_INBOX_COMMENTS_URL, wait_until="domcontentloaded", timeout=45000)
                                    if asyncio.iscoroutine(goto_res) or hasattr(goto_res, "__await__"):
                                        await goto_res
                                await human_sleep(2.0, 3.5)
                except Exception as e_inline:
                    logger.debug("Lỗi xử lý form inline: %s", e_inline)

                # 2. Nếu chưa thành công, điều hướng trực tiếp sang https://www.facebook.com/login.php
                if not reauth_success:
                    c_p = urllib.parse.urlparse(page.url).path.lower()
                    if "/business/loginpage" in c_p or c_p.startswith("/login"):
                        try:
                            logger.info("Điều hướng sang trang đăng nhập chuẩn https://www.facebook.com/login.php...")
                            if hasattr(page, "goto"):
                                goto_res = page.goto("https://www.facebook.com/login.php", wait_until="domcontentloaded", timeout=30000)
                                if asyncio.iscoroutine(goto_res) or hasattr(goto_res, "__await__"):
                                    await goto_res
                            await human_sleep(1.0, 2.0)
                            fb_login_ok = await submit_credentials_on_page(page, fb_email, fb_password)
                            if fb_login_ok:
                                fb_auth_done = False
                                for _ in range(30):
                                    await asyncio.sleep(0.5)
                                    post_url = page.url.lower()
                                    post_parsed = urllib.parse.urlparse(page.url)
                                    post_p = post_parsed.path.lower()

                                    # a. Màn hình Interstitial "Save browser / Remember device" (Nhớ trình duyệt)
                                    if "save-device" in post_p or "save-device" in post_url or "save_device" in post_url:
                                        logger.info("Phát hiện màn hình lưu trình duyệt (Save browser/device). Đang tự động xác nhận...")
                                        save_btn_sel = (
                                            'button:has-text("Lưu"), div[role="button"]:has-text("Lưu"), '
                                            'button:has-text("Lưu trình duyệt"), div[role="button"]:has-text("Lưu trình duyệt"), '
                                            'button:has-text("Save"), div[role="button"]:has-text("Save"), '
                                            'button:has-text("Save Browser"), div[role="button"]:has-text("Save Browser"), '
                                            'button:has-text("Tiếp tục"), div[role="button"]:has-text("Tiếp tục"), '
                                            'button:has-text("Continue"), div[role="button"]:has-text("Continue"), '
                                            'button:has-text("Không lưu"), div[role="button"]:has-text("Không lưu"), '
                                            'button:has-text("Don\'t Save"), div[role="button"]:has-text("Don\'t Save"), '
                                            'button:has-text("Lúc khác"), div[role="button"]:has-text("Lúc khác"), '
                                            'button:has-text("Not Now"), div[role="button"]:has-text("Not Now"), '
                                            'button[type="submit"], button[name="__CONFIRM__"], button#checkpointSubmitButton'
                                        )
                                        try:
                                            save_loc = page.locator(save_btn_sel).first
                                            if await _safe_eval_count(save_loc) > 0:
                                                await save_loc.click(timeout=4000, force=True)
                                                await asyncio.sleep(1.0)
                                        except Exception as e_sb:
                                            logger.debug("Lỗi bấm nút save-device: %s", e_sb)
                                        fb_auth_done = True
                                        break

                                    # b. Checkpoint / 2FA
                                    if "checkpoint" in post_p or "checkpoint" in post_url:
                                        try:
                                            has_2fa = (
                                                await page.locator('input[name="approvals_code"], input[autocomplete="one-time-code"]').count() > 0
                                                or "two_step_verification" in post_url
                                            )
                                        except Exception:
                                            has_2fa = False
                                        if has_2fa:
                                            logger.warning("Đăng nhập Facebook gặp checkpoint/2FA xác thực tài khoản. Không thể tự động vượt qua.")
                                            return False
                                        cp_btn = page.locator(
                                            'button#checkpointSubmitButton, button[type="submit"]:has-text("Tiếp tục"), '
                                            'button:has-text("Continue"), button:has-text("Tiếp tục")'
                                        ).first
                                        if await _safe_eval_count(cp_btn) > 0:
                                            try:
                                                await cp_btn.click(timeout=4000, force=True)
                                                await asyncio.sleep(1.0)
                                                continue
                                            except Exception:
                                                pass
                                        logger.warning("Đăng nhập Facebook gặp checkpoint/2FA xác thực tài khoản. Không thể tự động vượt qua.")
                                        return False

                                    # c. Lỗi thông tin đăng nhập không hợp lệ
                                    err_sel = (
                                        'div[role="alert"], '
                                        'div:has-text("Mật khẩu bạn đã nhập không chính xác"), '
                                        'div:has-text("The password that you\'ve entered is incorrect"), '
                                        'div:has-text("Sai mật khẩu"), '
                                        'div:has-text("Tài khoản của bạn đã bị vô hiệu hóa"), '
                                        'div:has-text("Your account has been disabled")'
                                    )
                                    try:
                                        if await page.locator(err_sel).count() > 0:
                                            logger.warning("Tái đăng nhập Facebook qua login.php không thành công (sai thông tin đăng nhập hoặc form bị chặn).")
                                            return False
                                    except Exception:
                                        pass

                                    # d. Đã thoát khỏi trang đăng nhập
                                    is_still_login = (
                                        post_p.startswith("/login")
                                        or "login_attempt" in post_url
                                    )
                                    if not is_still_login and "/business/loginpage" not in post_p:
                                        fb_auth_done = True
                                        break

                                    # e. Đã xuất hiện cookie c_user (khi không bị kẹt login_attempt)
                                    if "login_attempt" not in post_url:
                                        try:
                                            c_list = await page.context.cookies()
                                            if any(c.get("name") == "c_user" and c.get("value") for c in c_list if isinstance(c, dict)):
                                                fb_auth_done = True
                                                break
                                        except Exception:
                                            pass

                                if not fb_auth_done:
                                    logger.warning("Tái đăng nhập Facebook qua login.php không thành công (sai thông tin đăng nhập hoặc form bị chặn).")
                                    return False

                                logger.info(
                                    "Đăng nhập Facebook.com thành công! Đang lưu session mới và điều hướng lại về Meta Business Suite: %s",
                                    META_INBOX_COMMENTS_URL,
                                )
                                reauth_success = True
                                try:
                                    from bot.auth_helper import export_github_secret_file, sync_storage_secret_to_github
                                    os.makedirs(os.path.dirname(STORAGE_STATE_FILE) or STATE_DIR, exist_ok=True)
                                    await page.context.storage_state(path=str(STORAGE_STATE_FILE))
                                    export_github_secret_file(str(STORAGE_STATE_FILE))
                                    sync_storage_secret_to_github()
                                except Exception as e_mid_save:
                                    logger.debug("Lỗi lưu storage_state sau facebook.com login: %s", e_mid_save)

                                if hasattr(page, "goto"):
                                    goto_res = page.goto(META_INBOX_COMMENTS_URL, wait_until="domcontentloaded", timeout=45000)
                                    if asyncio.iscoroutine(goto_res) or hasattr(goto_res, "__await__"):
                                        await goto_res
                                await human_sleep(2.0, 4.0)

                                c_p = urllib.parse.urlparse(page.url).path.lower()
                                if "/business/loginpage" in c_p or c_p.startswith("/login"):
                                    for sel in sso_selectors:
                                        loc = page.locator(sel).first
                                        if await _safe_eval_count(loc) > 0 and await _safe_eval_visible(loc):
                                            logger.info("Bấm nút SSO bắc cầu phiên sau khi đã tái đăng nhập: %s", sel)
                                            await loc.click(timeout=5000, force=True)
                                            for _ in range(10):
                                                await asyncio.sleep(0.5)
                                                c_p = urllib.parse.urlparse(page.url).path.lower()
                                                if "/business/loginpage" not in c_p and not c_p.startswith("/login"):
                                                    break
                                            break
                        except Exception as e_reauth:
                            err_str = str(e_reauth)
                            for s in (fb_password, fb_email):
                                if s and s in err_str:
                                    err_str = err_str.replace(s, "[REDACTED]")
                            logger.warning("Lỗi trong quá trình Auto Re-Authentication: %s", err_str)

        cur_p = urllib.parse.urlparse(page.url).path.lower()
        if "/business/loginpage" in cur_p or cur_p.startswith("/login"):
            return False

    # Đánh giá lại trạng thái sau chuyển hướng
    parsed = urllib.parse.urlparse(page.url)
    path = parsed.path.lower()

    if "checkpoint" in path:
        return False
    if "/business/loginpage" in path or path.startswith("/login"):
        return False

    # Kiểm tra xác nhận lần cuối qua sự tồn tại của UI Hộp thư / Thông báo MBS
    for ind in mbs_indicators:
        try:
            if await page.locator(ind).first.count() > 0:
                break
        except Exception:
            pass
    else:
        # Nếu không có bất kỳ chỉ báo MBS nào:
        # 1. Nếu có form đăng nhập: chắc chắn chưa đăng nhập
        if await page.locator('input[name="email"], input[name="pass"], input[type="password"]').count() > 0:
            return False
        # 2. Xóa bỏ điều kiện cứng ngắc "/latest/inbox not in path":
        # Cho phép cả các trang của Meta Business Suite (/latest/notifications, /latest/home, /latest/inbox, /latest/*)
        # đều hợp lệ khi không có form login
        is_valid_mbs_path = (
            path.startswith("/latest/")
            or "/latest/" in path
        )
        if not is_valid_mbs_path:
            return False

    # Lưu cố định toàn bộ cookies (gồm cả business.facebook.com) ngay sau khi xác thực/vào inbox thành công
    try:
        from bot.auth_helper import export_github_secret_file, sync_storage_secret_to_github
        # Bảo toàn origins (localStorage business.facebook.com) hiện có
        preserved_origins = []
        if os.path.exists(STORAGE_STATE_FILE):
            try:
                with open(STORAGE_STATE_FILE, "r", encoding="utf-8") as f_prev:
                    p_data = json.load(f_prev)
                preserved_origins = p_data.get("origins", [])
            except Exception:
                pass

        os.makedirs(os.path.dirname(STORAGE_STATE_FILE) or STATE_DIR, exist_ok=True)
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
        sync_storage_secret_to_github()
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
                    if any(k in txt for k in ["xem", "view"]) and not any(bad in txt for bad in ["ẩn", "hide"]):
                        if not await is_dangerous_hide_button(btn):
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
            return blacklist.some(b => low.includes(b));
        };

        const isBadgeString = (s) => {
            if (!s) return false;
            const low = s.toLowerCase().trim();
            return low === 'tác giả' || low === 'author' ||
                   low === 'tác giả bài viết' || low === 'post author' ||
                   low.startsWith('tác giả ·') || low.startsWith('author ·') ||
                   low.startsWith('tác giả •') || low.startsWith('author •') ||
                   low.startsWith('tác giả -') || low.startsWith('author -');
        };

        // Tìm tất cả articles trong vùng hiển thị chi tiết bài viết (ưu tiên x > 300 nếu là 3 cột, hoặc toàn bộ nếu mở đơn bài)
        let allArticles = Array.from(document.querySelectorAll('[role="article"]'))
            .filter(el => {
                const r = el.getBoundingClientRect();
                return r.height > 15;
            });
        if (allArticles.some(el => el.getBoundingClientRect().left > 300)) {
            allArticles = allArticles.filter(el => el.getBoundingClientRect().left > 300);
        }

        // Lọc bỏ article chứa nhãn online indicator
        const commentArticles = allArticles.filter(art => {
            const aria = (art.getAttribute('aria-label') || '').toLowerCase();
            const text = (art.innerText || '').toLowerCase();
            return !aria.includes('chỉ báo trạng thái online') && !text.includes('chỉ báo trạng thái online');
        });

        const isReplyBtn = (el) => {
            const t = (el.innerText || '').trim().toLowerCase();
            const a = (el.getAttribute('aria-label') || '').trim().toLowerCase();
            const title = (el.getAttribute('title') || '').trim().toLowerCase();
            const combo = (t + ' ' + a + ' ' + title).trim();
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
            const title = (el.getAttribute('title') || '').trim().toLowerCase();
            const combo = (t + ' ' + a + ' ' + title).trim();
            if (combo.includes('ẩn') || combo.includes('hide')) {
                return false;
            }
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

            let hasAuthorBadge = false;

            // Trích xuất tên tác giả
            let authorName = "";
            const mAria = aria.match(/Bình luận dưới tên\s+(.+?)(?:\s+vào\s+|$)/i) ||
                          aria.match(/Comment by\s+(.+?)(?:\s+\d+\s*(?:s|m|h|d|w|y|sec|min|hour|day|week|month|year)s?\s+ago|\s+ago|\s+at|\s+on|$)/i);
            if (mAria && mAria[1]) {
                const rawAuthor = mAria[1].trim();
                if (isBadgeString(rawAuthor)) {
                    hasAuthorBadge = true;
                } else if (!isSystemString(rawAuthor)) {
                    authorName = rawAuthor;
                }
            }

            const lines = inner.split('\n').map(s => s.trim()).filter(Boolean);

            if (!authorName || isSystemString(authorName) || isBadgeString(authorName)) {
                const authorBtns = Array.from(art.querySelectorAll('div[role="button"]:not([aria-label]), a[role="link"], span[dir="auto"]'));
                for (const btn of authorBtns) {
                    if (btn && btn.innerText) {
                        const cand = btn.innerText.trim();
                        if (isBadgeString(cand)) {
                            hasAuthorBadge = true;
                            continue;
                        }
                        if (!isSystemString(cand) && cand.length >= 2 && cand.length <= 50) {
                            authorName = cand;
                            break;
                        }
                    }
                }
            }

            if (!authorName || isSystemString(authorName) || isBadgeString(authorName)) {
                for (const line of lines) {
                    if (isBadgeString(line)) {
                        hasAuthorBadge = true;
                        continue;
                    }
                    if (!isSystemString(line) && line.length >= 2 && line.length <= 50 && !line.includes('tuần') && !line.includes('ngày') && !line.includes('phút') && !line.includes('giờ') && line !== '·') {
                        authorName = line;
                        break;
                    }
                }
            }

            if (isBadgeString(authorName)) {
                hasAuthorBadge = true;
                authorName = "";
            }

            // Nhận diện huy hiệu "Tác giả" / "Author" trên comment article:
            // 1. Loại trừ tên người bình luận và nội dung sau dấu ':' (nếu aria-label chứa cả bình luận khách)
            const ariaHeader = (mAria && mAria[1] ? aria.replace(mAria[1], '') : (authorName ? aria.replace(authorName, '') : aria)).split(':')[0].toLowerCase();
            hasAuthorBadge = hasAuthorBadge ||
                             ariaHeader.includes("tác giả") ||
                             ariaHeader.includes("author") ||
                             lines.some(l => {
                                 if (l === authorName) return false;
                                 return isBadgeString(l);
                             }) ||
                             Boolean(art.querySelector('[aria-label*="tác giả" i]:not([role="article"]), [aria-label*="author" i]:not([role="article"]), [aria-label*="badge" i]:not([role="article"]), [title*="tác giả" i]:not([role="article"]), [title*="author" i]:not([role="article"]), [title*="badge" i]:not([role="article"]), [data-badge]')) ||
                             Boolean(art.querySelector('svg[aria-label*="tác giả" i], svg[aria-label*="author" i], svg[aria-label*="badge" i]'));

            // Kiểm tra xem article này là phản hồi của chính Fanpage hoặc Tác giả:
            // - Khớp tên tác giả (lowAuthor, mAria, authorHeaderLine) với PAGE_NAMES
            // - Hoặc article có huy hiệu Tác giả / Author
            const lowAuthor = (authorName || '').toLowerCase().trim();
            const authorHeaderLine = lines.length > 0 ? lines[0].toLowerCase().trim() : '';
            const secondAuthorHeader = (lines.length > 1 && isBadgeString(authorHeaderLine)) ? lines[1].toLowerCase().trim() : '';

            const isPageNameMatch = (cand) => {
                if (!cand) return false;
                return pageNames.some(p => cand === p || cand.startsWith(p + ' ·') || cand.startsWith(p + ' •') || cand.startsWith(p + ' - ') || cand.startsWith(p + ' – '));
            };

            let isPageReply = hasAuthorBadge ||
                              lowerAria.includes("dưới tên dần86farm") ||
                              lowerAria.includes("dưới tên dan86") ||
                              pageNames.some(p => (mAria && mAria[1] && (mAria[1].toLowerCase().trim() === p || mAria[1].toLowerCase().includes(p))) ||
                                                  (lowAuthor && (lowAuthor === p || lowAuthor.includes(p))) ||
                                                  lowerAria.includes("dưới tên " + p) ||
                                                  lowerAria.includes("comment by " + p)) ||
                              isPageNameMatch(authorHeaderLine) ||
                              isPageNameMatch(secondAuthorHeader);

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
                if (['trả lời', 'reply', 'phản hồi', 'ẩn', 'hide', 'see chat', 'nhắn tin', 'gửi tin nhắn', 'send message', 'thích', 'like', 'bày tỏ cảm xúc', 'theo dõi lại', 'theo dõi', 'tác giả', 'author'].includes(low)) return false;
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
                hasMsgBtn: !!mBtn,
                msgBtnText: mBtn ? ((mBtn.innerText || '').trim() || (mBtn.getAttribute('aria-label') || '').trim()) : "",
                innerPreview: inner.slice(0, 100),
                articleEl: art,
                left: rect.left,
                top: rect.top
            });
        }

        const minLeft = parsedComments.length > 0
            ? Math.min(...parsedComments.map(c => c.left))
            : 0;

        // Đánh giá xem bình luận nào có phản hồi của Page lồng ngay bên dưới
        for (let j = 0; j < parsedComments.length; j++) {
            const item = parsedComments[j];
            if (item.isPageReply) {
                item.hasPageReply = true;
                continue;
            }

            const isItemRoot = item.left <= minLeft + 15;
            let hasReplyBelow = false;

            for (let k = j + 1; k < parsedComments.length; k++) {
                const nextItem = parsedComments[k];
                if (isItemRoot) {
                    // Bình luận gốc cấp 1: nếu nextItem có cùng lề gốc (<= item.left + 15) -> kết thúc nhánh
                    if (nextItem.left <= item.left + 15) {
                        break;
                    }
                    if (nextItem.left > item.left + 15 && nextItem.isPageReply) {
                        hasReplyBelow = true;
                        break;
                    }
                } else {
                    // Bình luận lồng cấp 2+ (nested reply):
                    // Nếu nextItem lùi ra ngoài lề gốc/cấp cha (< item.left - 15) -> kết thúc nhánh
                    if (nextItem.left < item.left - 15) {
                        break;
                    }
                    // Trong cùng nhánh: nếu article tiếp theo là của Page -> đã được phản hồi
                    if (nextItem.isPageReply) {
                        hasReplyBelow = true;
                        break;
                    }
                }
            }
            item.hasPageReply = hasReplyBelow;
        }

        // Lấy danh sách tất cả các bình luận khách MỚI (!c.isOldComment) chưa có Page trả lời HOẶC chưa được gửi tin nhắn riêng
        const unrepliedList = parsedComments.filter(c => {
            if (c.isPageReply || c.isOldComment) return false;
            const pLow = (c.innerPreview || '').toLowerCase();
            const hasTextAction = pLow.includes('trả lời') || pLow.includes('reply') || pLow.includes('phản hồi') || pLow.includes('gửi tin nhắn') || pLow.includes('nhắn tin') || pLow.includes('see chat');
            if (!c.hasReplyBtn && !c.hasMsgBtn && !hasTextAction) return false;
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
                const clickCombo = ((clickNode.innerText || '') + ' ' + (clickNode.getAttribute('aria-label') || '') + ' ' + (clickNode.getAttribute('title') || '')).toLowerCase();
                const rCombo = ((rBtn.innerText || '') + ' ' + (rBtn.getAttribute('aria-label') || '') + ' ' + (rBtn.getAttribute('title') || '')).toLowerCase();
                if (!clickCombo.includes('ẩn') && !clickCombo.includes('hide') && !rCombo.includes('ẩn') && !rCombo.includes('hide')) {
                    if (!clickCombo.includes('xem') && !clickCombo.includes('view')) {
                        clickNode.setAttribute('data-dan86-reply-btn', 'true');
                    } else if (!rCombo.includes('xem') && !rCombo.includes('view')) {
                        rBtn.setAttribute('data-dan86-reply-btn', 'true');
                    }
                }
            }
            const mBtn = candidateEls.find(isMsgBtn);
            if (mBtn) {
                const msgNode = mBtn.closest('button, [role="button"], a') || mBtn;
                const mCombo = ((msgNode.innerText || '') + ' ' + (msgNode.getAttribute('aria-label') || '') + ' ' + (msgNode.getAttribute('title') || '')).toLowerCase();
                if (!mCombo.includes('ẩn') && !mCombo.includes('hide')) {
                    msgNode.setAttribute('data-dan86-msg-btn', 'true');
                }
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
        let allArticles = Array.from(document.querySelectorAll('[role="article"]'))
            .filter(el => {
                const r = el.getBoundingClientRect();
                return r.height > 15;
            });
        if (allArticles.some(el => el.getBoundingClientRect().left > 300)) {
            allArticles = allArticles.filter(el => el.getBoundingClientRect().left > 300);
        }

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
            const title = (el.getAttribute('title') || '').trim().toLowerCase();
            const combo = (t + ' ' + a + ' ' + title).trim();
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
            const title = (el.getAttribute('title') || '').trim().toLowerCase();
            const combo = (t + ' ' + a + ' ' + title).trim();
            if (combo.includes('ẩn') || combo.includes('hide')) {
                return false;
            }
            return combo.includes('see chat') || combo.includes('gửi tin nhắn') ||
                   combo.includes('nhắn tin') || combo.includes('send message') ||
                   combo.includes('tin nhắn') || combo.includes('message') || combo.includes('chat');
        };

        const candidateEls = Array.from(target.querySelectorAll('button, [role="button"], a[role="link"], a, [role="tab"], span, div'));
        const rBtn = candidateEls.find(isReplyBtn);
        if (rBtn) {
            const clickNode = rBtn.closest('button, [role="button"], a') || rBtn;
            const clickCombo = ((clickNode.innerText || '') + ' ' + (clickNode.getAttribute('aria-label') || '') + ' ' + (clickNode.getAttribute('title') || '')).toLowerCase();
            const rCombo = ((rBtn.innerText || '') + ' ' + (rBtn.getAttribute('aria-label') || '') + ' ' + (rBtn.getAttribute('title') || '')).toLowerCase();
            if (!clickCombo.includes('ẩn') && !clickCombo.includes('hide') && !rCombo.includes('ẩn') && !rCombo.includes('hide')) {
                if (!clickCombo.includes('xem') && !clickCombo.includes('view')) {
                    clickNode.setAttribute('data-dan86-reply-btn', 'true');
                } else if (!rCombo.includes('xem') && !rCombo.includes('view')) {
                    rBtn.setAttribute('data-dan86-reply-btn', 'true');
                }
            }
        }

        const mBtn = candidateEls.find(isMsgBtn);
        if (mBtn) {
            const msgNode = mBtn.closest('button, [role="button"], a') || mBtn;
            const mCombo = ((msgNode.innerText || '') + ' ' + (msgNode.getAttribute('aria-label') || '') + ' ' + (msgNode.getAttribute('title') || '')).toLowerCase();
            if (!mCombo.includes('ẩn') && !mCombo.includes('hide')) {
                msgNode.setAttribute('data-dan86-msg-btn', 'true');
            }
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
    """Tự động đóng các popup modal / upsell / banner quảng cáo che khuất giao diện (chỉ đóng bên trong dialog đang hiển thị, tuyệt đối không bấm nút trên trang chính và không đóng dialog soạn tin nhắn riêng)."""
    try:
        dialogs = page.locator('div[role="dialog"]')
        cnt = await dialogs.count()
        for i in range(cnt):
            dlg = dialogs.nth(i)
            if await dlg.is_visible():
                # SAFETY CHECK: Tuyệt đối không đóng dialog nếu đó là popup soạn tin nhắn riêng!
                composer = dlg.locator('div[role="textbox"], textarea').first
                if await composer.count() > 0 and await composer.is_visible():
                    aria = (await composer.get_attribute("aria-label") or "").lower()
                    holder = (await composer.get_attribute("placeholder") or "").lower()
                    if any(k in aria or k in holder for k in ["tin nhắn", "message", "chat"]):
                        continue

                close_btn = dlg.locator(
                    '[aria-label*="Đóng"], [aria-label*="Close"], '
                    '[aria-label*="Dismiss"], [aria-label*="Bỏ qua"], '
                    'button:has-text("Đóng"), button:has-text("Close"), '
                    'div[role="button"]:has-text("Đóng"), div[role="button"]:has-text("Close"), '
                    'button:has-text("Không phải bây giờ"), button:has-text("Not now"), '
                    'button:has-text("Để sau"), button:has-text("Lúc khác"), '
                    'div[role="button"]:has-text("Không phải bây giờ"), div[role="button"]:has-text("Not now"), '
                    'div[role="button"]:has-text("Để sau"), div[role="button"]:has-text("Lúc khác")'
                ).first
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

    # 1. Thử click nút tin nhắn đã được gán data-dan86-msg-btn bằng tọa độ vật lý
    marked_msg_btn = page.locator('[data-dan86-msg-btn="true"]').first
    if await marked_msg_btn.count() > 0 and await marked_msg_btn.is_visible():
        try:
            btn_text_lower = (await marked_msg_btn.inner_text() or "").lower()
            clicked_btn = await click_element_at_physical_coordinates(page, marked_msg_btn, timeout_ms=2500)
            if not clicked_btn:
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
            let articles = Array.from(document.querySelectorAll('[role="article"]'))
                .filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.height > 15;
                });
            if (articles.some(el => el.getBoundingClientRect().left > 300)) {
                articles = articles.filter(el => el.getBoundingClientRect().left > 300);
            }

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
                const title = (el.getAttribute('title') || '').trim().toLowerCase();
                const combo = (t + ' ' + a + ' ' + title).trim();
                if (combo.includes('ẩn') || combo.includes('hide')) {
                    return false;
                }
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
                const nodeCombo = ((clickNode.innerText || '') + ' ' + (clickNode.getAttribute('aria-label') || '') + ' ' + (clickNode.getAttribute('title') || '')).toLowerCase();
                if (nodeCombo.includes('ẩn') || nodeCombo.includes('hide')) {
                    return { clicked: false, tagged: false, text: '' };
                }
                clickNode.scrollIntoView();
                clickNode.setAttribute('data-dan86-msg-btn', 'true');
                const r = clickNode.getBoundingClientRect();
                const foundText = (btn.innerText || btn.getAttribute('aria-label') || '').trim();
                return {
                    clicked: false,
                    tagged: true,
                    text: foundText,
                    coords: {
                        x: r.x !== undefined ? r.x : r.left,
                        y: r.y !== undefined ? r.y : r.top,
                        width: r.width,
                        height: r.height
                    }
                };
            }
            return { clicked: false, tagged: false, text: '' };
        }
        """
        try:
            res_click = await page.evaluate(js_click_msg, {"targetIdx": dom_index, "targetAuthor": author_name})
            if res_click.get("tagged"):
                btn_text_lower = res_click.get("text", "").lower()
                re_marked_btn = page.locator('[data-dan86-msg-btn="true"]').first
                if await re_marked_btn.count() > 0:
                    clicked_btn = await click_element_at_physical_coordinates(page, re_marked_btn, timeout_ms=2500)
                if not clicked_btn:
                    c_info = res_click.get("coords")
                    if c_info and c_info.get("width", 0) > 0 and c_info.get("height", 0) > 0:
                        cx = c_info["x"] + c_info["width"] / 2.0
                        cy = c_info["y"] + c_info["height"] / 2.0
                        clicked_btn = await physical_mouse_click(page, cx, cy)
                if not clicked_btn and await re_marked_btn.count() > 0:
                    await safe_click(re_marked_btn, timeout=2500)
                    clicked_btn = True
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
                    # Xóa sạch mọi văn bản mặc định / template cũ của Facebook trong ô nhập (nếu có)
                    try:
                        await dialog_box.click()
                        await page.keyboard.press("Control+A")
                        await page.keyboard.press("Backspace")
                        await human_sleep(0.2, 0.4)
                    except Exception:
                        pass
                    await type_human_like(page, dialog_box, private_reply_text)
                    send_btn = dialog.locator(
                        '[aria-label*="Gửi"], [aria-label*="Send"], '
                        'div[role="button"]:has-text("Gửi"), div[role="button"]:has-text("Send"), '
                        'button:has-text("Gửi"), button:has-text("Send")'
                    ).last
                    if await send_btn.count() > 0 and await send_btn.is_visible():
                        clicked_send = await click_element_at_physical_coordinates(page, send_btn, timeout_ms=2500)
                        if not clicked_send:
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
            if "bình luận công khai" in combo and not any(
                k in combo for k in ["trả lời", "câu trả lời", "phản hồi", "reply"]
            ):
                logger.debug("Bỏ qua ô nhập vì là ô bình luận bài viết cấp 1: %s", combo)
                return False

            return True
        except Exception:
            return False

    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        # Ưu tiên 1: Element đang :focus (document.activeElement) có quan hệ hình học sát target_art
        # Khi click Trả lời, Facebook tự động focus vào ô nhập vừa bung ra
        focused_el = page.locator('div[role="textbox"]:focus, div[contenteditable="true"]:focus, :focus').first
        if await is_valid_nested_candidate(focused_el):
            logger.info("Tìm thấy ô nested reply lồng nhau (Ưu tiên 1: :focus activeElement).")
            return focused_el

        # Ưu tiên 2: Ô textbox nằm ngay sau target_art (following XPath 1 & 2)
        following_box = target_art.locator('xpath=following::div[@role="textbox"][1]').first
        if await is_valid_nested_candidate(following_box):
            logger.info("Tìm thấy ô nested reply lồng nhau (Ưu tiên 2: following role=textbox).")
            return following_box

        following_edit = target_art.locator('xpath=following::div[@contenteditable="true"][1]').first
        if await is_valid_nested_candidate(following_edit):
            logger.info("Tìm thấy ô nested reply lồng nhau (Ưu tiên 2: following contenteditable).")
            return following_edit

        following_box2 = target_art.locator('xpath=following::div[@role="textbox" or @contenteditable="true"][2]').first
        if await is_valid_nested_candidate(following_box2):
            logger.info("Tìm thấy ô nested reply lồng nhau (Ưu tiên 2: following #2).")
            return following_box2

        # Ưu tiên 3: Ô textbox nằm ngay bên trong target_art
        inside_box = target_art.locator('div[role="textbox"], div[contenteditable="true"]').first
        if await is_valid_nested_candidate(inside_box):
            logger.info("Tìm thấy ô nested reply lồng nhau (Ưu tiên 3: inside target_art).")
            return inside_box

        # Ưu tiên 4: Quét các textbox đang hiển thị nằm trong phạm vi hình học gần target_art
        near_boxes = page.locator('div[role="textbox"], div[contenteditable="true"]')
        near_count = min(await near_boxes.count(), 30)
        for nb_idx in range(near_count):
            cand_nb = near_boxes.nth(nb_idx)
            if await is_valid_nested_candidate(cand_nb):
                logger.info("Tìm thấy ô nested reply lồng nhau (Ưu tiên 4: near geometric match #%d).", nb_idx)
                return cand_nb

        await asyncio.sleep(0.3)

    return None


async def inspect_notifications_list(page: Page) -> List[Dict[str, Any]]:
    """
    Phân tích trang Thông báo Meta Business Suite:
    - Tìm tất cả các mục thông báo liên quan đến bình luận.
    - Đánh dấu data-dan86-notif-idx lên các phần tử để dễ dàng định vị.
    - Trích xuất text và tọa độ DOM thực tế (getBoundingClientRect).
    """
    js_code = """
    () => {
        document.querySelectorAll('[data-dan86-notif-idx]').forEach(e => e.removeAttribute('data-dan86-notif-idx'));

        const selectors = [
            'div[role="listitem"]',
            'div[role="row"]',
            'div[role="article"]',
            'div[role="button"]',
            'a[role="link"]',
            'div._a6ag._a6ah'
        ];
        const allCandidates = Array.from(document.querySelectorAll(selectors.join(', ')));

        const results = [];
        const seenTexts = new Set();

        for (const el of allCandidates) {
            const text = (el.innerText || '').trim();
            if (!text || text.length < 10) continue;

            const lower = text.toLowerCase();
            const hasCommentKw = lower.includes('đã bình luận') ||
                                 lower.includes('commented') ||
                                 lower.includes('đã phản hồi') ||
                                 lower.includes('replied') ||
                                 lower.includes('đã trả lời') ||
                                 lower.includes('bình luận về') ||
                                 lower.includes('phản hồi về') ||
                                 lower.includes('bình luận của') ||
                                 lower.includes('đã nhắc đến') ||
                                 lower.includes('mentioned') ||
                                 lower.includes('đã gắn thẻ') ||
                                 lower.includes('gắn thẻ') ||
                                 lower.includes('tagged') ||
                                 lower.includes('nhắc đến bạn') ||
                                 lower.includes('nhắc đến trang');
            if (!hasCommentKw) continue;

            const r = el.getBoundingClientRect();
            // Thẻ thông báo độc lập có kích thước pixel rõ ràng, tránh bắt nhầm toàn bộ container/feed
            if (r.width < 100 || r.height < 25 || r.height > 250) continue;

            // Bỏ qua nếu phần tử này là container bao bọc một candidate thẻ con khác cũng là thẻ thông báo bình luận
            const containsOtherCard = allCandidates.some(c => {
                if (c === el || !el.contains(c)) return false;
                const cText = (c.innerText || '').toLowerCase().trim();
                const cHasKw = cText.includes('đã bình luận') || cText.includes('commented') ||
                               cText.includes('đã phản hồi') || cText.includes('replied') ||
                               cText.includes('đã trả lời') || cText.includes('bình luận về') ||
                               cText.includes('phản hồi về') || cText.includes('bình luận của') ||
                               cText.includes('đã nhắc đến') || cText.includes('mentioned') ||
                               cText.includes('đã gắn thẻ') || cText.includes('gắn thẻ') || cText.includes('tagged');
                if (!cHasKw) return false;
                const cr = c.getBoundingClientRect();
                return cr.width >= 100 && cr.height >= 25 && cr.height <= 250;
            });
            if (containsOtherCard) continue;

            const keyText = text.slice(0, 120);
            if (seenTexts.has(keyText)) continue;

            seenTexts.add(keyText);
            const idx = results.length;
            el.setAttribute('data-dan86-notif-idx', String(idx));

            results.push({
                index: idx,
                element: el,
                text: text,
                coords: {
                    x: r.x !== undefined ? r.x : r.left,
                    y: r.y !== undefined ? r.y : r.top,
                    width: r.width,
                    height: r.height,
                    left: r.left,
                    top: r.top,
                    right: r.right,
                    bottom: r.bottom
                }
            });
        }

        return results.map(r => ({
            index: r.index,
            text: r.text,
            coords: r.coords
        }));
    }
    """
    try:
        raw_list = await page.evaluate(js_code)
        if isinstance(raw_list, list):
            return raw_list
    except Exception as e:
        logger.debug("Lỗi inspect_notifications_list: %s", e)
    return []


async def process_post_comments_by_coordinates(
    page: Page,
    memory: BotMemoryStore,
    current_post_url: str = "",
    dry_run: bool = False,
    target_author_filter: Optional[str] = None,
    max_comments: int = 10,
) -> int:
    """
    Xử lý tất cả bình luận trên bài viết đang mở bằng Động cơ Tọa độ DOM F12 Vật lý:
    1. Đổi bộ lọc sang 'Mới nhất' (ensure_newest_comments_filter).
    2. Lặp mở rộng phản hồi ẩn (expand_all_comment_replies).
    3. Phân tích panel bình luận (inspect_comment_panel).
    4. Thả Like bình luận bằng click vật lý.
    5. Click nút Trả lời bằng tọa độ chuột vật lý (page.mouse.click).
    6. Chờ ô nested reply bung ra trong phạm vi hình học (box_y < comment_bottom + 250).
    7. Click chuột vật lý vào ô nested reply -> gõ public_reply -> Enter.
    8. Fail-safe guard: Nếu không tìm thấy ô nested reply, HỦY BỎ cmt công khai để chống văng ra ngoài bài viết.
    9. Click nút 'Gửi tin nhắn' bằng tọa độ chuột vật lý để gửi Private Inbox.
    10. Ghi nhận memory.
    """
    replied_count = 0
    await ensure_newest_comments_filter(page)

    post_comment_cycle = 0
    while post_comment_cycle < max_comments:
        post_comment_cycle += 1

        await expand_all_comment_replies(page)

        info = await inspect_comment_panel(page)
        post_id = info.get("post_id") or ""
        unreplied_candidates = info.get("unreplied_comments", [])

        if not unreplied_candidates:
            logger.debug("Bài viết này không còn bình luận nào cần trả lời.")
            break

        target_candidate = None
        target_key = None
        needs_inbox_only = False

        for cand in unreplied_candidates:
            cand_author = cand.get("author_name") or "bạn"
            cand_text = cand.get("comment_text") or ""
            cand_idx = int(cand.get("dom_index", 0))
            cand_has_reply = bool(cand.get("has_page_reply", False))

            if is_page_author_name(cand_author):
                continue

            # BỎ QUA 100% nếu bình luận cũ (tuần, tháng, năm hoặc > 3 ngày)
            if cand.get("is_old_comment") or is_old_comment_timestamp(cand.get("time_str", "")):
                logger.info(
                    "Bình luận cũ từ [%s] (Thời gian: '%s'). BỎ QUA 100%!",
                    cand_author,
                    cand.get("time_str", "") or cand.get("innerPreview", "")[:30],
                )
                continue

            # Chế độ thử nghiệm an toàn (nếu có cấu hình whitelist):
            if TEST_ONLY_AUTHOR_WHITELIST:
                c_norm = normalize_text(cand_author)
                if not any(normalize_text(w) in c_norm for w in TEST_ONLY_AUTHOR_WHITELIST):
                    logger.info(
                        "Chế độ thử nghiệm: Bỏ qua khách [%s] (Không nằm trong TEST_ONLY_AUTHOR_WHITELIST).",
                        cand_author,
                    )
                    continue

            # Lọc chính xác theo tác giả mục tiêu từ thông báo nếu có chỉ định
            if target_author_filter and target_author_filter != "bạn":
                t_norm = normalize_text(target_author_filter)
                c_norm = normalize_text(cand_author)
                t_words = set(t_norm.split())
                c_words = set(c_norm.split())
                is_target_match = (
                    t_norm in c_norm
                    or c_norm in t_norm
                    or (bool(t_words) and bool(c_words) and t_words == c_words)
                )
                if not is_target_match:
                    logger.debug(
                        "Bỏ qua bình luận từ [%s] vì không khớp tác giả thông báo mục tiêu [%s].",
                        cand_author,
                        target_author_filter,
                    )
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

            if should_rep:
                target_candidate = cand
                target_key = comment_key
                needs_inbox_only = False
                break

            # Nếu trong memory ĐÃ TỒN TẠI bản ghi nhưng chưa gửi inbox thành công:
            if comment_key:
                existing_rec = memory.get_comment_record(
                    comment_key=comment_key,
                    author_name=cand_author,
                    comment_text=cand_text,
                    post_id=post_id,
                )
                if existing_rec and not existing_rec.get("private_inbox_sent"):
                    if existing_rec.get("inbox_attempts", 0) < 2:
                        target_candidate = cand
                        target_key = comment_key
                        needs_inbox_only = True
                        break

        if target_candidate is None:
            logger.debug("Tất cả bình luận chưa rep trên bài viết này đã được xử lý trong memory hoặc không hợp lệ.")
            break

        cand_author = clean_customer_name(target_candidate.get("author_name") or "bạn")
        cand_text = clean_comment_text(target_candidate.get("comment_text") or "")
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
            inbox_sent = await send_private_inbox_to_commenter(
                page=page,
                post_url=current_post_url or page.url,
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
            if current_post_url and page.url != current_post_url:
                try:
                    await page.goto(current_post_url, wait_until="domcontentloaded", timeout=45000)
                    await human_sleep(2.0, 3.5)
                except Exception:
                    pass
            await human_sleep(ACTION_COOLDOWN_SECONDS[0], ACTION_COOLDOWN_SECONDS[1])
            continue

        # Bước 1: Thả Like bình luận của khách bằng click vật lý
        if target_art is not None:
            try:
                like_btn = target_art.locator('div[role="button"]:has-text("Thích"), div[role="button"]:has-text("Like")').first
                cnt = like_btn.count()
                if asyncio.iscoroutine(cnt) or hasattr(cnt, "__await__"):
                    cnt = await cnt
                if cnt > 0:
                    vis = like_btn.is_visible()
                    if asyncio.iscoroutine(vis) or hasattr(vis, "__await__"):
                        vis = await vis
                    if vis:
                        await click_element_at_physical_coordinates(page, like_btn, timeout_ms=2000)
                        await human_sleep(0.8, 1.5)
            except Exception:
                pass

        # Bước 2: Bấm chính xác nút "Trả lời" / "Phản hồi" (Reply) bằng TỌA ĐỘ VẬT LÝ F12
        reply_clicked = False
        try:
            marked_reply_btn = page.locator('[data-dan86-reply-btn="true"]').first
            rcnt = marked_reply_btn.count()
            if asyncio.iscoroutine(rcnt) or hasattr(rcnt, "__await__"):
                rcnt = await rcnt
            if rcnt > 0:
                rvis = marked_reply_btn.is_visible()
                if asyncio.iscoroutine(rvis) or hasattr(rvis, "__await__"):
                    rvis = await rvis
                if rvis:
                    reply_clicked = await click_element_at_physical_coordinates(page, marked_reply_btn, timeout_ms=2500)
        except Exception as e_reply:
            logger.debug("Lỗi bấm nút Trả lời đánh dấu: %s", e_reply)

        if not reply_clicked and target_art is not None:
            cand_buttons = target_art.locator('div[role="button"], button, a, span')
            b_count = min(await cand_buttons.count(), 20)
            for b_idx in range(b_count):
                b_el = cand_buttons.nth(b_idx)
                if not await b_el.is_visible():
                    continue
                b_text = (await b_el.inner_text() or "").strip().lower()
                b_aria = (await b_el.get_attribute("aria-label") or "").strip().lower()
                b_title = (await b_el.get_attribute("title") or "").strip().lower()
                b_combo = f"{b_text} {b_aria} {b_title}"
                if any(bad in b_combo for bad in ["xem", "ẩn", "view", "hide"]):
                    continue
                if await is_dangerous_hide_button(b_el):
                    continue
                if (
                    b_text in ["trả lời", "reply", "phản hồi"]
                    or b_aria in ["trả lời", "reply", "phản hồi"]
                    or b_aria.startswith("trả lời")
                    or "trả lời bình luận" in b_aria
                    or "reply to comment" in b_aria
                ):
                    try:
                        reply_clicked = await click_element_at_physical_coordinates(page, b_el, timeout_ms=2500)
                        if reply_clicked:
                            logger.info("Đã bấm nút Trả lời trong comment article bằng tọa độ vật lý.")
                            break
                    except Exception as e_b:
                        logger.debug("Lỗi bấm nút Trả lời dự phòng: %s", e_b)

        # Chờ 1.2 - 2.0 giây để DOM chèn ô nhập phản hồi lồng nhau
        if reply_clicked:
            await human_sleep(1.2, 2.0)
        else:
            await human_sleep(0.8, 1.2)

        # Định vị ô nhập phản hồi lồng nhau cấp 2 độc quyền cho target_art (ràng buộc box_y < comment_bottom + 250)
        nested_box = await locate_nested_reply_box(page, target_art, timeout_seconds=2.5)

        # Fail-safe guard: Nếu KHÔNG tìm thấy ô reply lồng nhau hợp lệ, HỦY BỎ cmt công khai
        if nested_box is None:
            logger.warning(
                "Không tìm thấy ô nested reply lồng nhau hợp lệ gần bình luận của [%s], hủy cmt để chống đăng nhầm ra ngoài bài viết!",
                cand_author,
            )
            inbox_sent = await send_private_inbox_to_commenter(
                page=page,
                post_url=current_post_url or page.url,
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
            if current_post_url and page.url != current_post_url:
                try:
                    await page.goto(current_post_url, wait_until="domcontentloaded", timeout=45000)
                    await human_sleep(2.0, 3.5)
                except Exception:
                    pass
            await human_sleep(ACTION_COOLDOWN_SECONDS[0], ACTION_COOLDOWN_SECONDS[1])
            continue

        # Whitelist re-check trước khi gửi cmt công khai
        if TEST_ONLY_AUTHOR_WHITELIST:
            c_norm = normalize_text(cand_author)
            if not any(normalize_text(w) in c_norm for w in TEST_ONLY_AUTHOR_WHITELIST):
                logger.info(
                    "Chế độ thử nghiệm: Bỏ qua gửi cmt công khai cho [%s] (Không nằm trong TEST_ONLY_AUTHOR_WHITELIST).",
                    cand_author,
                )
                continue

        # Lấy tọa độ vật lý của nested_box và click chuột vật lý
        box_coords = await get_element_coordinates(nested_box)
        if box_coords:
            bcx = box_coords["x"] + box_coords["width"] / 2.0
            bcy = box_coords["y"] + box_coords["height"] / 2.0
            await physical_mouse_click(page, bcx, bcy)
            await human_sleep(0.3, 0.6)

        await type_human_like(page, nested_box, public_reply)
        await page.keyboard.press("Enter")
        await human_sleep(2.5, 4.0)
        logger.info("Đã gửi phản hồi bình luận công khai cho [%s] (Nested Reply: True, Coordinate Engine: True).", cand_author)

        # Bước 3: Gửi tin nhắn riêng (Private Inbox) cho người vừa bình luận
        inbox_sent = await send_private_inbox_to_commenter(
            page=page,
            post_url=current_post_url or page.url,
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
            public_reply=public_reply,
            private_inbox_sent=inbox_sent,
            private_reply_text=private_inbox_reply,
            post_id=post_id,
            dom_index=cand_idx,
        )
        replied_count += 1

        if current_post_url and page.url != current_post_url:
            try:
                await page.goto(current_post_url, wait_until="domcontentloaded", timeout=45000)
                await human_sleep(2.0, 3.5)
            except Exception:
                pass

        await human_sleep(ACTION_COOLDOWN_SECONDS[0], ACTION_COOLDOWN_SECONDS[1])

    return replied_count


async def process_facebook_notifications_tab(
    page: Page,
    memory: BotMemoryStore,
    dry_run: bool = False,
) -> int:
    """
    Quét Trang Thông báo Fanpage (Facebook Notifications):
    URL: https://business.facebook.com/latest/notifications?asset_id=104011958817512

    Bao phủ TOÀN BỘ bài viết (không bị giới hạn bởi 10-20 bài gần nhất):
    1. Lọc thông báo mới có từ khóa bình luận ('đã bình luận', 'commented', 'đã phản hồi', 'replied').
    2. Trích xuất tên tác giả và thời gian tương đối ('vừa xong', '1 phút', 'vài giây').
    3. Lọc bỏ thông báo cũ (> 3 ngày, tuần, tháng, năm).
    4. Kiểm tra Whitelist (nếu TEST_ONLY_AUTHOR_WHITELIST được cấu hình).
    5. Kiểm tra memory (chưa có trong replied_comments và không trong cooldown).
    6. Click chuột vật lý vào thông báo để Facebook mở chi tiết bài viết và cuộn tới đúng comment.
    7. Sử dụng Coordinate-based DOM Engine để phản hồi cmt lồng nhau và gửi tin nhắn riêng.
    8. Quay lại trang thông báo để tiếp tục.
    """
    replied_count = 0
    logger.info("Đang kiểm tra Trang Thông báo Facebook: %s", META_NOTIFICATIONS_URL)
    try:
        await page.goto(META_NOTIFICATIONS_URL, wait_until="domcontentloaded", timeout=45000)
        await human_sleep(3.5, 5.0)
    except Exception as e_nav:
        logger.warning("Không thể điều hướng tới Trang Thông báo: %s", e_nav)
        return 0

    if not await verify_logged_in(page):
        logger.warning("Phiên đăng nhập Facebook chưa sẵn sàng trên trang Thông báo! Đang hồi phục về trang Hộp thư...")
        try:
            await page.goto(META_INBOX_COMMENTS_URL, wait_until="domcontentloaded", timeout=30000)
            await human_sleep(2.0, 3.5)
        except Exception:
            pass
        return 0

    await dismiss_blocking_modals(page)

    notifs = await inspect_notifications_list(page)
    logger.info("Tìm thấy %d thông báo có chứa từ khóa bình luận trên trang Thông báo.", len(notifs))

    for notif in notifs:
        try:
            notif_idx = notif.get("index", 0)
            notif_text = notif.get("text", "")
            parsed = parse_notification_text(notif_text)

            if not parsed.get("is_comment_notif"):
                continue

            author = parsed.get("author_name", "bạn")
            time_str = parsed.get("time_str", "")
            snippet = parsed.get("comment_snippet", "")
            is_old = parsed.get("is_old", False)

            if is_old or is_old_comment_timestamp(time_str):
                logger.info("Bỏ qua thông báo cũ từ [%s] (Thời gian: '%s').", author, time_str)
                continue

            # Whitelist filter (nếu có cấu hình)
            if TEST_ONLY_AUTHOR_WHITELIST:
                c_norm = normalize_text(author)
                if not any(normalize_text(w) in c_norm for w in TEST_ONLY_AUTHOR_WHITELIST):
                    logger.info("Chế độ thử nghiệm: Bỏ qua thông báo từ [%s] (Không nằm trong TEST_ONLY_AUTHOR_WHITELIST).", author)
                    continue

            # Memory cooldown check (chỉ áp dụng khi có snippet để tránh chặn oan thông báo bài viết khác khi chưa rõ nội dung)
            if snippet and memory.is_customer_in_cooldown(
                author,
                cooldown_seconds=CUSTOMER_ANTI_SPAM_COOLDOWN_SECONDS,
                comment_text=snippet,
            ):
                logger.info("Khách hàng [%s] đang trong cooldown chống spam. Bỏ qua thông báo!", author)
                continue

            # Kiểm tra xem comment đã được xử lý hoàn tất chưa
            rec = memory.get_comment_record(author_name=author, comment_text=snippet)
            if rec and rec.get("public_reply") and rec.get("private_inbox_sent"):
                p_rep = str(rec.get("public_reply", ""))
                if not p_rep.startswith("(Bỏ qua"):
                    logger.info("Bình luận từ thông báo của [%s] đã được trả lời & inbox trong memory. Bỏ qua!", author)
                    continue

            logger.info("Phát hiện thông báo bình luận MỚI từ [%s] ('%s' - %s). Đang nhấp mở chi tiết bài viết...", author, snippet[:40], time_str)

            if dry_run:
                pub_rep, priv_rep = memory.prepare_comment_and_inbox_replies(author)
                logger.info("[DRY-RUN] Thông báo từ [%s] -> Sẽ rep cmt: %s", author, pub_rep)
                logger.info("[DRY-RUN] Sẽ gửi tin nhắn riêng: %s", priv_rep[:80])
                replied_count += 1
                continue

            # Click vật lý vào thông báo theo tọa độ DOM
            clicked_notif = False
            # Ưu tiên 1: Cuộn tới phần tử và click vật lý vào tọa độ DOM thực tế hiện tại
            try:
                notif_loc = page.locator(f'[data-dan86-notif-idx="{notif_idx}"]').first
                cnt = notif_loc.count()
                if asyncio.iscoroutine(cnt) or hasattr(cnt, "__await__"):
                    cnt = await cnt

                # Kiểm tra xem thẻ này có thực sự thuộc về author không (tránh lệch index sau khi reload)
                is_correct_author = True
                if cnt > 0 and author and author != "bạn":
                    try:
                        card_txt = (await notif_loc.inner_text() or "").lower()
                        is_correct_author = author.lower() in card_txt
                    except Exception:
                        pass

                if cnt == 0 or not is_correct_author:
                    # Nếu trang vừa được điều hướng/tải lại khiến attribute bị xóa hoặc đổi thứ tự:
                    await inspect_notifications_list(page)
                    # Ưu tiên tìm thẻ có chứa đúng tên tác giả mục tiêu
                    if author and author != "bạn":
                        author_card = page.locator(f'[data-dan86-notif-idx]:has-text("{author}")').first
                        ac_cnt = author_card.count()
                        if asyncio.iscoroutine(ac_cnt) or hasattr(ac_cnt, "__await__"):
                            ac_cnt = await ac_cnt
                        if ac_cnt > 0:
                            notif_loc = author_card
                            cnt = ac_cnt
                            is_correct_author = True
                    if cnt == 0:
                        notif_loc = page.locator(f'[data-dan86-notif-idx="{notif_idx}"]').first
                        cnt = notif_loc.count()
                        if asyncio.iscoroutine(cnt) or hasattr(cnt, "__await__"):
                            cnt = await cnt

                if cnt > 0:
                    clicked_notif = await click_element_at_physical_coordinates(page, notif_loc, timeout_ms=3000)
            except Exception as e_loc:
                logger.debug("Lỗi click locator thông báo bằng tọa độ vật lý: %s", e_loc)

            # Ưu tiên 2: Fallback click trực tiếp vào tọa độ đã trích xuất trước đó
            if not clicked_notif:
                coords = notif.get("coords")
                if coords and coords.get("width", 0) > 0 and coords.get("height", 0) > 0:
                    cx = coords["x"] + coords["width"] / 2.0
                    cy = coords["y"] + coords["height"] / 2.0
                    clicked_notif = await physical_mouse_click(page, cx, cy)

            if not clicked_notif:
                logger.warning("Không thể click vào thông báo của [%s].", author)
                continue

            # Chờ Facebook điều hướng tới bài viết và cuộn tới đúng comment
            await human_sleep(4.0, 6.0)
            await dismiss_blocking_modals(page)

            # Kiểm tra xem Facebook có mở tab/cửa sổ mới hay không (target="_blank")
            context = getattr(page, "context", None)
            target_page = page
            opened_new_page = False
            if context and hasattr(context, "pages") and len(context.pages) > 1:
                target_page = context.pages[-1]
                opened_new_page = True
                try:
                    await target_page.bring_to_front()
                    await human_sleep(1.5, 3.0)
                    await dismiss_blocking_modals(target_page)
                except Exception:
                    pass

            # Xử lý bình luận bài viết vừa mở
            post_url = target_page.url
            rep_done = await process_post_comments_by_coordinates(
                page=target_page,
                memory=memory,
                current_post_url=post_url,
                dry_run=dry_run,
                target_author_filter=author,
                max_comments=5,
            )
            replied_count += rep_done

            if opened_new_page:
                try:
                    await target_page.close()
                except Exception:
                    pass
                try:
                    await page.bring_to_front()
                except Exception:
                    pass
            elif page.url != META_NOTIFICATIONS_URL:
                # Quay lại trang Thông báo để tiếp tục quét
                try:
                    await page.goto(META_NOTIFICATIONS_URL, wait_until="domcontentloaded", timeout=45000)
                    await human_sleep(2.5, 4.0)
                except Exception as e_back:
                    logger.debug("Lỗi quay lại trang Thông báo: %s", e_back)

            await human_sleep(ACTION_COOLDOWN_SECONDS[0], ACTION_COOLDOWN_SECONDS[1])

        except Exception as e_notif:
            logger.warning("Lỗi khi xử lý thông báo bình luận: %s", e_notif)

    return replied_count


async def process_facebook_comments_tab(
    page: Page,
    memory: BotMemoryStore,
    dry_run: bool = False,
) -> int:
    """
    Quét tab Bình luận Facebook trên Meta Business Suite (Phương án Dự phòng / Fallback):
    1. Lọc sạch tên khách hàng (chống lấy nhầm 'Chỉ báo trạng thái online').
    2. Chọn bài viết an toàn ở cột trái tại position x=150, y=40.
    3. Xử lý bình luận trên bài viết bằng Động cơ Tọa độ DOM F12 Vật lý.
    """
    replied_count = 0
    logger.info("Đang kiểm tra Tab Bình luận Facebook (Fallback): %s", META_INBOX_COMMENTS_URL)
    await page.goto(META_INBOX_COMMENTS_URL, wait_until="domcontentloaded", timeout=45000)
    await human_sleep(4.0, 6.0)

    if not await verify_logged_in(page):
        logger.warning("Phiên đăng nhập Facebook chưa sẵn sàng hoặc đã hết hạn!")
        return 0

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
            try:
                await safe_click(item, timeout=3000, position={"x": 150, "y": 40})
            except Exception:
                await dismiss_blocking_modals(page)
                await safe_click(item, timeout=3000, position={"x": 150, "y": 40})
            await human_sleep(2.0, 3.5)
            current_post_url = page.url

            # Xử lý tất cả bình luận trên bài viết này bằng Động cơ Tọa độ DOM F12
            p_replied = await process_post_comments_by_coordinates(
                page=page,
                memory=memory,
                current_post_url=current_post_url,
                dry_run=dry_run,
                max_comments=10,
            )
            replied_count += p_replied

        except Exception as e:
            logger.warning("Lỗi khi xử lý bài viết thứ %d: %s", i, e)

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
            // Khung chat Messenger MBS nằm trong khoảng x: 380..1120 (tâm trục ngang ~ 750)
            // Tin nhắn của khách luôn bám sát lề trái (r.left < 540).
            // Tin nhắn của Fanpage bám sát lề phải (r.left > 600 hoặc tâm bong bóng lệch phải > 750).
            const isLeftCustomer = r.left < 540;
            const isRightAligned = r.left > 600 || ((r.left + r.right) / 2 > 750);

            // Chữ ký nhận diện Page CHỈ được xét khi tin nhắn KHÔNG nằm ở lề trái của khách (tránh nhận nhầm khi khách hỏi về website/tư vấn)
            const hasBrandSignature = !isLeftCustomer && (
                lower.includes("dan86.vn") ||
                lower.includes("0933 133 516") ||
                lower.includes("nhân viên tư vấn") ||
                lower.includes("bộ phận tư vấn") ||
                lower.includes("dần86farm") ||
                lower.includes("bá lộc green")
            );
            const isPage = !isLeftCustomer && (isRightAligned || hasBrandSignature);

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

            # Chế độ thử nghiệm an toàn (nếu có cấu hình whitelist):
            if TEST_ONLY_AUTHOR_WHITELIST:
                c_norm = normalize_text(customer_name)
                if not any(normalize_text(w) in c_norm for w in TEST_ONLY_AUTHOR_WHITELIST):
                    logger.info("Chế độ thử nghiệm: Bỏ qua hội thoại Messenger từ [%s] (Không nằm trong TEST_ONLY_AUTHOR_WHITELIST).", customer_name)
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
