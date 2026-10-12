import asyncio
import json
import os
from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900}
        )
        page = await context.new_page()
        url = "https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512&mailbox_folder=DONE"
        print("Navigating to:", url)
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(6)
        
        print("Current URL:", page.url)
        print("Title:", await page.title())
        
        if "login" in page.url.lower():
            print("Redirected to login!")
            await browser.close()
            return
            
        os.makedirs("logs", exist_ok=True)
        await page.screenshot(path="logs/done_folder_messenger.png")
        print("Screenshot saved: logs/done_folder_messenger.png")
        
        items = await page.evaluate('''() => {
            const listItems = Array.from(document.querySelectorAll('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"], [role="row"]'));
            return listItems.map(el => {
                const text = (el.innerText || '').trim().replace(/\\n+/g, ' | ');
                const rect = el.getBoundingClientRect();
                return { text: text.slice(0, 100), top: rect.top, height: rect.height };
            }).filter(i => i.height > 20 && i.top > 50 && i.top < 850);
        }''')
        print(f"Found {len(items)} items in DONE folder:")
        for it in items[:15]:
            print(" -", it["text"])
            
        buttons = await page.evaluate('''() => {
            const btns = Array.from(document.querySelectorAll('[role="button"], button'));
            return btns.map(b => {
                const aria = b.getAttribute('aria-label') || '';
                const text = (b.innerText || '').trim();
                const title = b.getAttribute('title') || '';
                return { aria, text: text.slice(0, 40), title };
            }).filter(b => b.aria || b.text || b.title);
        }''')
        print(f"Total buttons found: {len(buttons)}")
        action_keywords = ['hộp thư', 'chuyển', 'inbox', 'move', 'chưa đọc', 'xong', 'lưu trữ', 'bỏ', 'khôi phục']
        for b in buttons:
            comb = f"{b['aria']} {b['text']} {b['title']}".lower()
            if any(k in comb for k in action_keywords):
                print("   Action button:", b)
                
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect())
