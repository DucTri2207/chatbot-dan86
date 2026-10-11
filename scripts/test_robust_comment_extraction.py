import asyncio
import json
import re
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

SYSTEM_BLACKLIST = [
    "chỉ báo trạng thái online",
    "online status indicator",
    "đang hoạt động",
    "đang có mặt",
    "hộp thư",
    "chưa đọc",
    "bình luận trên trang",
    "trao đổi thêm",
    "tạo quảng cáo",
    "dần86",
    "dan86",
    "bá lộc green",
    "ba loc green",
]

def clean_author_name(raw_name: str) -> str:
    if not raw_name:
        return "bạn"
    cleaned = raw_name.strip()
    # Lọc bỏ ký tự bullet, thời gian, etc.
    cleaned = cleaned.split("·")[0].split("•")[0].strip()
    cleaned = cleaned.split("\n")[0].strip()
    
    # Kiểm tra blacklist
    low = cleaned.lower()
    if any(b in low for b in SYSTEM_BLACKLIST):
        return "bạn"
    if len(cleaned) < 2 or len(cleaned) > 50:
        return "bạn"
    return cleaned

async def test_robust_comment_extraction():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        page = await context.new_page()
        await page.goto("https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512", wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        
        # Đánh giá cấu trúc tất cả articles trong panel chi tiết bên phải
        results = await page.evaluate('''() => {
            const articles = Array.from(document.querySelectorAll('[role="article"]'));
            const blacklist = [
                "chỉ báo trạng thái online",
                "online status indicator",
                "đang hoạt động",
                "đang có mặt",
                "dần86",
                "dan86"
            ];
            
            const comments = [];
            for (let i = 0; i < articles.length; i++) {
                const art = articles[i];
                const aria = (art.getAttribute('aria-label') || '').trim();
                const inner = (art.innerText || '').trim();
                const lowerInner = inner.toLowerCase();
                const lowerAria = aria.toLowerCase();
                
                // 1. Bỏ qua các widget hệ thống không phải comment (ví dụ chấm online status)
                if (lowerInner.includes("chỉ báo trạng thái online") || lowerAria.includes("chỉ báo trạng thái online")) {
                    continue;
                }
                
                // 2. Kiểm tra nếu là reply của chính Fanpage
                const isPageReply = lowerAria.includes("dưới tên dần86farm") || 
                                    lowerInner.startsWith("dần86farm") || 
                                    lowerInner.includes("tác giả\\nđã gửi tin nhắn");
                                    
                // 3. Trích xuất tên tác giả
                let authorName = "";
                // Cách a: Phân tích aria-label: "Bình luận dưới tên [Tên Khách] vào [thời gian]"
                const mAria = aria.match(/Bình luận dưới tên\\s+(.+?)(?:\\s+vào\\s+|$)/i);
                if (mAria && mAria[1]) {
                    authorName = mAria[1].trim();
                }
                
                // Cách b: Tìm link hoặc button tên tác giả
                if (!authorName) {
                    const authorBtn = art.querySelector('div[role="button"]:not([aria-label]), a[role="link"]');
                    if (authorBtn && authorBtn.innerText) {
                        authorName = authorBtn.innerText.trim();
                    }
                }
                
                // Cách c: Phân tích các dòng text của article
                if (!authorName) {
                    const lines = inner.split('\\n').map(s => s.trim()).filter(Boolean);
                    for (const line of lines) {
                        const low = line.toLowerCase();
                        if (low.length >= 2 && !blacklist.some(b => low.includes(b)) && !line.includes('tuần') && !line.includes('ngày') && !line.includes('phút') && !line.includes('giờ') && line !== '·' && line !== 'Ib' && line !== 'Trả lời' && line !== 'Ẩn') {
                            authorName = line;
                            break;
                        }
                    }
                }
                
                // 4. Trích xuất nội dung bình luận
                let commentText = "";
                const lines = inner.split('\\n').map(s => s.trim()).filter(Boolean);
                // Tìm dòng text không phải tên, không phải nút hành động
                const contentLines = lines.filter(l => {
                    const low = l.toLowerCase();
                    if (l === authorName || low.includes('tuần trước') || low.includes('ngày trước') || low.includes('phút trước') || low.includes('giờ trước') || low.includes('tuần') || low.includes('ngày') || low.includes('phút')) return false;
                    if (['trả lời', 'ẩn', 'see chat', 'nhắn tin', 'gửi tin nhắn', 'thích', 'bày tỏ cảm xúc', '·', 'tác giả'].includes(low)) return false;
                    return true;
                });
                commentText = contentLines.join(" ");

                // 5. Tìm nút Trả lời và nút Nhắn tin (Private Message)
                const actionEls = Array.from(art.querySelectorAll('[role="button"], span, div')).filter(el => el.children.length === 0);
                const replyBtn = actionEls.find(el => {
                    const t = (el.innerText || '').trim();
                    return t === 'Trả lời' || t === 'Reply';
                });
                const msgBtn = actionEls.find(el => {
                    const t = (el.innerText || '').trim();
                    return t === 'Gửi tin nhắn' || t === 'Nhắn tin' || t === 'See Chat' || t === 'Message' || t === 'Send message';
                });

                comments.push({
                    articleIndex: i,
                    ariaLabel: aria,
                    isPageReply: isPageReply,
                    authorName: authorName || "bạn",
                    commentText: commentText,
                    hasReplyBtn: !!replyBtn,
                    msgBtnText: msgBtn ? msgBtn.innerText.trim() : null
                });
            }
            return comments;
        }''')
        
        print(f"Extracted comments ({len(results)}):")
        for c in results:
            print(json.dumps(c, ensure_ascii=False, indent=2))
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_robust_comment_extraction())
