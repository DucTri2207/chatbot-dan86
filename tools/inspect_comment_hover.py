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
                
        # Hover over the first post item
        item = p.locator('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]').first
        if await item.count() > 0:
            print("Hovering over first item...")
            await item.hover()
            await asyncio.sleep(1.5)
            await p.screenshot(path="logs/audit/fb_comment_item_hover.png")
            
            # Inspect all interactive elements inside or near this item
            item_html = await item.evaluate('el => el.innerHTML')
            print("First item HTML snippet:", item_html[:500])
            
            # Check any buttons/icons that appeared on hover
            hover_buttons = await p.evaluate('''() => {
                const list = document.querySelector('[role="navigation"], div[role="grid"], div[style*="overflow"]');
                const btns = Array.from((list || document.body).querySelectorAll('[role="button"], button, svg'));
                return btns.map(b => ({
                    tag: b.tagName,
                    ariaLabel: b.getAttribute('aria-label') || '',
                    title: b.getAttribute('title') || '',
                    text: (b.innerText || '').trim()
                })).filter(b => b.ariaLabel || b.title);
            }''')
            print("Buttons found in/near list:", json.dumps(hover_buttons[:20], ensure_ascii=False, indent=2))
            
        await b.close()

if __name__ == "__main__":
    asyncio.run(inspect())
