import asyncio
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

async def inspect_threads_list():
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
        
        info = await page.evaluate('''() => {
            // Lấy tất cả các thẻ a hoặc div có link hoặc click được ở sidebar trái
            const links = Array.from(document.querySelectorAll('a, div[role="row"], div[role="listitem"], [data-pagelet*="Thread"]'))
                .map(el => {
                    const r = el.getBoundingClientRect();
                    return {
                        tag: el.tagName,
                        role: el.getAttribute('role'),
                        href: el.getAttribute('href') || '',
                        text: (el.innerText || '').slice(0, 100).replace(/\\n/g, ' | '),
                        rect: { top: r.top, left: r.left, width: r.width, height: r.height }
                    };
                })
                .filter(el => el.rect.left < 450 && el.rect.height > 20 && el.text.length > 5);
            return links;
        }''')
        
        print(f"Found {len(info)} links/items:")
        for item in info:
            print(f"[{item['rect']['top']:.1f}, {item['rect']['left']:.1f}] {item['tag']} {item['role']} -> {item['text']}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_threads_list())
