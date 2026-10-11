import asyncio
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

async def inspect_comment_buttons():
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
        
        # Lấy article 1
        art = page.locator('[role="article"]').nth(1)
        await art.hover()
        await asyncio.sleep(1)
        
        buttons = await art.evaluate('''el => {
            return Array.from(el.querySelectorAll('*'))
                .filter(b => b.children.length === 0 && (b.innerText || b.getAttribute('aria-label') || '').trim().length > 0)
                .map(b => ({
                    tag: b.tagName,
                    text: (b.innerText || '').trim(),
                    aria: (b.getAttribute('aria-label') || '').trim(),
                    role: b.getAttribute('role')
                }));
        }''')
        
        print(f"Buttons on hovered article: {len(buttons)}")
        for b in buttons:
            print(b)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_comment_buttons())
