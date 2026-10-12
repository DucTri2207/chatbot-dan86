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

async def run():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(storage_state='state/fb_storage_state.json', viewport={'width': 1440, 'height': 900}, locale='vi-VN')
        p = await ctx.new_page()
        await p.goto('https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512', wait_until='domcontentloaded')
        await asyncio.sleep(4)
        
        # Apply Xong
        f_btn = p.locator('[aria-label="Bộ lọc"]').first
        await f_btn.click()
        await asyncio.sleep(1.5)
        await p.locator('div:text-is("Xong"), span:text-is("Xong")').last.click()
        await asyncio.sleep(1)
        await p.locator('button:has-text("Áp dụng")').first.click()
        await asyncio.sleep(4)
        
        # Click first thread
        th = p.locator('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]').first
        await th.click(position={'x': 150, 'y': 35})
        await asyncio.sleep(2)
        
        # Check all buttons in middle header (x: 650..800, y: 200..280)
        btns = await p.evaluate('''() => {
            const all = Array.from(document.querySelectorAll('*'));
            return all.map(el => {
                const r = el.getBoundingClientRect();
                return {
                    tag: el.tagName,
                    role: el.getAttribute('role'),
                    aria: el.getAttribute('aria-label') || '',
                    title: el.getAttribute('title') || '',
                    className: el.className || '',
                    html: el.outerHTML.slice(0, 150),
                    rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}
                };
            }).filter(e => e.rect.x >= 700 && e.rect.x <= 780 && e.rect.y >= 220 && e.rect.y <= 280 && e.rect.w >= 20 && e.rect.h >= 20);
        }''')
        print('Header dots candidates:', json.dumps(btns[:5], ensure_ascii=False, indent=2))
        await b.close()

if __name__ == "__main__":
    asyncio.run(run())
