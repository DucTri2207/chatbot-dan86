import asyncio
import json
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from playwright.async_api import async_playwright

PAGE_ASSET_ID = "104011958817512"

async def test_move_comment():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        p = await ctx.new_page()
        url = f"https://business.facebook.com/latest/inbox/facebook?asset_id={PAGE_ASSET_ID}"
        await p.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(5)
        
        # Apply Xong filter
        filter_btn = p.locator('[aria-label="Bộ lọc"]').first
        if await filter_btn.count() > 0:
            await filter_btn.click()
            await asyncio.sleep(2)
            xong_elem = p.locator('[role="dialog"]').locator('div:text-is("Xong"), span:text-is("Xong")').first
            if await xong_elem.count() > 0:
                await xong_elem.click()
                await asyncio.sleep(1)
            apply_btn = p.locator('[role="dialog"]').locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first
            if await apply_btn.count() > 0:
                await apply_btn.click()
                await asyncio.sleep(4)

        # Check total move buttons visible
        move_btns = p.locator('div[aria-label="Chuyển đến thư mục Chính"], [role="gridcell"][aria-label="Chuyển đến thư mục Chính"]')
        count = await move_btns.count()
        print(f"Total 'Chuyển đến thư mục Chính' buttons found: {count}")
        
        if count > 0:
            # Check outerHTML of first button
            print("First move button outerHTML:", await move_btns.first.evaluate('el => el.outerHTML'))
            # Let's test clicking the first button
            print("Clicking first move button...")
            await move_btns.first.click()
            await asyncio.sleep(4)
            await p.screenshot(path="logs/audit/fb_comment_after_one_move.png")
            
            # Check count again
            new_count = await move_btns.count()
            print(f"After move, 'Chuyển đến thư mục Chính' buttons count: {new_count}")

        await b.close()

if __name__ == "__main__":
    asyncio.run(test_move_comment())
