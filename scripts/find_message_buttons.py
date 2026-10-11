import asyncio
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

async def find_message_buttons():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        page = await context.new_page()
        await page.goto("https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512", wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        
        # Lấy tất cả elements có text liên quan đến nhắn tin / gửi tin nhắn / message / chat trên toàn trang
        buttons = await page.evaluate('''() => {
            const matches = [];
            const all = Array.from(document.querySelectorAll('*'));
            for (const el of all) {
                if (el.children.length === 0) {
                    const t = (el.innerText || '').trim();
                    const aria = (el.getAttribute('aria-label') || '').trim();
                    const lower = (t + ' ' + aria).toLowerCase();
                    if (
                        lower.includes('tin nhắn') ||
                        lower.includes('nhắn tin') ||
                        lower.includes('message') ||
                        lower.includes('chat') ||
                        lower.includes('gửi')
                    ) {
                        matches.push({
                            tag: el.tagName,
                            text: t,
                            aria: aria,
                            role: el.getAttribute('role'),
                            parentTag: el.parentElement ? el.parentElement.tagName : '',
                            parentRole: el.parentElement ? el.parentElement.getAttribute('role') : '',
                            rect: el.getBoundingClientRect()
                        });
                    }
                }
            }
            return matches;
        }''')
        
        print(f"Total matching elements: {len(buttons)}")
        for b in buttons:
            if b['rect']['left'] > 400: # ở vùng xem chi tiết bên phải
                print(f"[{b['rect']['top']:.1f}, {b['rect']['left']:.1f}] {b['tag']} role={b['role']} text='{b['text']}' aria='{b['aria']}'")
                
        await browser.close()

if __name__ == "__main__":
    asyncio.run(find_message_buttons())
