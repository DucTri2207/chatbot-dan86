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
    os.makedirs("logs", exist_ok=True)
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        page = await ctx.new_page()
        
        done_url = "https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512&mailbox_folder=DONE"
        print(f"Navigating to DONE URL: {done_url}")
        await page.goto(done_url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(6)
        print("Page URL:", page.url)
        
        # Save BEFORE screenshot
        before_screenshot = "logs/01_before_restore_done_folder.png"
        await page.screenshot(path=before_screenshot)
        print(f"Saved BEFORE screenshot: {before_screenshot}")
        
        # Check threads in DONE folder
        threads = await page.evaluate('''() => {
            const nodes = Array.from(document.querySelectorAll('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"], [role="row"]'));
            return nodes.map((n, idx) => {
                const rect = n.getBoundingClientRect();
                const text = (n.innerText || '').trim().replace(/\\n+/g, ' | ');
                return { idx, text, rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)} };
            }).filter(n => n.rect.x >= 60 && n.rect.x <= 360 && n.rect.y >= 300 && n.rect.h >= 40);
        }''')
        print(f"Total threads in DONE folder: {len(threads)}")
        for t in threads[:10]:
            print(f"  [{t['idx']}] {t['text'][:100]}")
            
        # Check "Quản lý" (Bulk select) button
        manage_btn = page.locator('div[role="button"]:has-text("Quản lý"), button:has-text("Quản lý")').first
        if await manage_btn.count() > 0 and await manage_btn.is_visible():
            print("Found 'Quản lý' button! Clicking to test bulk select...")
            await manage_btn.click()
            await asyncio.sleep(2)
            await page.screenshot(path="logs/02_after_manage_click.png")
            
            # Check what appeared after clicking "Quản lý"
            manage_actions = await page.evaluate('''() => {
                const btns = Array.from(document.querySelectorAll('button, div[role="button"], input[type="checkbox"]'));
                return btns.map(b => ({
                    tag: b.tagName,
                    type: b.type || '',
                    text: (b.innerText || '').trim(),
                    aria: b.getAttribute('aria-label') || '',
                    rect: b.getBoundingClientRect()
                })).filter(b => b.rect.y > 150 && b.rect.y < 350 && (b.text || b.aria || b.type === 'checkbox'));
            }''')
            print("Actions after clicking 'Quản lý':", json.dumps(manage_actions, ensure_ascii=False, indent=2))
        
        # Click first thread to inspect individual thread actions
        thread_items = page.locator('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]')
        first_item = thread_items.first
        if await first_item.count() > 0:
            print("Clicking first thread...")
            await first_item.click(position={"x": 150, "y": 40})
            await asyncio.sleep(3)
            await page.screenshot(path="logs/03_thread_opened.png")
            
            # Inspect all buttons in header/middle pane
            header_buttons = await page.evaluate('''() => {
                const btns = Array.from(document.querySelectorAll('button, div[role="button"], [role="menuitem"]'));
                return btns.map(b => ({
                    tag: b.tagName,
                    text: (b.innerText || '').trim(),
                    aria: b.getAttribute('aria-label') || '',
                    title: b.getAttribute('title') || '',
                    rect: {x: Math.round(b.getBoundingClientRect().x), y: Math.round(b.getBoundingClientRect().y), w: Math.round(b.getBoundingClientRect().width), h: Math.round(b.getBoundingClientRect().height)}
                })).filter(b => b.rect.y >= 80 && b.rect.y <= 250 && b.rect.x >= 350 && (b.text || b.aria || b.title));
            }''')
            print("Thread header buttons:", json.dumps(header_buttons, ensure_ascii=False, indent=2))
            
        await b.close()

if __name__ == "__main__":
    asyncio.run(main())
