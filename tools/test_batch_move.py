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
        
        # Apply Xong filter
        f_btn = p.locator('[aria-label="Bộ lọc"]').first
        await f_btn.click()
        await asyncio.sleep(1.5)
        await p.locator('div:text-is("Xong"), span:text-is("Xong")').last.click()
        await asyncio.sleep(1)
        await p.locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first.click()
        await asyncio.sleep(4)
        
        # Click Quản lý
        manage_btn = p.locator('div[role="button"]:has-text("Quản lý"), button:has-text("Quản lý")').first
        await manage_btn.click()
        await asyncio.sleep(2)
        
        # Click "Chọn tất cả những gì đang hiển thị"
        select_all = p.get_by_text('Chọn tất cả những gì đang hiển thị', exact=False).first
        print("select_all count:", await select_all.count())
        if await select_all.count() > 0:
            await select_all.click()
            await asyncio.sleep(2)
            
            # Click "Chuyển đến thư mục Chính"
            move_btn = p.locator('div[role="button"]:has-text("Chuyển đến thư mục Chính")').first
            print("move_btn count:", await move_btn.count(), "visible:", await move_btn.is_visible())
            if await move_btn.count() > 0:
                print("Clicking 'Chuyển đến thư mục Chính'...")
                await move_btn.click()
                await asyncio.sleep(5)
                await p.screenshot(path='logs/test_after_move_executed.png')
                print("Move executed! Checking remaining...")
        
        # Check threads in Xong folder now
        threads = await p.evaluate('''() => {
            const nodes = Array.from(document.querySelectorAll('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]'));
            return nodes.map(n => {
                const text = (n.innerText || '').trim();
                const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                return lines[0] || '';
            }).filter(n => n.length > 1 && !['tìm kiếm', 'quản lý', 'hộp thư', 'messenger', 'chưa đọc', 'ưu tiên'].some(k => n.toLowerCase().includes(k)));
        }''')
        print(f"Threads remaining in Xong after move ({len(threads)}):")
        for idx, t in enumerate(threads[:10]):
            print(f"  {idx+1}. {t}")
            
        await b.close()

if __name__ == "__main__":
    asyncio.run(run())
