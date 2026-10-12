import asyncio
import sys
import os

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
        
        threads = await p.evaluate('''() => {
            const nodes = Array.from(document.querySelectorAll('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]'));
            return nodes.map(n => {
                const text = (n.innerText || '').trim();
                const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                return { name: lines[0] || '', time: lines[1] || '', preview: lines[2] || '' };
            }).filter(n => n.name && n.name.length > 1 && !['tìm kiếm', 'quản lý', 'hộp thư', 'messenger', 'chưa đọc', 'ưu tiên'].some(k => n.name.toLowerCase().includes(k)));
        }''')
        print(f"CURRENT THREADS IN XONG (COUNT: {len(threads)}):")
        for idx, t in enumerate(threads):
            print(f"  {idx+1}. {t['name']} ({t['time']}) - {t['preview'][:40]}")
            
        await b.close()

if __name__ == "__main__":
    asyncio.run(run())
