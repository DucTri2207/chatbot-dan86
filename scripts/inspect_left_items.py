import asyncio
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

async def inspect_threads():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        page = await context.new_page()
        
        url = "https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512"
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        
        items = await page.evaluate('''() => {
            // Danh sách thread bên trái thường là các div có class hoặc role
            // Tìm tất cả các container danh sách trong cột trái (x < 400)
            const rows = Array.from(document.querySelectorAll('div[role="listitem"], [role="grid"] [role="row"], [data-pagelet*="ThreadList"] [role="button"], div[tabindex="0"], div[tabindex="-1"]'))
                .filter(el => {
                    const rect = el.getBoundingClientRect();
                    return rect.left > 50 && rect.left < 380 && rect.top > 150 && rect.height > 40;
                });
            
            return rows.map((r, i) => ({
                index: i,
                text: r.innerText.trim(),
                rect: r.getBoundingClientRect(),
                hasUnread: r.innerHTML.includes('chưa đọc') || r.innerHTML.includes('unread') || r.innerText.includes('chưa đọc')
            }));
        }''')
        
        print("Left list items count:", len(items))
        for item in items[:15]:
            print(f"[{item['index']}] rect={item['rect']['top']} -> {repr(item['text'][:100])}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_threads())
