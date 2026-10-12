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

async def main():
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(r'd:\dan86\.chrome_profile', headless=True)
        p = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await p.goto('https://www.facebook.com', wait_until='domcontentloaded')
        await asyncio.sleep(2)
        btn = p.locator('text="Tiếp tục"').first
        print('Clicking Tiếp tục...')
        await btn.click()
        await asyncio.sleep(5)
        print('FB URL after click:', p.url, 'Title:', await p.title())
        await p.screenshot(path='fb_after_click.png')
        await ctx.close()

if __name__ == '__main__':
    asyncio.run(main())
