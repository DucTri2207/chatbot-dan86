import asyncio
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

async def inspect_thread_container():
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
        
        items = await page.evaluate('''() => {
            // Tìm tất cả các phần tử con trực tiếp trong danh sách bài viết/bình luận ở cột trái
            // Điểm bắt đầu từ dưới thanh tìm kiếm (y > 280, x >= 70, x <= 380)
            const nodes = Array.from(document.querySelectorAll('*')).filter(el => {
                const r = el.getBoundingClientRect();
                return r.left >= 70 && r.left <= 90 && r.top >= 280 && r.width > 200 && r.height >= 40 && r.height <= 120;
            });
            
            return nodes.map((el, i) => ({
                index: i,
                tag: el.tagName,
                className: el.className,
                rect: el.getBoundingClientRect(),
                text: (el.innerText || '').slice(0, 150).replace(/\\n/g, ' [NL] ')
            }));
        }''')
        
        print(f"Items found: {len(items)}")
        for it in items:
            print(f"[{it['index']}] top={it['rect']['top']} -> {it['text']}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_thread_container())
