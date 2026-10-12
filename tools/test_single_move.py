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

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        page = await ctx.new_page()
        await page.goto("https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512", wait_until="domcontentloaded")
        await asyncio.sleep(5)
        
        # Apply Xong filter
        filter_btn = page.locator('[aria-label="Bộ lọc"]').first
        await filter_btn.click()
        await asyncio.sleep(2)
        xong_chip = page.locator('div:text-is("Xong"), span:text-is("Xong")').last
        await xong_chip.click()
        await asyncio.sleep(1)
        apply_btn = page.locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first
        await apply_btn.click()
        await asyncio.sleep(4)
        
        # Get name of first thread
        first_thread = page.locator('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]').first
        thread_text = await first_thread.inner_text()
        first_name = thread_text.split('\n')[0].strip()
        print(f"Testing move for first thread: '{first_name}'")
        
        # Click dots button in header
        dots_btn = page.locator('[aria-label="Tùy chọn khác"]').last
        print("Clicking dots button in header...")
        await dots_btn.click()
        await asyncio.sleep(1.5)
        
        move_item = page.locator('[role="menuitem"]:has-text("Chuyển về Hộp thư đến")').first
        print("Move item count:", await move_item.count())
        if await move_item.count() > 0:
            print("Clicking [Chuyển về Hộp thư đến]...")
            await move_item.click()
            await asyncio.sleep(4)
            print(f"Successfully clicked move for '{first_name}'!")
            
            # Check remaining first thread name
            new_first = page.locator('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]').first
            new_text = await new_first.inner_text()
            new_name = new_text.split('\n')[0].strip()
            print(f"New first thread in Xong folder is now: '{new_name}' (was: '{first_name}')")
            
        await b.close()

if __name__ == "__main__":
    asyncio.run(main())
