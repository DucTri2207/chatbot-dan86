import asyncio
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

async def find_customer_name_selector():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        page = await context.new_page()
        await page.goto("https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512", wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        
        candidates = await page.evaluate('''() => {
            const matches = [];
            const all = Array.from(document.querySelectorAll('*'));
            for (const el of all) {
                if (el.children.length === 0 && (el.innerText || '').trim() === 'ThuDong Huynh') {
                    const r = el.getBoundingClientRect();
                    matches.push({
                        tag: el.tagName,
                        parentTag: el.parentElement ? el.parentElement.tagName : '',
                        grandParentTag: el.parentElement && el.parentElement.parentElement ? el.parentElement.parentElement.tagName : '',
                        className: el.className,
                        rect: { top: r.top, left: r.left }
                    });
                }
            }
            return matches;
        }''')
        
        print("Candidate elements for ThuDong Huynh:")
        print(json.dumps(candidates, ensure_ascii=False, indent=2))
        await browser.close()

if __name__ == "__main__":
    asyncio.run(find_customer_name_selector())
