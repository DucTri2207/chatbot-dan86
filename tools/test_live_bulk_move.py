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
        
        # Go to DONE URL
        await page.goto("https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512&mailbox_folder=DONE", wait_until="domcontentloaded")
        await asyncio.sleep(5)
        print("Page URL:", page.url)
        
        # Check Quản lý button
        manage_btn = page.locator('div[role="button"]:has-text("Quản lý"), button:has-text("Quản lý")').first
        print("Manage button count:", await manage_btn.count(), "visible:", await manage_btn.is_visible())
        
        if await manage_btn.count() > 0:
            print("Clicking Quản lý...")
            await manage_btn.click()
            await asyncio.sleep(2)
            await page.screenshot(path="logs/step1_after_manage.png")
            
            # Print all text in left area (x: 50..400, y: 150..350)
            texts = await page.evaluate('''() => {
                const els = Array.from(document.querySelectorAll('div, span, button, input'));
                return els.map(el => {
                    const r = el.getBoundingClientRect();
                    return {
                        tag: el.tagName,
                        type: el.type || '',
                        text: (el.innerText || '').trim(),
                        aria: el.getAttribute('aria-label') || '',
                        rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}
                    };
                }).filter(e => e.rect.x >= 50 && e.rect.x <= 400 && e.rect.y >= 150 && e.rect.y <= 350 && (e.text || e.aria || e.type === 'checkbox'));
            }''')
            print("Elements after Quản lý:", json.dumps(texts, ensure_ascii=False, indent=2))
            
            # Now find "Chọn tất cả" or any checkbox
            # Check by JS click or text locator
            select_all_btn = page.locator('text="Chọn tất cả"').first
            print("Locator text='Chọn tất cả' count:", await select_all_btn.count())
            if await select_all_btn.count() > 0:
                print("Clicking Chọn tất cả...")
                await select_all_btn.click()
                await asyncio.sleep(2)
                await page.screenshot(path="logs/step2_after_select_all.png")
                
                # Check for "Chuyển về Hộp thư đến"
                move_btn = page.locator('[aria-label="Chuyển về Hộp thư đến"], div[role="button"][aria-label="Chuyển về Hộp thư đến"]').first
                print("Move to inbox btn count:", await move_btn.count(), "visible:", await move_btn.is_visible())
                if await move_btn.count() > 0:
                    print(">>> Found move button! Testing click! <<<")
                    await move_btn.click()
                    await asyncio.sleep(4)
                    await page.screenshot(path="logs/step3_after_move_click.png")
                    print("Move clicked! Checking threads remaining in Xong...")
                    
                    remaining = await page.evaluate('''() => {
                        const nodes = Array.from(document.querySelectorAll('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]'));
                        return nodes.map(n => {
                            const lines = (n.innerText || '').trim().split('\\n').map(l => l.trim()).filter(Boolean);
                            return lines[0] || '';
                        }).filter(n => n.length > 1 && !['tìm kiếm', 'quản lý', 'hộp thư', 'messenger', 'chưa đọc', 'ưu tiên'].some(k => n.toLowerCase().includes(k)));
                    }''')
                    print("Remaining threads:", remaining)
                    
        await b.close()

if __name__ == "__main__":
    asyncio.run(main())
