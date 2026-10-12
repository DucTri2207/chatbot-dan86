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
        
        # Hover over the first thread
        first_thread = page.locator('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]').first
        print("Hovering over first thread...")
        await first_thread.hover()
        await asyncio.sleep(2)
        await page.screenshot(path="logs/hover_thread.png")
        
        # Check buttons inside or near first_thread
        hover_buttons = await page.evaluate('''() => {
            const btns = Array.from(document.querySelectorAll('button, div[role="button"]'));
            return btns.map(b => {
                const r = b.getBoundingClientRect();
                return {
                    aria: b.getAttribute('aria-label') || '',
                    title: b.getAttribute('title') || '',
                    text: (b.innerText || '').trim(),
                    rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}
                };
            }).filter(b => b.rect.x >= 280 && b.rect.x <= 360 && b.rect.y >= 300 && b.rect.y <= 400);
        }''')
        print("Hover buttons on thread:", json.dumps(hover_buttons, ensure_ascii=False, indent=2))
        
        # Also check the three dots button in chat header
        dots_btn = page.locator('[aria-label="Tùy chọn khác"], [aria-label*="Tùy chọn"]').first
        print("Dots button in header count:", await dots_btn.count(), "visible:", await dots_btn.is_visible())
        if await dots_btn.count() > 0:
            await dots_btn.click()
            await asyncio.sleep(1.5)
            await page.screenshot(path="logs/dots_menu_click.png")
            menu_items = await page.evaluate('''() => {
                const items = Array.from(document.querySelectorAll('[role="menuitem"], div[role="button"]'));
                return items.map(it => ({
                    role: it.getAttribute('role'),
                    text: (it.innerText || '').trim(),
                    aria: it.getAttribute('aria-label') || ''
                })).filter(it => it.text && (it.text.includes('Hộp thư') || it.text.includes('Chuyển') || it.text.includes('Xong')));
            }''')
            print("Menu items in dots menu:", json.dumps(menu_items, ensure_ascii=False, indent=2))
            
        await b.close()

if __name__ == "__main__":
    asyncio.run(main())
