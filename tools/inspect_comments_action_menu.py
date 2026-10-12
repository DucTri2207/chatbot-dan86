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

async def inspect():
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

        # Inspect button with aria-label="Xong"
        xong_btn = p.locator('[aria-label="Xong"]')
        print("xong_btn count:", await xong_btn.count())
        for i in range(await xong_btn.count()):
            elem = xong_btn.nth(i)
            print(f"xong_btn #{i}:", await elem.evaluate('el => el.outerHTML'))

        # Inspect button with aria-label containing "Hành động"
        action_btn = p.locator('[aria-label*="Hành động đối với bài viết"]')
        print("action_btn count:", await action_btn.count())
        if await action_btn.count() > 0:
            elem = action_btn.first
            print("action_btn outerHTML:", await elem.evaluate('el => el.outerHTML'))
            # Click action_btn to see menu
            await elem.click()
            await asyncio.sleep(2)
            menu_items = await p.evaluate('''() => {
                const items = Array.from(document.querySelectorAll('[role="menuitem"], [role="menu"] *'));
                return items.map(el => (el.innerText || '').trim()).filter(Boolean);
            }''')
            print("Action menu items:", menu_items)
            
        await b.close()

if __name__ == "__main__":
    asyncio.run(inspect())
