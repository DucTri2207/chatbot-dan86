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
    SYSTEM_BLACKLIST_STRINGS,
    TYPING_DELAY_MS,
    clean_customer_name,
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
    Phân tích khung chi tiết bình luận bên phải của Meta Business Suite:
    - Loại bỏ 100% các phần tử hệ thống ("Chỉ báo trạng thái online", "Đang hoạt động", v.v.)
    - Lấy chính xác tên khách hàng (từ aria-label 'Bình luận dưới tên ...' hoặc link tác giả)
    - Lấy nội dung bình luận sạch của khách
    - Kiểm tra xem bình luận này đã có phản hồi của Fanpage bên dưới chưa
    - Trả về index của article mục tiêu cần trả lời (`target_article_index`)
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
            "ẩn",
            "trả lời",
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
                                pageNames.some(p => lowerInner.startsWith(p) || lowerInner.includes(p + "\\n") || lowerInner.includes("tác giả\\n" + p));

            // Trích xuất tên tác giả
            let authorName = "";
            const mAria = aria.match(/Bình luận dưới tên\\s+(.+?)(?:\\s+vào\\s+|$)/i) ||
                          aria.match(/Comment by\\s+(.+?)(?:\\s+ago|\\s+at|\\s+on|$)/i);
            if (mAria && mAria[1]) {
                authorName = mAria[1].trim();
            }

            if (!authorName || isSystemString(authorName)) {
                // Thử lấy từ button/link tên tác giả
                const authorBtn = art.querySelector('div[role="button"]:not([aria-label]), a[role="link"], span[dir="auto"]');
                if (authorBtn && authorBtn.innerText) {
                    const cand = authorBtn.innerText.trim();
                    if (!isSystemString(cand) && cand.length >= 2 && cand.length <= 50) {
                        authorName = cand;
                    }
                }
            }

            if (!authorName || isSystemString(authorName)) {
                const lines = inner.split('\\n').map(s => s.trim()).filter(Boolean);
                for (const line of lines) {
                    if (!isSystemString(line) && line.length >= 2 && line.length <= 50 && !line.includes('tuần') && !line.includes('ngày') && !line.includes('phút') && !line.includes('giờ') && line !== '·') {
                        authorName = line;
                        break;
                    }
                }
            }

            // Trích xuất nội dung bình luận
            const lines = inner.split('\\n').map(s => s.trim()).filter(Boolean);
            const contentLines = lines.filter(l => {
                const low = l.toLowerCase();
                if (l === authorName || low.includes('tuần') || low.includes('ngày') || low.includes('phút') || low.includes('giờ') || l === '·') return false;
                if (['trả lời', 'ẩn', 'see chat', 'nhắn tin', 'gửi tin nhắn', 'thích', 'bày tỏ cảm xúc', 'theo dõi lại', 'theo dõi', 'tác giả', '1', '2', '3'].includes(low)) return false;
                return true;
            });
            const commentText = contentLines.join(" ").trim();

            // Kiểm tra nút Trả lời
            const actionEls = Array.from(art.querySelectorAll('[role="button"], span, div')).filter(el => el.children.length === 0);
            const hasReplyBtn = actionEls.some(el => {
                const t = (el.innerText || '').trim();
                return t === 'Trả lời' || t === 'Reply';
            });

            parsedComments.push({
                domIndex: allArticles.indexOf(art),
                isPageReply: isPageReply,
                authorName: authorName || "bạn",
                commentText: commentText,
                hasReplyBtn: hasReplyBtn,
                innerPreview: inner.slice(0, 100),
                articleEl: art
            });
        }

        // Tìm bình luận khách chưa có câu trả lời của Page
        let target = null;
        let targetArticleNode = null;
        for (let j = 0; j < parsedComments.length; j++) {
            const item = parsedComments[j];
            if (item.isPageReply) continue;

            let hasReplyBelow = false;
            if (j + 1 < parsedComments.length && parsedComments[j + 1].isPageReply) {
                hasReplyBelow = true;
            }

            if (!hasReplyBelow && item.hasReplyBtn && item.commentText) {
                target = {
                    author_name: item.authorName,
                    comment_text: item.commentText,
                    target_article_index: item.domIndex,
                    has_page_reply: false,
                    comment_id: ""
                };
                targetArticleNode = item.articleEl;
                break;
            }
        }

        if (!target && parsedComments.length > 0) {
            const first = parsedComments.find(p => !p.isPageReply) || parsedComments[0];
            target = {
                author_name: first.authorName,
                comment_text: first.commentText,
                target_article_index: first.domIndex,
                has_page_reply: true,
                comment_id: ""
            };
            targetArticleNode = first.articleEl;
        }

        // Đánh dấu trực tiếp các data-attributes lên DOM để Playwright định vị chính xác 100%
        document.querySelectorAll('[data-dan86-reply-target]').forEach(e => e.removeAttribute('data-dan86-reply-target'));
        document.querySelectorAll('[data-dan86-reply-btn]').forEach(e => e.removeAttribute('data-dan86-reply-btn'));
        document.querySelectorAll('[data-dan86-msg-btn]').forEach(e => e.removeAttribute('data-dan86-msg-btn'));

        if (targetArticleNode) {
            targetArticleNode.setAttribute('data-dan86-reply-target', 'true');

            // 1. Tìm nút Trả lời / Reply
            const actionEls = Array.from(targetArticleNode.querySelectorAll('[role="button"], span, div')).filter(el => el.children.length === 0);
            const rBtn = actionEls.find(el => {
                const t = (el.innerText || '').trim();
                const a = (el.getAttribute('aria-label') || '').trim();
                return t === 'Trả lời' || t === 'Reply' || a === 'Trả lời' || a === 'Reply';
            });
            if (rBtn) {
                const clickNode = rBtn.closest('[role="button"]') || rBtn;
                clickNode.setAttribute('data-dan86-reply-btn', 'true');
            }

            // 2. Tìm nút Gửi tin nhắn / Nhắn tin / Message / See Chat
            const mBtn = actionEls.find(el => {
                const t = (el.innerText || '').trim();
                const a = (el.getAttribute('aria-label') || '').trim();
                const combo = (t + ' ' + a).toLowerCase();
                return combo.includes('see chat') || combo.includes('gửi tin nhắn') || combo.includes('nhắn tin') || combo.includes('send message') || combo.includes('message');
            });
            if (mBtn) {
                const msgNode = mBtn.closest('[role="button"]') || mBtn;
                msgNode.setAttribute('data-dan86-msg-btn', 'true');
            }
        }

        const urlParams = new URLSearchParams(window.location.search);
        const commentId = urlParams.get("selected_item_id") || urlParams.get("comment_id") || "";
        if (target) {
            target.comment_id = commentId;
            return target;
        }

        return {
            author_name: "bạn",
            comment_text: "",
            comment_id: commentId,
            has_page_reply: false,
            target_article_index: -1
        };
    }
    """
    try:
        raw_res = await page.evaluate(js_code, PAGE_NAMES)
        raw_res["author_name"] = clean_customer_name(raw_res.get("author_name", ""))
        return raw_res
    except Exception as e:
        logger.debug("Không thể phân tích DOM bình luận: %s", e)
        return {
            "author_name": "bạn",
            "comment_text": "",
            "comment_id": "",
            "has_page_reply": False,
            "target_article_index": -1,
        }


async def send_private_inbox_to_commenter(
    page: Page,
    target_article: Optional[Locator],
    private_reply_text: str,
    dry_run: bool = False,
) -> bool:
    """
    Bấm nút 'Gửi tin nhắn' / 'Nhắn tin' (Message / Send message) ngay dưới bình luận của khách
    trong Meta Business Suite và gửi tin nhắn tư vấn riêng vào Inbox cho người đó.
    """
    msg_btn_selectors = [
        '[data-dan86-msg-btn="true"]',
        'div[role="button"]:has-text("See Chat")',
        'span:has-text("See Chat")',
        'div[role="button"]:has-text("Gửi tin nhắn")',
        'div[role="button"]:has-text("Nhắn tin")',
        'span:has-text("Gửi tin nhắn")',
        'span:has-text("Nhắn tin")',
        'div[role="button"]:has-text("Send message")',
        'div[role="button"]:has-text("Message")',
        'div[role="button"]:has-text("Chat")',
        '[aria-label*="See Chat"]',
        '[aria-label*="Gửi tin nhắn"]',
        '[aria-label*="Nhắn tin"]',
        '[aria-label*="Send message"]',
    ]

    clicked_modal = False

    # 1. Ưu tiên tìm nút đã được gán data-dan86-msg-btn từ JS
    marked_msg_btn = page.locator('[data-dan86-msg-btn="true"]').first
    if await marked_msg_btn.count() > 0 and await marked_msg_btn.is_visible():
        if dry_run:
            logger.info("[DRY-RUN] Sẽ bấm nút 'Gửi tin nhắn/See Chat' riêng cho người comment: %s", private_reply_text[:80])
            return True
        try:
            await marked_msg_btn.click()
            clicked_modal = True
            await human_sleep(1.5, 2.8)
        except Exception as e_mbtn:
            logger.debug("Lỗi bấm nút tin nhắn đánh dấu: %s", e_mbtn)

    # 2. Tìm nút trong chính article bình luận của khách
    if not clicked_modal and target_article is not None:
        for sel in msg_btn_selectors:
            loc = target_article.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                if dry_run:
                    logger.info("[DRY-RUN] Sẽ bấm nút 'Gửi tin nhắn/See Chat' riêng cho người comment: %s", private_reply_text[:80])
                    return True
                try:
                    await loc.click()
                    clicked_modal = True
                    await human_sleep(1.5, 2.8)
                    break
                except Exception:
                    continue

    # 3. Fallback tìm nút trên toàn trang nếu trong article không có
    if not clicked_modal:
        for sel in msg_btn_selectors:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                if dry_run:
                    logger.info("[DRY-RUN] Sẽ bấm nút 'Gửi tin nhắn/See Chat' riêng cho người comment: %s", private_reply_text[:80])
                    return True
                try:
                    await loc.click()
                    clicked_modal = True
                    await human_sleep(1.5, 2.8)
                    break
                except Exception:
                    continue

    if not clicked_modal:
        logger.info("Không thấy nút 'Gửi tin nhắn/See Chat' dưới bình luận (có thể bình luận quá hạn 7 ngày theo chính sách Meta, hoặc khách chặn tin nhắn).")
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
            target_box = boxes.last
            if await target_box.is_visible():
                await type_human_like(page, target_box, private_reply_text)
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
    1. Lọc sạch tên khách hàng (chống lấy nhầm 'Chỉ báo trạng thái online').
    2. Bấm chính xác nút 'Trả lời' dưới bình luận của khách để mở nested reply (không đăng thành cmt gốc bài viết).
    3. Thả Like bình luận.
    4. Random câu trả lời công khai lồng dưới bình luận (1 lần duy nhất).
    5. Tự động bấm 'Gửi tin nhắn' để Inbox riêng cho người bình luận đó (1 lần duy nhất).
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
            target_art_idx = int(info.get("target_article_index", -1))

            if is_page_author_name(author_name):
                continue

            should_rep, comment_key = memory.should_reply_comment(
                author_name=author_name,
                comment_text=comment_text,
                has_page_reply_in_dom=has_page_reply,
                comment_id=comment_id,
            )

            if not should_rep:
                logger.debug("Bỏ qua bình luận của %s (đã trả lời trước đó hoặc không hợp lệ).", author_name)
                continue

            public_reply, private_inbox_reply = memory.prepare_comment_and_inbox_replies(author_name)
            logger.info("Phát hiện bình luận mới từ [%s]: %s", author_name, comment_text[:80])

            if dry_run:
                logger.info("[DRY-RUN] Sẽ rep cmt công khai lồng bên dưới: %s", public_reply)
                logger.info("[DRY-RUN] Sẽ tự động inbox riêng: %s", private_inbox_reply[:90])
                replied_count += 1
                continue

            # Xác định article bình luận mục tiêu
            target_art: Optional[Locator] = None
            marked_target = page.locator('[data-dan86-reply-target="true"]').first
            if await marked_target.count() > 0 and await marked_target.is_visible():
                target_art = marked_target
            elif target_art_idx >= 0:
                all_arts = page.locator('[role="article"]')
                if await all_arts.count() > target_art_idx:
                    target_art = all_arts.nth(target_art_idx)

            # Bước 1: Thả Like bình luận của khách (nếu có nút Thích chưa bấm trong target_art)
            if target_art is not None:
                like_btn = target_art.locator('div[role="button"]:has-text("Thích"), div[role="button"]:has-text("Like")').first
                if await like_btn.count() > 0 and await like_btn.is_visible():
                    try:
                        await like_btn.click()
                        await human_sleep(0.8, 1.5)
                    except Exception:
                        pass

            # Bước 2: Bấm chính xác nút "Trả lời" (Reply) của bình luận khách để mở nested reply!
            reply_clicked = False
            marked_reply_btn = page.locator('[data-dan86-reply-btn="true"]').first
            if await marked_reply_btn.count() > 0 and await marked_reply_btn.is_visible():
                try:
                    await marked_reply_btn.click()
                    reply_clicked = True
                    await human_sleep(1.2, 2.2)
                except Exception as e_reply:
                    logger.debug("Lỗi bấm nút Trả lời đánh dấu: %s", e_reply)

            if not reply_clicked and target_art is not None:
                reply_btn = target_art.locator(
                    'div[role="button"]:has-text("Trả lời"), '
                    'span:has-text("Trả lời"), '
                    'div[role="button"]:has-text("Reply")'
                ).first
                if await reply_btn.count() > 0 and await reply_btn.is_visible():
                    try:
                        await reply_btn.click()
                        reply_clicked = True
                        await human_sleep(1.2, 2.2)
                    except Exception as e_reply:
                        logger.warning("Lỗi bấm nút Trả lời trong comment article: %s", e_reply)

            # Tìm ô nhập phản hồi lồng nhau cấp 2 (nested reply box)
            # Ưu tiên 1: Focus box sau khi click Reply
            nested_box = page.locator('div[role="textbox"]:focus').first

            # Ưu tiên 2: Ô có aria-label Trả lời với vai trò
            if await nested_box.count() == 0 or not await nested_box.is_visible():
                nested_box = page.locator(
                    'div[role="textbox"][aria-label*="Trả lời với vai trò"], '
                    'div[role="textbox"][aria-label*="Reply as"], '
                    'div[role="textbox"][aria-label*="Viết câu trả lời"]'
                ).first

            # Ưu tiên 3: Ô textbox nằm ngay bên trong hoặc kế cận target_art
            if (await nested_box.count() == 0 or not await nested_box.is_visible()) and target_art is not None:
                nested_box = target_art.locator('div[role="textbox"]').first

            # CHỐNG GÕ NHẦM Ô BÌNH LUẬN GỐC CỦA BÀI VIẾT:
            is_valid_nested_box = False
            if await nested_box.count() > 0 and await nested_box.is_visible():
                box_aria = (await nested_box.get_attribute("aria-label") or "").lower()
                box_placeholder = (await nested_box.get_attribute("placeholder") or "").lower()
                if "bình luận dưới tên" in box_aria or "viết bình luận" in box_placeholder:
                    logger.warning("Phát hiện ô bình luận bài viết cấp 1! Bỏ qua để không đăng nhầm cmt cấp 1!")
                    is_valid_nested_box = False
                else:
                    is_valid_nested_box = True

            if is_valid_nested_box:
                await type_human_like(page, nested_box, public_reply)
                await page.keyboard.press("Enter")
                await human_sleep(2.5, 4.0)
                logger.info("Đã gửi phản hồi bình luận công khai cho [%s] (Nested Reply: %s).", author_name, reply_clicked)

                # Bước 3: Tự động bấm Gửi tin nhắn riêng (Private Reply) cho người vừa bình luận
                inbox_sent = await send_private_inbox_to_commenter(
                    page=page,
                    target_article=target_art,
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
            else:
                logger.warning("Không tìm thấy ô nhập nested reply hợp lệ cho bình luận của [%s].", author_name)

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

        // Tìm tất cả các bong bóng tin nhắn trong khung chat (x: 380..1120, y: 120..840)
        const chatNodes = Array.from(document.querySelectorAll('[dir="auto"], [role="row"]'))
            .filter(el => {
                const r = el.getBoundingClientRect();
                return r.left > 380 && r.right < 1120 && r.top > 120 && r.bottom < 840 && r.height >= 16;
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

            if last_sender_is_page:
                memory.touch_staff_interaction(customer_name=customer_name, thread_id=thread_id)
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
