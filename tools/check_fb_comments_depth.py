import asyncio
import json
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from playwright.async_api import async_playwright

PAGE_ASSET_ID = "104011958817512"

async def check_depth():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        p = await ctx.new_page()
        url = f"https://business.facebook.com/latest/inbox/facebook?asset_id={PAGE_ASSET_ID}"
        await p.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(5)
        
        filter_btn = p.locator('[aria-label="Bộ lọc"]').first
        if await filter_btn.count() > 0:
            await filter_btn.click()
            await asyncio.sleep(2)
            await p.evaluate('''() => {
                const dialog = document.querySelector('[role="dialog"]');
                if (dialog) {
                    const scrollable = Array.from(dialog.querySelectorAll('*')).filter(el => el.scrollHeight > el.clientHeight && el.clientHeight > 200);
                    for (const s of scrollable) s.scrollTop = s.scrollHeight;
                }
            }''')
            await asyncio.sleep(1)
            xong_elem = p.locator('[role="dialog"]').locator('div:text-is("Xong"), span:text-is("Xong")').first
            if await xong_elem.count() > 0:
                await xong_elem.click()
                await asyncio.sleep(1)
            apply_btn = p.locator('[role="dialog"]').locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first
            if await apply_btn.count() > 0:
                await apply_btn.click()
                await asyncio.sleep(4)
                
        # Scroll thread list and see all dates
        dates = []
        for s in range(15):
            items = await p.evaluate('''() => {
                const rows = Array.from(document.querySelectorAll('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]'));
                return rows.map(r => {
                    const text = (r.innerText || '').split('\\n');
                    return {
                        title: text[0] || '',
                        date: text[1] || ''
                    };
                });
            }''')
            dates.extend(items)
            # scroll down
            await p.evaluate('''() => {
                const containers = Array.from(document.querySelectorAll('div[style*="overflow"], div[class*="scroll"], div[role="navigation"], div[role="grid"]'))
                    .filter(el => {
                        const r = el.getBoundingClientRect();
                        return r.x >= 50 && r.x <= 380 && r.height > 300;
                    });
                for (const c of containers) {
                    c.scrollTop += 800;
                }
            }''')
            await asyncio.sleep(1.5)
            
        unique_titles = {d['title']: d['date'] for d in dates if d['title']}
        print(f"Total unique posts found in Xong: {len(unique_titles)}")
        print("Dates found:", set(unique_titles.values()))
        for t, d in list(unique_titles.items())[:15]:
            print(f"  {d}: {t[:50]}")
            
        await b.close()

if __name__ == "__main__":
    asyncio.run(check_depth())
