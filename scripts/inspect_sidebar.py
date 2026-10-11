import asyncio
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

async def inspect_sidebar():
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
        
        elements = await page.evaluate('''() => {
            const all = Array.from(document.querySelectorAll('*')).filter(el => {
                const r = el.getBoundingClientRect();
                return r.left >= 60 && r.right <= 400 && r.top >= 200 && r.height >= 40 && el.children.length > 0;
            });
            
            // Tìm các div có chứa chữ hoặc click được trong sidebar
            const result = [];
            for (const el of all) {
                // Chỉ lấy phần tử cấp ngoài cùng của mỗi card
                if (el.innerText && el.innerText.trim().length > 5) {
                    const rect = el.getBoundingClientRect();
                    result.push({
                        tag: el.tagName,
                        role: el.getAttribute('role'),
                        ariaLabel: el.getAttribute('aria-label'),
                        className: el.className,
                        text: el.innerText.slice(0, 120).replace(/\\n/g, ' | '),
                        top: rect.top,
                        height: rect.height
                    });
                }
            }
            return result;
        }''')
        
        print(f"Total found: {len(elements)}")
        for e in elements[:20]:
            print(f"top={e['top']:.1f} h={e['height']:.1f} role={e['role']} -> {e['text']}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_sidebar())
