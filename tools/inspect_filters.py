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
        
        # 1. Inspect normal inbox
        await page.goto("https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512", wait_until="domcontentloaded")
        await asyncio.sleep(4)
        print("Inbox URL:", page.url)
        
        # Look for buttons in the search/filter header area (y: 200..320, x: 0..400)
        filter_elements = await page.evaluate('''() => {
            const els = Array.from(document.querySelectorAll('button, div[role="button"], div[role="tab"], span, a'));
            return els.map(el => {
                const rect = el.getBoundingClientRect();
                return {
                    tag: el.tagName,
                    role: el.getAttribute('role'),
                    aria: el.getAttribute('aria-label') || '',
                    text: (el.innerText || '').trim(),
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}
                };
            }).filter(e => e.rect.x >= 60 && e.rect.x <= 360 && e.rect.y >= 200 && e.rect.y <= 320 && (e.text || e.aria));
        }''')
        print("Filter elements:", json.dumps(filter_elements, ensure_ascii=False, indent=2))
        
        # Now let's try opening the DONE folder directly
        done_url = "https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512&mailbox_folder=DONE"
        print(f"Navigating to DONE folder: {done_url}")
        await page.goto(done_url, wait_until="domcontentloaded")
        await asyncio.sleep(5)
        print("DONE URL:", page.url)
        
        await page.screenshot(path="logs/inspect_done_view.png")
        
        # Let's inspect the filter elements in DONE folder
        done_filter_elements = await page.evaluate('''() => {
            const els = Array.from(document.querySelectorAll('button, div[role="button"], div[role="tab"], span, a'));
            return els.map(el => {
                const rect = el.getBoundingClientRect();
                return {
                    tag: el.tagName,
                    role: el.getAttribute('role'),
                    aria: el.getAttribute('aria-label') || '',
                    text: (el.innerText || '').trim(),
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}
                };
            }).filter(e => e.rect.x >= 60 && e.rect.x <= 360 && e.rect.y >= 200 && e.rect.y <= 320 && (e.text || e.aria));
        }''')
        print("DONE Filter elements:", json.dumps(done_filter_elements, ensure_ascii=False, indent=2))
        
        # Inspect thread list in DONE folder
        threads = await page.evaluate('''() => {
            const nodes = Array.from(document.querySelectorAll('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"], [role="row"]'));
            return nodes.map(n => {
                const rect = n.getBoundingClientRect();
                const text = (n.innerText || '').trim().replace(/\\n+/g, ' | ');
                return { text, rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)} };
            }).filter(n => n.rect.x >= 60 && n.rect.x <= 360 && n.rect.y >= 300 && n.rect.h >= 40);
        }''')
        print(f"Total threads found in DONE view: {len(threads)}")
        for idx, t in enumerate(threads[:15]):
            print(f"Thread {idx}: {t['text'][:120]}")
            
        await b.close()

if __name__ == "__main__":
    asyncio.run(main())
