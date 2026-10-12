import asyncio
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from playwright.async_api import async_playwright

PAGE_ASSET_ID = "104011958817512"

async def run():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        page = await ctx.new_page()
        
        # Check Facebook comments
        fb_comments_url = f"https://business.facebook.com/latest/inbox/fb_comments?asset_id={PAGE_ASSET_ID}"
        print(f"Navigating to {fb_comments_url}...")
        await page.goto(fb_comments_url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        await page.screenshot(path="logs/audit/fb_comments_tab.png")
        
        # Check filter on FB comments
        filter_btn = page.locator('[aria-label="Bộ lọc"]').first
        print(f"FB comments filter button count: {await filter_btn.count()}")
        if await filter_btn.count() > 0:
            await filter_btn.click()
            await asyncio.sleep(2)
            await page.screenshot(path="logs/audit/fb_comments_filter_dialog.png")
            
            # Check what's inside
            dialog_text = await page.evaluate('''() => {
                const d = document.querySelector('[role="dialog"]') || document.body;
                return d.innerText;
            }''')
            print("Dialog text snippet:", dialog_text[:300].replace('\n', ' | '))
            
            # Check if Xong exists
            xong_exists = 'Xong' in dialog_text
            print(f"Is 'Xong' an option in FB comments? {xong_exists}")
            
        await b.close()

if __name__ == "__main__":
    asyncio.run(run())
