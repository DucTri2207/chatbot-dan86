import asyncio
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

async def scan_posts():
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
        
        # Click từng post ở sidebar
        for post_idx in range(5):
            print(f"\n--- Checking Post Index {post_idx} ---")
            # Tìm danh sách post ở sidebar
            sidebar_posts = page.locator('div[role="listitem"], [role="grid"] [role="row"], div[tabindex="0"], div[tabindex="-1"]').filter(has_text="bình luận")
            if await sidebar_posts.count() > post_idx:
                await sidebar_posts.nth(post_idx).click()
                await asyncio.sleep(3)
                
            # Kiểm tra các article trong post này
            arts = await page.evaluate('''() => {
                const articles = Array.from(document.querySelectorAll('[role="article"]'));
                return articles.map(a => {
                    const btns = Array.from(a.querySelectorAll('[role="button"], span, div'))
                        .filter(b => b.children.length === 0 && (b.innerText || '').trim().length > 0)
                        .map(b => b.innerText.trim());
                    return {
                        ariaLabel: a.getAttribute('aria-label') || '',
                        text: a.innerText.slice(0, 100).replace(/\\n/g, ' | '),
                        allButtonTexts: Array.from(new Set(btns))
                    };
                });
            }''')
            
            for a in arts:
                print(f"Article aria='{a['ariaLabel'][:50]}' buttons={a['allButtonTexts']}")
                
        await browser.close()

if __name__ == "__main__":
    asyncio.run(scan_posts())
