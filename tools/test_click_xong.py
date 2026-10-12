import asyncio
import json
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        page = await ctx.new_page()
        print("Navigating to messenger inbox...")
        await page.goto("https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512", wait_until="domcontentloaded")
        await asyncio.sleep(5)
        
        # Click "Bộ lọc"
        filter_btn = page.locator('[aria-label="Bộ lọc"], button[aria-label="Bộ lọc"]').first
        print("Clicking Bộ lọc...")
        await filter_btn.click()
        await asyncio.sleep(2)
        
        # Click "Xong" in the dropdown menu
        xong_item = page.locator('div:text-is("Xong"), span:text-is("Xong")').first
        print("Found Xong item count:", await xong_item.count())
        if await xong_item.count() > 0:
            print("Clicking Xong...")
            await xong_item.click()
            await asyncio.sleep(4)
            print("Current URL:", page.url)
            await page.screenshot(path="logs/after_click_xong_folder.png")
            
            # Read thread list now
            threads = await page.evaluate('''() => {
                const nodes = Array.from(document.querySelectorAll('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"], [role="row"]'));
                return nodes.map((n, idx) => {
                    const rect = n.getBoundingClientRect();
                    const text = (n.innerText || '').trim().replace(/\\n+/g, ' | ');
                    return { idx, text, rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)} };
                }).filter(n => n.rect.x >= 60 && n.rect.x <= 360 && n.rect.y >= 300 && n.rect.h >= 40);
            }''')
            print(f"Threads in Xong folder after click ({len(threads)}):")
            for t in threads:
                print(f"  {t['text'][:100]}")
                
        await b.close()

if __name__ == "__main__":
    asyncio.run(main())
