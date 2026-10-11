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
import time
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import Browser, BrowserContext, Locator, Page, Playwright

from bot.bot_config import (
    ACTION_COOLDOWN_SECONDS,
    CHROME_PROFILE_DIR,
    LOGS_DIR,
    MAX_THREADS_PER_CYCLE,
    META_INBOX_COMMENTS_URL,
    META_INBOX_MESSENGER_URL,
    PAGE_NAMES,
    STORAGE_STATE_FILE,
    TYPING_DELAY_MS,
)
from bot.memory_store import BotMemoryStore, normalize_text

logger = logging.getLogger("dan86_page_bot")


def restore_storage_state_from_env() -> bool:
    """
    Khôi phục file state/fb_storage_state.json từ biến môi trường FB_STORAGE_STATE
    (dùng khi chạy tự động trên VPS GitHub Actions).
    """
    env_b64 = os.environ.get("FB_STORAGE_STATE", "").strip()
    if not env_b64:
        return os.path.exists(STORAGE_STATE_FILE)

    os.makedirs(os.path.dirname(STORAGE_STATE_FILE), exist_ok=True)
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
        return os.path.exists(STORAGE_STATE_FILE)


async def create_bot_browser_context(
    playwright: Playwright,
    headless: bool = False,
    use_persistent_profile: bool = False,
) -> Tuple[Optional[Browser], BrowserContext]:
    """Khởi tạo trình duyệt Playwright siêu nhẹ với phiên đăng nhập đã lưu."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    restore_storage_state_from_env()

    # Tự động nạp cookies từ d:\dan86 nếu chưa có file state cục bộ
    if not os.path.exists(STORAGE_STATE_FILE):
        try:
            from bot.auth_helper import sync_facebook_credentials_from_dan86
            sync_res = sync_facebook_credentials_from_dan86()
            if sync_res.get("success"):
                logger.info("Tự động nạp cookies từ d:\\dan86 thành công (%d cookies).", sync_res.get("cookies_count", 0))
        except Exception as e:
            logger.warning("Không thể tự động nạp cookies từ d:\\dan86: %s", e)

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


async def type_human_like(page: Page, locator: Locator, text: str) -> None:
    """
    Gõ văn bản vào ô chat giống người thật (hỗ trợ xuống dòng Shift+Enter
    để không bị gửi sớm khi mẫu câu có nhiều dòng).
    """
    await locator.click()
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
    """
    url = page.url.lower()

    # 1. Nếu trang chứa form nhập tài khoản / mật khẩu thông thường
    login_form = await page.locator('input[name="email"], input[name="pass"]').count()
    if login_form > 0:
        return False

    # 2. Nếu đang ở trang đăng nhập của Meta Business Suite, tự động bấm nút tiếp tục bằng tài khoản có sẵn
    if "login" in url:
        logger.info("Phát hiện màn hình chuyển tiếp Meta Business. Đang kiểm tra nút đăng nhập một chạm...")
        sso_selectors = [
            'button:has-text("Tiếp tục bằng Facebook")',
            'a:has-text("Tiếp tục bằng Facebook")',
            'div[role="button"]:has-text("Tiếp tục bằng Facebook")',
            'button:has-text("Tiếp tục dưới tên")',
            'a:has-text("Tiếp tục dưới tên")',
            'div[role="button"]:has-text("Tiếp tục dưới tên")',
            'button:has-text("Log in with Facebook")',
            'a:has-text("Log in with Facebook")',
        ]

        clicked = False
        for sel in sso_selectors:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                logger.info("Bấm nút bắc cầu phiên Facebook sang Meta: %s", sel)
                try:
                    async with page.context.expect_page(timeout=5000) as pinfo:
                        await loc.click()
                    popup = await pinfo.value
                    await popup.wait_for_load_state("domcontentloaded")
                    p_btn = popup.locator('div[role="button"]:has-text("Tiếp tục"), button:has-text("Tiếp tục"), text="Tiếp tục"').first
                    if await p_btn.count() > 0 and await p_btn.is_visible():
                        await p_btn.click()
                    await popup.wait_for_event("close", timeout=10000)
                    clicked = True
                    break
                except Exception:
                    try:
                        await loc.click()
                        await page.wait_for_load_state("domcontentloaded")
                        clicked = True
                        break
                    except Exception as e_click:
                        logger.debug("Lỗi bấm nút SSO: %s", e_click)

        if clicked:
            await asyncio.sleep(4.0)
            url = page.url.lower()

    if "checkpoint" in url:
        return False
    if "login" in url:
        return False

    return True


# ==============================================================================
# PHẦN 1: QUÉT & TRẢ LỜI BÌNH LUẬN FACEBOOK + TỰ ĐỘNG INBOX NGƯỜI BÌNH LUẬN
# ==============================================================================
async def inspect_comment_panel(page: Page) -> Dict[str, Any]:
    """
    Phân tích khung chi tiết bình luận bên phải của Meta Business Suite để lấy:
    - Tên khách bình luận (`author_name`)
    - Nội dung bình luận của khách (`comment_text`)
    - ID hoặc dấu hiệu bình luận (`comment_id`)
    - Đã có câu trả lời của Fanpage bên dưới chưa (`has_page_reply`)
    """
    js_code = """
    (pageNames) => {
        const result = {
            author_name: "bạn",
            comment_text: "",
            comment_id: "",
            has_page_reply: false
        };

        // Tìm vùng hiển thị chi tiết bài viết & bình luận ở giữa/bên phải màn hình
        const mainAreas = Array.from(document.querySelectorAll('[role="main"], [role="region"], [data-pagelet]'))
            .filter(el => el.getBoundingClientRect().left > 280 && el.innerText && el.innerText.trim().length > 10);

        const container = mainAreas.length > 0 ? mainAreas[mainAreas.length - 1] : document.body;
        const articles = Array.from(container.querySelectorAll('[role="article"], [data-testid*="comment"]'));

        if (articles.length > 0) {
            for (const art of articles) {
                const txt = (art.innerText || "").trim();
                const lower = txt.toLowerCase();
                const isPage = pageNames.some(p => lower.startsWith(p) || lower.includes(p + "\\n"));
                if (isPage) {
                    result.has_page_reply = true;
                } else if (!result.comment_text && txt.length > 1) {
                    const lines = txt.split("\\n").map(s => s.trim()).filter(Boolean);
                    if (lines.length >= 2) {
                        result.author_name = lines[0];
                        result.comment_text = lines.slice(1).join(" ");
                    } else if (lines.length === 1) {
                        result.comment_text = lines[0];
                    }
                }
            }
        }

        // Fallback nếu Meta Business Suite dùng cấu trúc div phẳng thay vì role="article"
        if (!result.comment_text) {
            const fullText = (container.innerText || "").trim();
            const lowerFull = fullText.toLowerCase();
            if (pageNames.some(p => lowerFull.includes("đã gửi thông tin chi tiết") || lowerFull.includes("vừa nhắn tin tư vấn") || lowerFull.includes("đã gửi tin nhắn riêng"))) {
                result.has_page_reply = true;
            }
            const lines = fullText.split("\\n").map(s => s.trim()).filter(s => s.length > 1);
            if (lines.length >= 2) {
                result.author_name = lines[0].slice(0, 50);
                result.comment_text = lines.slice(1, 5).join(" ").slice(0, 300);
            }
        }

        const urlParams = new URLSearchParams(window.location.search);
        result.comment_id = urlParams.get("selected_item_id") || urlParams.get("comment_id") || "";
        return result;
    }
    """
    try:
        return await page.evaluate(js_code, PAGE_NAMES)
    except Exception as e:
        logger.debug("Không thể phân tích DOM bình luận: %s", e)
        return {
            "author_name": "bạn",
            "comment_text": "",
            "comment_id": "",
            "has_page_reply": False,
        }


async def send_private_inbox_to_commenter(
    page: Page,
    private_reply_text: str,
    dry_run: bool = False,
) -> bool:
    """
    Bấm nút 'Gửi tin nhắn' / 'Nhắn tin' (Message / Send message) ngay dưới bình luận của khách
    trong Meta Business Suite và gửi tin nhắn tư vấn riêng vào Inbox cho người đó.
    """
    msg_btn_selectors = [
        'div[role="button"]:has-text("Gửi tin nhắn")',
        'div[role="button"]:has-text("Nhắn tin")',
        'span:has-text("Gửi tin nhắn")',
        'span:has-text("Nhắn tin")',
        'div[role="button"]:has-text("Send message")',
        'div[role="button"]:has-text("Message")',
        '[aria-label="Gửi tin nhắn"]',
        '[aria-label="Send message"]',
    ]

    clicked_modal = False
    for sel in msg_btn_selectors:
        loc = page.locator(sel).first
        if await loc.count() > 0 and await loc.is_visible():
            if dry_run:
                logger.info("[DRY-RUN] Sẽ bấm nút 'Gửi tin nhắn' riêng cho người comment: %s", private_reply_text[:80])
                return True
            try:
                await loc.click()
                clicked_modal = True
                await human_sleep(1.5, 2.8)
                break
            except Exception:
                continue

    if not clicked_modal:
        logger.info("Không thấy nút 'Gửi tin nhắn' dưới bình luận (có thể đã gửi inbox trước đó hoặc khách chặn tin nhắn).")
        return False

    # Tìm ô nhập tin nhắn trong hộp thoại (Modal) hoặc khung gửi tin nhắn riêng vừa bật lên
    modal_input_selectors = [
        'div[role="dialog"] div[role="textbox"][contenteditable="true"]',
        'div[role="dialog"] textarea',
        'div[role="textbox"][contenteditable="true"]',
    ]

    for input_sel in modal_input_selectors:
        boxes = page.locator(input_sel)
        count = await boxes.count()
        if count > 0:
            # Lấy textbox nằm ở trên cùng (trong dialog vừa mở)
            target_box = boxes.last
            if await target_box.is_visible():
                await type_human_like(page, target_box, private_reply_text)
                # Tìm nút Gửi trong dialog hoặc nhấn Enter
                send_btn = page.locator(
                    'div[role="dialog"] [aria-label*="Gửi"], '
                    'div[role="dialog"] [aria-label*="Send"], '
                    'div[role="dialog"] div[role="button"]:has-text("Gửi"), '
                    'div[role="dialog"] div[role="button"]:has-text("Send")'
                ).last
                if await send_btn.count() > 0 and await send_btn.is_visible():
                    await send_btn.click()
                else:
                    await page.keyboard.press("Enter")
                await human_sleep(2.0, 3.5)
                logger.info("Đã tự động gửi Inbox riêng cho người bình luận thành công!")
                return True

    return False


async def process_facebook_comments_tab(
    page: Page,
    memory: BotMemoryStore,
    dry_run: bool = False,
) -> int:
    """
    Quét tab Bình luận Facebook trên Meta Business Suite:
    1. Thả Like bình luận.
    2. Random câu trả lời công khai dưới bình luận (1 lần duy nhất).
    3. Tự động bấm 'Gửi tin nhắn' để Inbox riêng cho người bình luận đó (1 lần duy nhất).
    """
    replied_count = 0
    logger.info("Đang kiểm tra Tab Bình luận Facebook: %s", META_INBOX_COMMENTS_URL)
    await page.goto(META_INBOX_COMMENTS_URL, wait_until="domcontentloaded", timeout=45000)
    await human_sleep(4.0, 6.0)

    if not await verify_logged_in(page):
        logger.warning("Phiên đăng nhập Facebook chưa sẵn sàng hoặc đã hết hạn!")
        return 0

    # Tìm danh sách các mục bình luận ở cột bên trái
    thread_selectors = [
        '[role="navigation"] [role="listitem"]',
        '[role="grid"] [role="row"]',
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
    logger.info("Tìm thấy %d mục bình luận cần kiểm tra.", total_items)

    for i in range(total_items):
        try:
            item = items_locator.nth(i)
            if not await item.is_visible():
                continue

            preview_text = (await item.inner_text() or "").strip()
            await item.click()
            await human_sleep(2.0, 3.5)

            info = await inspect_comment_panel(page)
            author_name = info.get("author_name") or "bạn"
            comment_text = info.get("comment_text") or preview_text
            comment_id = info.get("comment_id") or ""
            has_page_reply = bool(info.get("has_page_reply", False))

            if is_page_author_name(author_name):
                continue

            should_rep, comment_key = memory.should_reply_comment(
                author_name=author_name,
                comment_text=comment_text,
                has_page_reply_in_dom=has_page_reply,
                comment_id=comment_id,
            )

            if not should_rep:
                logger.debug("Bỏ qua bình luận của %s (đã trả lời trước đó).", author_name)
                continue

            public_reply, private_inbox_reply = memory.prepare_comment_and_inbox_replies(author_name)
            logger.info("Phát hiện bình luận mới từ [%s]: %s", author_name, comment_text[:80])

            if dry_run:
                logger.info("[DRY-RUN] Sẽ rep cmt công khai: %s", public_reply)
                logger.info("[DRY-RUN] Sẽ tự động inbox riêng: %s", private_inbox_reply[:90])
                replied_count += 1
                continue

            # Bước 1: Thả Like bình luận (nếu có nút Thích chưa bấm)
            like_btn = page.locator('div[role="button"]:has-text("Thích"), div[role="button"]:has-text("Like")').first
            if await like_btn.count() > 0 and await like_btn.is_visible():
                try:
                    await like_btn.click()
                    await human_sleep(0.8, 1.5)
                except Exception:
                    pass

            # Bước 2: Gõ câu trả lời công khai vào ô bình luận
            comment_box = page.locator(
                'div[role="textbox"][contenteditable="true"], '
                'textarea[placeholder*="bình luận"], '
                'textarea[placeholder*="comment"]'
            ).first

            if await comment_box.count() > 0 and await comment_box.is_visible():
                await type_human_like(page, comment_box, public_reply)
                await page.keyboard.press("Enter")
                await human_sleep(2.5, 4.0)
                logger.info("Đã trả lời bình luận công khai cho [%s].", author_name)

                # Bước 3: Tự động bấm Gửi tin nhắn riêng (Private Reply) cho người vừa bình luận
                inbox_sent = await send_private_inbox_to_commenter(
                    page=page,
                    private_reply_text=private_inbox_reply,
                    dry_run=dry_run,
                )

                # Lưu vào bộ nhớ để không bao giờ trả lời lặp lại bình luận này
                memory.mark_comment_replied(
                    comment_key=comment_key,
                    author_name=author_name,
                    comment_text=comment_text,
                    public_reply=public_reply,
                    private_inbox_sent=inbox_sent,
                    private_reply_text=private_inbox_reply,
                )
                replied_count += 1
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
    - Tên khách hàng (`customer_name`)
    - Tin nhắn cuối cùng (`last_message_text`)
    - Tin nhắn cuối cùng là của Fanpage hay của khách (`last_sender_is_page`)
    - Trước đó Fanpage đã từng gửi tin nhắn nào trong cuộc trò chuyện này chưa (`has_prior_page_messages`)
    - Mã hội thoại (`thread_id`)
    """
    js_code = """
    (pageNames) => {
        const info = {
            customer_name: "bạn",
            last_message_text: "",
            last_sender_is_page: false,
            has_prior_page_messages: false,
            thread_id: ""
        };

        const urlParams = new URLSearchParams(window.location.search);
        info.thread_id = urlParams.get("selected_item_id") || "";

        // Lấy tên khách hàng trên thanh tiêu đề cuộc trò chuyện
        const headings = Array.from(document.querySelectorAll('h1, h2, h3, [role="heading"]'))
            .filter(el => el.getBoundingClientRect().left > 280 && el.getBoundingClientRect().top < 200);
        for (const h of headings) {
            const t = (h.innerText || "").trim();
            if (t && t.length > 1 && t.length < 60 && !t.toLowerCase().includes("hộp thư")) {
                info.customer_name = t.split("\\n")[0].trim();
                break;
            }
        }

        // Tìm tất cả các bong bóng tin nhắn (message rows) trong khung chat chính
        const msgNodes = Array.from(document.querySelectorAll('[role="row"], [data-testid*="message"], [dir="auto"]'))
            .filter(el => {
                const rect = el.getBoundingClientRect();
                return rect.left > 300 && rect.right < window.innerWidth - 250 && rect.height > 14 && rect.height < 500;
            });

        const messages = [];
        for (const node of msgNodes) {
            const txt = (node.innerText || "").trim();
            if (!txt || txt.length < 2) continue;
            const rect = node.getBoundingClientRect();
            const centerX = rect.left + rect.width / 2;
            const lower = txt.toLowerCase();

            // Bong bóng tin nhắn của Page thường nằm lệch về bên phải hoặc chứa chữ ký thương hiệu DAN86
            const hasBrandSignature = (
                lower.includes("dan86.vn") ||
                lower.includes("0933 133 516") ||
                lower.includes("nhân viên tư vấn của shop") ||
                lower.includes("bộ phận tư vấn sẽ phản hồi")
            );
            const isRightAligned = rect.left > 560;
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
        return await page.evaluate(js_code, PAGE_NAMES)
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
            item = items_locator.nth(i)
            if not await item.is_visible():
                continue

            await item.click()
            await human_sleep(2.0, 3.5)

            conv = await inspect_messenger_conversation(page)
            customer_name = conv.get("customer_name") or "bạn"
            last_msg_text = conv.get("last_message_text") or ""
            last_sender_is_page = bool(conv.get("last_sender_is_page", False))
            has_prior_page_msgs = bool(conv.get("has_prior_page_messages", False))
            thread_id = conv.get("thread_id") or ""

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
