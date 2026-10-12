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
        print("Navigating to messenger inbox...")
        await page.goto("https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512", wait_until="domcontentloaded")
        await asyncio.sleep(5)
        
        # Open filter and select Xong
        filter_btn = page.locator('[aria-label="Bộ lọc"], button[aria-label="Bộ lọc"]').first
        await filter_btn.click()
        await asyncio.sleep(2)
        xong_chip = page.locator('div:text-is("Xong"), span:text-is("Xong")').last
        await xong_chip.click()
        await asyncio.sleep(1)
        apply_btn = page.locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first
        await apply_btn.click()
        await asyncio.sleep(4)
        
        # 1. Inspect "..." button in Uyên Phạm chat header
        dots_btn = page.locator('div[role="button"][aria-label*="Tùy chọn"], div[role="button"][aria-label*="thêm"], div._a6ag [role="button"]').first
        # Find three dots button in center pane (x: 650..780, y: 220..270)
        dots_candidates = await page.evaluate('''() => {
            const btns = Array.from(document.querySelectorAll('button, div[role="button"]'));
            return btns.map(b => {
                const r = b.getBoundingClientRect();
                return {
                    aria: b.getAttribute('aria-label') || '',
                    text: (b.innerText || '').trim(),
                    rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}
                };
            }).filter(b => b.rect.x > 600 && b.rect.x < 780 && b.rect.y > 200 && b.rect.y < 280);
        }''')
        print("Dots button candidates:", dots_candidates)
        
        if dots_candidates:
            tgt = dots_candidates[0]
            print(f"Clicking dots button at ({tgt['rect']['x']}, {tgt['rect']['y']})...")
            await page.mouse.click(tgt['rect']['x'] + 10, tgt['rect']['y'] + 10)
            await asyncio.sleep(2)
            await page.screenshot(path="logs/dots_menu_opened.png")
            
            # Inspect menu items
            menu_items = await page.evaluate('''() => {
                const els = Array.from(document.querySelectorAll('[role="menuitem"], div[role="button"], span, div'));
                return els.map(el => {
                    const r = el.getBoundingClientRect();
                    return {
                        role: el.getAttribute('role'),
                        aria: el.getAttribute('aria-label') || '',
                        text: (el.innerText || '').trim(),
                        rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}
                    };
                }).filter(e => e.rect.w > 60 && e.rect.h >= 20 && e.rect.x > 500 && e.rect.y > 200 && e.text);
            }''')
            print("Menu items in dots menu:", json.dumps(menu_items, ensure_ascii=False, indent=2))
        
        # 2. Inspect "Quản lý" (Bulk select) button in DONE view
        manage_btn = page.locator('div[role="button"]:has-text("Quản lý"), button:has-text("Quản lý")').first
        if await manage_btn.count() > 0:
            print("Clicking Quản lý button...")
            await manage_btn.click()
            await asyncio.sleep(2)
            await page.screenshot(path="logs/manage_mode_opened.png")
            
            # Check what buttons appeared in bulk select bar
            bulk_buttons = await page.evaluate('''() => {
                const btns = Array.from(document.querySelectorAll('button, div[role="button"], input[type="checkbox"]'));
                return btns.map(b => ({
                    tag: b.tagName,
                    type: b.type || '',
                    text: (b.innerText || '').trim(),
                    aria: b.getAttribute('aria-label') || '',
                    rect: b.getBoundingClientRect()
                })).filter(b => b.rect.y >= 200 && b.rect.y <= 320);
            }''')
            print("Bulk select buttons:", json.dumps(bulk_buttons, ensure_ascii=False, indent=2))
            
            # Check if there is "Chọn tất cả"
            select_all = page.locator('div:text-is("Chọn tất cả"), span:text-is("Chọn tất cả")').first
            if await select_all.count() > 0:
                print("Clicking 'Chọn tất cả'...")
                await select_all.click()
                await asyncio.sleep(2)
                await page.screenshot(path="logs/after_select_all.png")
                
                # Check what action buttons appeared at top/bottom of bulk select
                action_bar = await page.evaluate('''() => {
                    const btns = Array.from(document.querySelectorAll('button, div[role="button"], span'));
                    return btns.map(b => ({
                        text: (b.innerText || '').trim(),
                        aria: b.getAttribute('aria-label') || '',
                        rect: {x: Math.round(b.getBoundingClientRect().x), y: Math.round(b.getBoundingClientRect().y), w: Math.round(b.getBoundingClientRect().width), h: Math.round(b.getBoundingClientRect().height)}
                    })).filter(b => b.rect.y >= 200 && b.rect.y <= 350 && (b.text || b.aria));
                }''')
                print("Action bar after 'Chọn tất cả':", json.dumps(action_bar, ensure_ascii=False, indent=2))
                
        await b.close()

if __name__ == "__main__":
    asyncio.run(main())
