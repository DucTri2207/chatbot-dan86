import asyncio
import json
import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        # 1. Kiểm tra comments page
        url = "https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512"
        print(f"Navigating to {url}...")
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(6)
        print(f"Current URL: {page.url}")
        print(f"Page title: {await page.title()}")
        
        # Chụp ảnh màn hình để xem giao diện hiện tại
        os.makedirs("logs", exist_ok=True)
        await page.screenshot(path="logs/comments_page.png")
        print("Saved screenshot to logs/comments_page.png")
        
        # Phân tích DOM của danh sách và nội dung comment
        dom_dump = await page.evaluate('''() => {
            const listItems = Array.from(document.querySelectorAll('[role="navigation"] [role="listitem"], [role="grid"] [role="row"], div[role="listitem"]'));
            const listInfo = listItems.slice(0, 5).map((el, i) => ({
                index: i,
                innerText: el.innerText,
                innerHTMLSnippet: el.innerHTML.slice(0, 300)
            }));
            
            // Tìm các button trong trang
            const buttons = Array.from(document.querySelectorAll('button, div[role="button"], span[role="button"]'))
                .filter(b => b.innerText && b.innerText.trim().length > 0)
                .map(b => ({
                    tag: b.tagName,
                    text: b.innerText.trim(),
                    ariaLabel: b.getAttribute('aria-label') || '',
                    rect: { top: b.getBoundingClientRect().top, left: b.getBoundingClientRect().left }
                }))
                .filter(b => b.rect.left > 200);

            return {
                listCount: listItems.length,
                listItems: listInfo,
                buttons: buttons.slice(0, 30)
            };
        }''')
        print("DOM Dump:")
        print(json.dumps(dom_dump, ensure_ascii=False, indent=2))
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect())
