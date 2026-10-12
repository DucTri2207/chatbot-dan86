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

PAGE_ASSET_ID = "104011958817512"

async def check_comments_xong():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        p = await ctx.new_page()
        url = f"https://business.facebook.com/latest/inbox/facebook?asset_id={PAGE_ASSET_ID}"
        print(f"Navigating to {url}...")
        await p.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(5)
        
        filter_btn = p.locator('[aria-label="Bộ lọc"]').first
        print("Filter btn count:", await filter_btn.count())
        if await filter_btn.count() > 0:
            await filter_btn.click()
            await asyncio.sleep(2)
            
            # Click Xong
            xong_elem = p.locator('[role="dialog"]').locator('div:text-is("Xong"), span:text-is("Xong")').first
            print("Xong elem count:", await xong_elem.count())
            if await xong_elem.count() > 0:
                await xong_elem.click()
                await asyncio.sleep(1)
                
            apply_btn = p.locator('[role="dialog"]').locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first
            print("Apply btn count:", await apply_btn.count())
            if await apply_btn.count() > 0:
                await apply_btn.click()
                await asyncio.sleep(4)
                
        await p.screenshot(path="logs/audit/fb_comments_xong_applied.png")
        
        # Check threads / comments in Xong view
        threads = await p.evaluate('''() => {
            const nodes = Array.from(document.querySelectorAll('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]'));
            return nodes.map(n => {
                const text = (n.innerText || '').trim();
                const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                return {
                    name: lines[0] || '',
                    time: lines[1] || '',
                    preview: lines[2] || '',
                    full: text.replace(/\\n+/g, ' | ')
                };
            }).filter(n => n.name && n.name.length > 1 && !['tìm kiếm', 'quản lý', 'hộp thư', 'messenger', 'chưa đọc', 'ưu tiên'].some(k => n.name.toLowerCase().includes(k)));
        }''')
        
        empty_text = await p.evaluate('''() => {
            return document.body.innerText.includes('Không có kết quả nào khớp với bộ lọc') || 
                   document.body.innerText.includes('Không có bình luận') ||
                   document.body.innerText.includes('Không có tin nhắn');
        }''')
        
        print(f"RESULTS FOR FB COMMENTS XONG FILTER:")
        print(f"Empty state message present: {empty_text}")
        print(f"Item count in Xong filter: {len(threads)}")
        for t in threads:
            print(f"  - {t['name']}: {t.get('time', '')}")
            
        await b.close()

if __name__ == "__main__":
    asyncio.run(check_comments_xong())
