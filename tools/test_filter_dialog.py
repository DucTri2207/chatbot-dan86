import asyncio
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        page = await ctx.new_page()
        await page.goto("https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512", wait_until="domcontentloaded")
        await asyncio.sleep(5)
        filter_btn = page.locator('[aria-label="Bộ lọc"]').first
        print(f"Filter button exists: {await filter_btn.count() > 0}")
        if await filter_btn.count() > 0:
            await filter_btn.click()
            await asyncio.sleep(2)
            res = await page.evaluate('''() => {
                const dialog = document.querySelector('[role="dialog"]') || document.body;
                // find all sections/headings/chips
                const chips = Array.from(dialog.querySelectorAll('div, span, button')).filter(e => {
                    const t = (e.innerText || '').trim();
                    return t === 'Xong' || t === 'Chính' || t === 'Thư mục' || t.includes('Thư mục');
                }).map(e => ({
                    tag: e.tagName,
                    text: e.innerText,
                    rect: e.getBoundingClientRect()
                }));
                return {
                    dialogFound: !!document.querySelector('[role="dialog"]'),
                    chips: chips,
                    bodySnippet: dialog.innerText.substring(0, 500)
                };
            }''')
            print(f"Dialog result: {res}")
            
            # Scroll dialog down
            await page.evaluate('''() => {
                const els = document.querySelectorAll('*');
                for (const el of els) {
                    if (el.scrollHeight > el.clientHeight && el.clientHeight > 200) {
                        el.scrollTop = el.scrollHeight;
                    }
                }
            }''')
            await asyncio.sleep(2)
            await page.screenshot(path="logs/audit/filter_dialog_scrolled.png")
            
            res_after = await page.evaluate('''() => {
                const dialog = document.querySelector('[role="dialog"]') || document.body;
                const chips = Array.from(dialog.querySelectorAll('div, span, button')).filter(e => {
                    const t = (e.innerText || '').trim();
                    return t === 'Xong' || t === 'Chính' || t.includes('Xong');
                }).map(e => ({
                    tag: e.tagName,
                    text: e.innerText,
                    visible: e.getBoundingClientRect().height > 0
                }));
                return chips;
            }''')
            print(f"Chips after scroll: {res_after}")
            
        await b.close()

if __name__ == "__main__":
    asyncio.run(run())
