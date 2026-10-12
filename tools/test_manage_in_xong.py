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
        await p.locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first.click()
        await asyncio.sleep(4)
        
        # Now click Quản lý
        manage_btn = p.locator('div[role="button"]:has-text("Quản lý"), button:has-text("Quản lý")').first
        print("Manage button count:", await manage_btn.count())
        await manage_btn.click()
        await asyncio.sleep(2)
        await p.screenshot(path='logs/test_manage_in_xong.png')
        
        # Print all elements on screen
        els = await p.evaluate('''() => {
            const all = Array.from(document.querySelectorAll('*'));
            return all.map(el => {
                const r = el.getBoundingClientRect();
                return {
                    tag: el.tagName,
                    role: el.getAttribute('role'),
                    text: (el.innerText || '').trim(),
                    aria: el.getAttribute('aria-label') || '',
                    rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}
                };
            }).filter(e => e.text && (e.text.includes('Chọn tất cả') || e.text.includes('Hộp thư') || e.text.includes('Xong') || e.text.includes('Đã chọn')) && e.rect.w > 10);
        }''')
        print("Matching elements in Xong manage view:", json.dumps(els, ensure_ascii=False, indent=2))
        
        await b.close()

if __name__ == "__main__":
    asyncio.run(run())
