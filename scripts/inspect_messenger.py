import asyncio
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

async def inspect_messenger():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        page = await context.new_page()
        url = "https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512"
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        
        await page.screenshot(path="logs/messenger_page.png")
        print("Saved screenshot to logs/messenger_page.png")
        
        info = await page.evaluate('''() => {
            // Danh sách hội thoại ở cột trái
            const threads = Array.from(document.querySelectorAll('[role="grid"] [role="row"], [role="navigation"] [role="listitem"], div[role="listitem"]'))
                .map((t, i) => ({
                    index: i,
                    text: t.innerText.slice(0, 100).replace(/\\n/g, ' | '),
                    ariaLabel: t.getAttribute('aria-label') || ''
                }));
                
            // Khung chat chính
            const headings = Array.from(document.querySelectorAll('h1, h2, h3, [role="heading"]'))
                .map(h => ({
                    text: h.innerText.trim(),
                    rect: h.getBoundingClientRect()
                }));
                
            // Textboxes
            const textboxes = Array.from(document.querySelectorAll('[role="textbox"], textarea'))
                .map(tb => ({
                    placeholder: tb.getAttribute('placeholder') || '',
                    ariaLabel: tb.getAttribute('aria-label') || '',
                    rect: tb.getBoundingClientRect()
                }));

            return {
                threads: threads.slice(0, 10),
                headings,
                textboxes
            };
        }''')
        
        print("Messenger Info:")
        print(json.dumps(info, ensure_ascii=False, indent=2))
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_messenger())
