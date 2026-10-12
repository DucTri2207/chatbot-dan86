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

async def run():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        page = await ctx.new_page()
        print("Navigating to Messenger...")
        await page.goto("https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512", wait_until="domcontentloaded")
        await asyncio.sleep(5)
        
        filter_btn = page.locator('[aria-label="Bộ lọc"]').first
        if await filter_btn.count() > 0:
            await filter_btn.click()
            await asyncio.sleep(2)
            
            # Scroll down dialog
            await page.evaluate('''() => {
                const dialog = document.querySelector('[role="dialog"]');
                if (dialog) {
                    const scrollable = Array.from(dialog.querySelectorAll('*')).filter(el => el.scrollHeight > el.clientHeight && el.clientHeight > 200);
                    for (const s of scrollable) {
                        s.scrollTop = s.scrollHeight;
                    }
                }
            }''')
            await asyncio.sleep(1)
            
            # Click Xong
            xong_elem = page.locator('[role="dialog"]').locator('div:text-is("Xong"), span:text-is("Xong")').first
            print("Xong elem count:", await xong_elem.count())
            await xong_elem.click()
            await asyncio.sleep(1)
            
            # Click Áp dụng
            apply_btn = page.locator('[role="dialog"]').locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first
            print("Apply btn count:", await apply_btn.count())
            await apply_btn.click()
            await asyncio.sleep(4)
            
        await page.screenshot(path="logs/audit/messenger_actual_xong_filter.png")
        
        # Check threads in Xong view
        threads = await page.evaluate('''() => {
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
        
        empty_text = await page.evaluate('''() => {
            return document.body.innerText.includes('Không có kết quả nào khớp với bộ lọc');
        }''')
        
        print(f"RESULTS FOR MESSENGER XONG FILTER:")
        print(f"Empty state message present: {empty_text}")
        print(f"Thread count in Xong filter: {len(threads)}")
        if threads:
            for t in threads:
                print(f"  - {t['name']}")
                
        # NOW DO THE EXACT SAME FOR "TẤT CẢ TIN NHẮN" (ALL)
        print("\nNavigating to ALL inbox...")
        await page.goto("https://business.facebook.com/latest/inbox/all?asset_id=104011958817512", wait_until="domcontentloaded")
        await asyncio.sleep(5)
        
        filter_btn_all = page.locator('[aria-label="Bộ lọc"]').first
        if await filter_btn_all.count() > 0:
            await filter_btn_all.click()
            await asyncio.sleep(2)
            await page.evaluate('''() => {
                const dialog = document.querySelector('[role="dialog"]');
                if (dialog) {
                    const scrollable = Array.from(dialog.querySelectorAll('*')).filter(el => el.scrollHeight > el.clientHeight && el.clientHeight > 200);
                    for (const s of scrollable) {
                        s.scrollTop = s.scrollHeight;
                    }
                }
            }''')
            await asyncio.sleep(1)
            xong_elem_all = page.locator('[role="dialog"]').locator('div:text-is("Xong"), span:text-is("Xong")').first
            await xong_elem_all.click()
            await asyncio.sleep(1)
            apply_btn_all = page.locator('[role="dialog"]').locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first
            await apply_btn_all.click()
            await asyncio.sleep(4)
            
        await page.screenshot(path="logs/audit/all_actual_xong_filter.png")
        
        threads_all = await page.evaluate('''() => {
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
        
        empty_text_all = await page.evaluate('''() => {
            return document.body.innerText.includes('Không có kết quả nào khớp với bộ lọc');
        }''')
        
        print(f"\nRESULTS FOR ALL INBOX XONG FILTER:")
        print(f"Empty state message present: {empty_text_all}")
        print(f"Thread count in ALL Xong filter: {len(threads_all)}")
        if threads_all:
            for t in threads_all:
                print(f"  - {t['name']}")
                
        await b.close()

if __name__ == "__main__":
    asyncio.run(run())
