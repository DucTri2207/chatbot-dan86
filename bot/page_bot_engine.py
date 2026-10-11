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
        for sel in sso_selectors:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                logger.info("Bấm nút bắc cầu phiên Facebook sang Meta: %s", sel)
                try:
                    async with page.context.expect_page(timeout=8000) as pinfo:
                        await loc.click()
                    popup = await pinfo.value
                    await popup.wait_for_load_state("domcontentloaded")
                    p_btn = popup.locator(
                        'div[role="button"]:has-text("Tiếp tục"), '
                        'button:has-text("Tiếp tục"), '
                        'div:has-text("Tiếp tục"), '
                        'a:has-text("Tiếp tục")'
                    ).last
                    if await p_btn.count() > 0 and await p_btn.is_visible():
                        await p_btn.click()
                    try:
                        await popup.wait_for_event("close", timeout=8000)
                    except Exception:
                        pass
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
            await human_sleep(3.0, 5.0)
            url = page.url.lower()
            if "login" in url:
                try:
                    await page.goto(META_INBOX_COMMENTS_URL, wait_until="domcontentloaded", timeout=45000)
                    await human_sleep(3.0, 4.0)
                    url = page.url.lower()
                except Exception:
                    pass

    if "checkpoint" in url:
        return False
    if "login" in url:
        return False

    # Lưu cố định toàn bộ cookies (gồm cả business.facebook.com) ngay sau khi xác thực/vào inbox thành công
    try:
        from bot.auth_helper import export_github_secret_file
        await page.context.storage_state(path=str(STORAGE_STATE_FILE))
        export_github_secret_file(str(STORAGE_STATE_FILE))
        logger.info("Đã lưu cố định fb_storage_state.json và cập nhật GITHUB_SECRET_VALUE.txt thành công!")
    except Exception as e_save:
        logger.warning("Không thể lưu storage_state sau xác thực: %s", e_save)

    return True


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
            'div[role="button"]:has-text("Xem"):has-text("phản hồi")',
            'span:has-text("Xem"):has-text("phản hồi")',
            'div[role="button"]:has-text("Xem thêm bình luận")',
            'span:has-text("Xem thêm bình luận")',
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
            return t === 'trả lời' || t === 'reply' || t === 'phản hồi' ||
                   a.includes('trả lời') || a.includes('reply') || a.includes('phản hồi');
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
                                pageNames.some(p => lowerInner.startsWith(p) || lowerInner.includes(p + "\\n") || lowerInner.includes("tác giả\\n" + p));

            // Trích xuất tên tác giả
            let authorName = "";
            const mAria = aria.match(/Bình luận dưới tên\\s+(.+?)(?:\\s+vào\\s+|$)/i) ||
                          aria.match(/Comment by\\s+(.+?)(?:\\s+ago|\\s+at|\\s+on|$)/i);
            if (mAria && mAria[1]) {
                authorName = mAria[1].trim();
            }

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
                const lines = inner.split('\\n').map(s => s.trim()).filter(Boolean);
                for (const line of lines) {
                    if (!isSystemString(line) && line.length >= 2 && line.length <= 50 && !line.includes('tuần') && !line.includes('ngày') && !line.includes('phút') && !line.includes('giờ') && line !== '·') {
                        authorName = line;
                        break;
                    }
                }
            }

            // Trích xuất nội dung bình luận (cho phép bình luận 1 ký tự, icon, số, chữ ngắn)
            const lines = inner.split('\\n').map(s => s.trim()).filter(Boolean);
            const contentLines = lines.filter(l => {
                const low = l.toLowerCase();
                if (l === authorName || low.includes('tuần') || low.includes('ngày') || low.includes('phút') || low.includes('giờ') || l === '·') return false;
                if (/^\d+(\s+(?:phản hồi|bình luận|replies|reply))?$/i.test(l.trim())) return false;
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

            // Kiểm tra nút Trả lời / Phản hồi & Nút Nhắn tin
            const candidateEls = Array.from(art.querySelectorAll('button, [role="button"], a[role="link"], [role="link"], span, div'));
            const rBtn = candidateEls.find(isReplyBtn);
            const mBtn = candidateEls.find(isMsgBtn);

            parsedComments.push({
                domIndex: allArticles.indexOf(art),
                isPageReply: isPageReply,
                authorName: authorName || "bạn",
                commentText: commentText,
                hasReplyBtn: !!rBtn,
                msgBtnText: mBtn ? ((mBtn.innerText || '').trim() || (mBtn.getAttribute('aria-label') || '').trim()) : "",
                innerPreview: inner.slice(0, 100),
                articleEl: art
            });
        }

        // Đánh giá xem bình luận nào có phản hồi của Page ngay bên dưới
        for (let j = 0; j < parsedComments.length; j++) {
            const item = parsedComments[j];
            if (item.isPageReply) {
                item.hasPageReply = true;
                continue;
            }

            let hasReplyBelow = false;
            if (j + 1 < parsedComments.length && parsedComments[j + 1].isPageReply) {
                hasReplyBelow = true;
            }
            item.hasPageReply = hasReplyBelow;
        }

        // Lấy danh sách tất cả các bình luận khách chưa có Page trả lời
        const unrepliedList = parsedComments.filter(c => !c.isPageReply && !c.hasPageReply);

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
            const candidateEls = Array.from(targetArticleNode.querySelectorAll('button, [role="button"], a[role="link"], [role="link"], span, div'));
            const rBtn = candidateEls.find(isReplyBtn);
            if (rBtn) {
                const clickNode = rBtn.closest('button, [role="button"], a') || rBtn;
                clickNode.setAttribute('data-dan86-reply-btn', 'true');
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
                has_page_reply: false,
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
        for uc in raw_res.get("unreplied_comments", []):
            uc["author_name"] = clean_customer_name(uc.get("author_name", ""))
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
        target.setAttribute('data-dan86-reply-target', 'true');

        const isReplyBtn = (el) => {
            const t = (el.innerText || '').trim().toLowerCase();
            const a = (el.getAttribute('aria-label') || '').trim().toLowerCase();
            return t === 'trả lời' || t === 'reply' || t === 'phản hồi' ||
                   a.includes('trả lời') || a.includes('reply') || a.includes('phản hồi');
        };

        const isMsgBtn = (el) => {
            const t = (el.innerText || '').trim().toLowerCase();
            const a = (el.getAttribute('aria-label') || '').trim().toLowerCase();
            const combo = t + ' ' + a;
            return combo.includes('see chat') || combo.includes('gửi tin nhắn') ||
                   combo.includes('nhắn tin') || combo.includes('send message') ||
                   combo.includes('tin nhắn') || combo.includes('message') || combo.includes('chat');
        };

        const candidateEls = Array.from(target.querySelectorAll('button, [role="button"], a[role="link"], [role="link"], span, div'));
        const rBtn = candidateEls.find(isReplyBtn);
        if (rBtn) {
            const clickNode = rBtn.closest('button, [role="button"], a') || rBtn;
            clickNode.setAttribute('data-dan86-reply-btn', 'true');
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
        thread_items = page.locator('[role="navigation"] [role="listitem"], [role="grid"] [role="row"], div[role="listitem"]')
        found_item = False
        item_count = min(await thread_items.count(), 15)

        for i in range(item_count):
            item = thread_items.nth(i)
            txt = (await item.inner_text() or "").lower()
            if clean_name.lower() in txt:
                logger.info("Tìm thấy hội thoại của [%s] trong danh sách gần nhất!", clean_name)
                await item.click()
                found_item = True
                await human_sleep(2.0, 3.5)
                break

        # 2. Nếu không thấy trong danh sách gần nhất, dùng ô tìm kiếm
        if not found_item:
            search_box = page.locator('input[placeholder*="Tìm kiếm"], input[placeholder*="Search"]').first
            if await search_box.count() > 0 and await search_box.is_visible():
                logger.info("Dùng ô tìm kiếm Messenger gõ tên: %s", clean_name)
                await search_box.click()
                await search_box.fill(clean_name)
                await human_sleep(2.5, 4.0)

                result_items = page.locator('[role="navigation"] [role="listitem"], [role="listbox"] [role="option"]')
                if await result_items.count() > 0:
                    first_res = result_items.first
                    if await first_res.is_visible():
                        await first_res.click()
                        found_item = True
                        await human_sleep(2.0, 3.5)

        # 3. Gửi tin nhắn nếu đã mở được hội thoại
        if found_item:
            composer = page.locator(
                'div[role="textbox"][contenteditable="true"], '
                'textarea[placeholder*="tin nhắn"], '
                'textarea[placeholder*="message"]'
            ).last
            if await composer.count() > 0 and await composer.is_visible():
                await type_human_like(page, composer, private_reply_text)
                await page.keyboard.press("Enter")
                await human_sleep(2.0, 3.5)
                logger.info("Đã gửi tin nhắn riêng cho [%s] qua Fallback Messenger thành công!", clean_name)

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
    """Tự động đóng các popup modal / upsell / banner quảng cáo che khuất giao diện."""
    try:
        modals = page.locator('[data-surface*="upsell"], div[role="dialog"]')
        if await modals.count() > 0:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
            close_btn = page.locator(
                '[aria-label*="Đóng"], [aria-label*="Close"], '
                'div[role="button"]:has-text("Đóng"), div[role="button"]:has-text("Xong"), '
                'button:has-text("Đóng"), button:has-text("Xong")'
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

    # 1. Thử click nút tin nhắn đã được gán data-dan86-msg-btn
    marked_msg_btn = page.locator('[data-dan86-msg-btn="true"]').first
    if await marked_msg_btn.count() > 0 and await marked_msg_btn.is_visible():
        try:
            btn_text_lower = (await marked_msg_btn.inner_text() or "").lower()
            await marked_msg_btn.click()
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
                target = articles[targetIdx];
            }
            if (!target && targetAuthor && targetAuthor !== 'bạn') {
                target = articles.find(a => (a.innerText || '').toLowerCase().includes(targetAuthor.toLowerCase()));
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

            const candidateEls = Array.from(target.querySelectorAll('button, [role="button"], a[role="link"], [role="link"], span, div'));
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
                await type_human_like(page, dialog_box, private_reply_text)
                send_btn = dialog.locator(
                    '[aria-label*="Gửi"], [aria-label*="Send"], '
                    'div[role="button"]:has-text("Gửi"), div[role="button"]:has-text("Send"), '
                    'button:has-text("Gửi"), button:has-text("Send")'
                ).last
                if await send_btn.count() > 0 and await send_btn.is_visible():
                    await send_btn.click()
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

    # TRƯỜNG HỢP 2: Bấm nút 'See Chat' (chuyển sang giao diện chat của khách)
    current_url = page.url.lower()
    is_chat_view = "messenger" in current_url or ("inbox" in current_url and "facebook" not in current_url) or "see chat" in btn_text_lower
    chat_panel = page.locator('[data-pagelet="ChatTab"], [role="main"]:has(div[role="textbox"][aria-label*="tin nhắn"])').first
    if not is_chat_view and await chat_panel.count() > 0 and await chat_panel.is_visible():
        is_chat_view = True

    if is_chat_view:
        composer_selectors = [
            'div[role="textbox"][contenteditable="true"]:not([aria-label*="bình luận"]):not([aria-label*="phản hồi"]):not([placeholder*="bình luận"])',
            'textarea[placeholder*="tin nhắn"]',
            'textarea[placeholder*="message"]',
        ]
        for c_sel in composer_selectors:
            composers = page.locator(c_sel)
            cnt = await composers.count()
            if cnt > 0:
                target_composer = composers.last
                if await target_composer.is_visible():
                    aria = (await target_composer.get_attribute("aria-label") or "").lower()
                    placeholder = (await target_composer.get_attribute("placeholder") or "").lower()
                    if not any(k in aria or k in placeholder for k in ["bình luận", "comment", "phản hồi"]):
                        await type_human_like(page, target_composer, private_reply_text)
                        await page.keyboard.press("Enter")
                        await human_sleep(2.0, 3.5)
                        logger.info("Đã gửi tin nhắn riêng cho [%s] qua giao diện See Chat thành công!", author_name)

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


async def process_facebook_comments_tab(
    page: Page,
    memory: BotMemoryStore,
    dry_run: bool = False,
) -> int:
    """
    Quét tab Bình luận Facebook trên Meta Business Suite:
    1. Lọc sạch tên khách hàng (chống lấy nhầm 'Chỉ báo trạng thái online').
    2. Tự động mở rộng các phản hồi bị ẩn dưới nút 'Xem ... phản hồi'.
    3. Lặp xử lý HẾT tất cả bình luận chưa trả lời trong bài viết đang mở.
    4. Thả Like bình luận.
    5. Random câu trả lời công khai lồng dưới bình luận (Nested Reply).
    6. Tự động gửi tin nhắn riêng (Inbox) cho người bình luận đó:
       - Hỗ trợ Popup Modal
       - Hỗ trợ giao diện See Chat
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
    logger.info("Tìm thấy %d mục bài viết có bình luận cần kiểm tra.", total_items)

    for i in range(total_items):
        try:
            await dismiss_blocking_modals(page)
            item = items_locator.nth(i)
            if not await item.is_visible():
                continue

            preview_text = (await item.inner_text() or "").strip()
            try:
                await item.click(timeout=3000)
            except Exception:
                await dismiss_blocking_modals(page)
                await item.click(timeout=3000)
            await human_sleep(2.0, 3.5)
            current_post_url = page.url

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

                # Tìm candidate đầu tiên cần trả lời theo bộ nhớ (memory)
                target_candidate = None
                target_key = None
                for cand in unreplied_candidates:
                    cand_author = cand.get("author_name") or "bạn"
                    cand_text = cand.get("comment_text") or preview_text
                    cand_idx = int(cand.get("dom_index", 0))

                    if is_page_author_name(cand_author):
                        continue

                    should_rep, comment_key = memory.should_reply_comment(
                        author_name=cand_author,
                        comment_text=cand_text,
                        has_page_reply_in_dom=False,
                        post_id=post_id,
                        dom_index=cand_idx,
                    )
                    if should_rep:
                        target_candidate = cand
                        target_key = comment_key
                        break

                # Nếu tất cả các candidate đều đã được rep trong memory hoặc không hợp lệ -> Dừng vòng lặp bài này
                if target_candidate is None:
                    logger.debug("Tất cả bình luận chưa rep trên bài viết này đã được xử lý trong memory hoặc không hợp lệ.")
                    break

                cand_author = target_candidate.get("author_name") or "bạn"
                cand_text = target_candidate.get("comment_text") or preview_text
                cand_idx = int(target_candidate.get("dom_index", 0))

                public_reply, private_inbox_reply = memory.prepare_comment_and_inbox_replies(cand_author)
                logger.info(
                    "Phát hiện bình luận mới từ [%s] (Post ID: %s, DOM Index: %d, Còn %d cmt chưa rep): %s",
                    cand_author,
                    post_id,
                    cand_idx,
                    len(unreplied_candidates),
                    cand_text[:80],
                )

                if dry_run:
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

                # Bước 1: Thả Like bình luận của khách
                if target_art is not None:
                    like_btn = target_art.locator('div[role="button"]:has-text("Thích"), div[role="button"]:has-text("Like")').first
                    if await like_btn.count() > 0 and await like_btn.is_visible():
                        try:
                            await like_btn.click(timeout=2000)
                            await human_sleep(0.8, 1.5)
                        except Exception:
                            pass

                # Bước 2: Bấm chính xác nút "Trả lời" / "Phản hồi" (Reply) của bình luận khách
                reply_clicked = False
                marked_reply_btn = page.locator('[data-dan86-reply-btn="true"]').first
                if await marked_reply_btn.count() > 0 and await marked_reply_btn.is_visible():
                    try:
                        await marked_reply_btn.click(timeout=2500)
                        reply_clicked = True
                        await human_sleep(1.2, 2.2)
                    except Exception as e_reply:
                        logger.debug("Lỗi bấm nút Trả lời đánh dấu: %s", e_reply)

                if not reply_clicked and target_art is not None:
                    reply_btn = target_art.locator(
                        'div[role="button"]:has-text("Trả lời"), '
                        'span:has-text("Trả lời"), '
                        'div[role="button"]:has-text("Phản hồi"), '
                        'span:has-text("Phản hồi"), '
                        'div[role="button"]:has-text("Reply")'
                    ).first
                    if await reply_btn.count() > 0 and await reply_btn.is_visible():
                        try:
                            await reply_btn.click(timeout=2500)
                            reply_clicked = True
                            await human_sleep(1.2, 2.2)
                        except Exception as e_reply:
                            logger.warning("Lỗi bấm nút Trả lời trong comment article: %s", e_reply)

                # Tìm ô nhập phản hồi lồng nhau cấp 2 (nested reply box)
                nested_box = page.locator('div[role="textbox"]:focus').first
                if await nested_box.count() == 0 or not await nested_box.is_visible():
                    nested_box = page.locator(
                        'div[role="textbox"][aria-label*="Trả lời với vai trò"], '
                        'div[role="textbox"][aria-label*="Reply as"], '
                        'div[role="textbox"][aria-label*="Viết câu trả lời"], '
                        'div[role="textbox"][aria-label*="Viết phản hồi"]'
                    ).first

                if (await nested_box.count() == 0 or not await nested_box.is_visible()) and target_art is not None:
                    nested_box = target_art.locator('div[role="textbox"]').first

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
                    logger.info("Đã gửi phản hồi bình luận công khai cho [%s] (Nested Reply: %s).", cand_author, reply_clicked)

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
                else:
                    logger.warning("Không tìm thấy ô nhập nested reply hợp lệ cho bình luận của [%s].", cand_author)
                    break

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
