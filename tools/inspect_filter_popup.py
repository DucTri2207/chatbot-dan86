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
        await page.goto("https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512", wait_until="domcontentloaded")
        await asyncio.sleep(5)
        
        # Click "Bộ lọc"
        filter_btn = page.locator('[aria-label="Bộ lọc"], button[aria-label="Bộ lọc"]').first
        print("Filter button count:", await filter_btn.count(), "visible:", await filter_btn.is_visible())
        if await filter_btn.count() > 0:
            await filter_btn.click()
            await asyncio.sleep(2)
            await page.screenshot(path="logs/filter_popup_opened.png")
            
            # Inspect all menu items or dialog elements
            menu_items = await page.evaluate('''() => {
                const els = Array.from(document.querySelectorAll('[role="menuitem"], [role="option"], [role="radio"], [role="checkbox"], div[role="button"], span, div'));
                return els.map(el => {
                    const rect = el.getBoundingClientRect();
                    return {
                        tag: el.tagName,
                        role: el.getAttribute('role'),
                        text: (el.innerText || '').trim(),
                        aria: el.getAttribute('aria-label') || '',
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}
                    };
                }).filter(e => e.rect.w > 40 && e.rect.h > 15 && e.rect.y > 100 && e.rect.y < 800 && e.rect.x > 50 && e.rect.x < 600 && e.text && (
                    e.text.includes('Xong') || e.text.includes('Chính') || e.text.includes('Spam') || e.text.includes('Thư mục') || e.text.includes('Hộp thư')
                ));
            }''')
            print("Filter menu candidates:", json.dumps(menu_items, ensure_ascii=False, indent=2))
            
        await b.close()

if __name__ == "__main__":
    asyncio.run(main())
