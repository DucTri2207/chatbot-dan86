import asyncio
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

async def inspect_article():
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
        
        info = await page.evaluate('''() => {
            const articles = Array.from(document.querySelectorAll('[role="article"]'));
            return articles.map((art, idx) => {
                const ariaLabel = art.getAttribute('aria-label') || '';
                
                // Tìm tất cả các link hoặc text có thể là tên tác giả
                const authorLink = art.querySelector('a[role="link"], span[dir="auto"]');
                const authorLinkText = authorLink ? authorLink.innerText : '';
                
                // Tìm các nút hành động bên trong article
                const buttons = Array.from(art.querySelectorAll('div[role="button"], span[role="button"], button, a[role="button"]'))
                    .map(b => ({
                        tag: b.tagName,
                        role: b.getAttribute('role'),
                        ariaLabel: b.getAttribute('aria-label') || '',
                        text: (b.innerText || '').trim()
                    }));
                
                // Kiểm tra các element text có text "Trả lời", "Nhắn tin", "Gửi tin nhắn", "See Chat", "Gửi tin nhắn riêng"
                const allActionSpans = Array.from(art.querySelectorAll('span, div'))
                    .filter(el => ['Trả lời', 'Reply', 'Gửi tin nhắn', 'Nhắn tin', 'Message', 'Send message', 'See Chat'].includes((el.innerText || '').trim()))
                    .map(el => ({
                        tag: el.tagName,
                        role: el.getAttribute('role'),
                        ariaLabel: el.getAttribute('aria-label') || '',
                        text: el.innerText.trim(),
                        className: el.className
                    }));

                return {
                    idx,
                    ariaLabel,
                    authorLinkText,
                    buttons,
                    allActionSpans,
                    fullInnerText: art.innerText
                };
            });
        }''')
        
        print(f"Total articles found: {len(info)}")
        for item in info:
            print(f"=== Article #{item['idx']} ===")
            print("AriaLabel:", item["ariaLabel"])
            print("AuthorLinkText:", item["authorLinkText"])
            print("Action Spans:", item["allActionSpans"])
            print("Buttons:", item["buttons"])
            print("Full Text:\n", item["fullInnerText"])
            print("-" * 50)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_article())
