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
        
        await page.goto(f"https://business.facebook.com/latest/inbox/messenger?asset_id={PAGE_ASSET_ID}", wait_until="domcontentloaded")
        await asyncio.sleep(5)
        
        fb_tab = page.locator('div[role="tab"]:has-text("Bình luận trên Facebook"), button:has-text("Bình luận trên Facebook")').first
        if await fb_tab.count() > 0:
            print("Found FB comments tab, clicking...")
            await fb_tab.click()
            await asyncio.sleep(4)
            await page.screenshot(path="logs/audit/tab_fb_comments_view.png")
            
            # Check filter button in comments tab
            filter_btn = page.locator('[aria-label="Bộ lọc"]').first
            print("Filter button count in comments:", await filter_btn.count())
            if await filter_btn.count() > 0:
                await filter_btn.click()
                await asyncio.sleep(2)
                dialog_text = await page.evaluate('''() => {
                    const d = document.querySelector('[role="dialog"]') || document.body;
                    return d.innerText;
                }''')
                print("Filter dialog text in comments tab:", dialog_text[:300].replace('\n', ' | '))
                
        await b.close()

if __name__ == "__main__":
    asyncio.run(run())
