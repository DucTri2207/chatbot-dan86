import asyncio
import os
import sys
from playwright.async_api import async_playwright

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN",
        )
        p = await ctx.new_page()
        await p.goto("https://www.facebook.com", wait_until="domcontentloaded")
        await p.goto("https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512", wait_until="domcontentloaded")
        await asyncio.sleep(4)

        btn = page_btn = p.locator('text="Tiếp tục bằng Facebook"').first
        popup_f = asyncio.get_event_loop().create_future()
        ctx.on("page", lambda page: popup_f.set_result(page) if not popup_f.done() else None)
        await page_btn.click()
        popup = await popup_f
        await popup.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(2)

        forms = await popup.evaluate('''() => {
            return Array.from(document.querySelectorAll('form, button, div[role="button"], input, a')).map(e => ({
                tag: e.tagName,
                id: e.id,
                name: e.name || '',
                type: e.type || '',
                action: e.action || e.href || '',
                text: (e.innerText || e.value || '').trim()
            }));
        }''')
        for f in forms:
            print("ELEM:", f)

        # Now let's try clicking the Continue button and see network requests or errors
        print("Clicking continue button...")
        cont_btn = popup.locator('div[role="button"]:has-text("Tiếp tục"), button:has-text("Tiếp tục")').first
        await cont_btn.click()
        await asyncio.sleep(5)
        print("After click popup URL:", popup.url)
        await popup.screenshot(path="logs/popup_after_cont_click.png")

        await b.close()

if __name__ == "__main__":
    asyncio.run(main())
