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
        
        # Apply Xong
        filter_btn = page.locator('[aria-label="Bộ lọc"]').first
        await filter_btn.click()
        await asyncio.sleep(2)
        xong_chip = page.locator('div:text-is("Xong"), span:text-is("Xong")').last
        await xong_chip.click()
        await asyncio.sleep(1)
        apply_btn = page.locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first
        await apply_btn.click()
        await asyncio.sleep(4)
        
        # Click Quản lý
        manage_btn = page.locator('div[role="button"]:has-text("Quản lý"), button:has-text("Quản lý")').first
        print("Clicking Quản lý...")
        await manage_btn.click()
        await asyncio.sleep(2)
        
        # Look for "Chọn tất cả" or "Chọn tất cả những gì đang hiển thị"
        select_all_candidates = await page.evaluate('''() => {
            const all = Array.from(document.querySelectorAll('*'));
            return all.map(el => {
                const text = (el.innerText || '').trim();
                return {
                    tag: el.tagName,
                    role: el.getAttribute('role'),
                    text,
                    rect: el.getBoundingClientRect()
                };
            }).filter(e => e.text && (e.text.includes('Chọn tất cả') || e.text.includes('hiển thị')) && e.rect.w > 20);
        }''')
        print("Select all candidates:", json.dumps(select_all_candidates[:5], ensure_ascii=False, indent=2))
        
        select_btn = page.locator('text="Chọn tất cả những gì đang hiển thị", text="Chọn tất cả"').first
        if await select_btn.count() > 0:
            print("Clicking select_btn...")
            await select_btn.click()
            await asyncio.sleep(2)
            await page.screenshot(path="logs/bulk_selected.png")
            
            # Check what action buttons appear
            action_buttons = await page.evaluate('''() => {
                const btns = Array.from(document.querySelectorAll('button, div[role="button"], span'));
                return btns.map(b => ({
                    tag: b.tagName,
                    text: (b.innerText || '').trim(),
                    aria: b.getAttribute('aria-label') || '',
                    rect: {x: Math.round(b.getBoundingClientRect().x), y: Math.round(b.getBoundingClientRect().y), w: Math.round(b.getBoundingClientRect().width), h: Math.round(b.getBoundingClientRect().height)}
                })).filter(b => (b.aria || b.text) && b.rect.y >= 200 && b.rect.y <= 320 && b.rect.w >= 20);
            }''')
            print("Action buttons after bulk select:", json.dumps(action_buttons, ensure_ascii=False, indent=2))
            
            # Look for "Chuyển về Hộp thư đến"
            move_btn = page.locator('[aria-label="Chuyển về Hộp thư đến"]').first
            if await move_btn.count() > 0:
                print(">>> FOUND MOVE TO INBOX BUTTON IN BULK SELECT! <<<")
                await move_btn.click()
                await asyncio.sleep(4)
                await page.screenshot(path="logs/after_bulk_move.png")
                print("Successfully clicked bulk move!")
                
        await b.close()

if __name__ == "__main__":
    asyncio.run(main())
