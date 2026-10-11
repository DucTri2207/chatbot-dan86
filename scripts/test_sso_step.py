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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.page_bot_engine import create_bot_browser_context
from bot.bot_config import META_INBOX_COMMENTS_URL

async def main():
    async with async_playwright() as pw:
        browser, context = await create_bot_browser_context(pw, headless=True)
        page = await context.new_page()
        try:
            print("Going to:", META_INBOX_COMMENTS_URL)
            await page.goto(META_INBOX_COMMENTS_URL, wait_until="domcontentloaded")
            await asyncio.sleep(4)
            print("URL:", page.url)

            btn = page.locator('text="Tiếp tục bằng Facebook"').first
            print("Btn count:", await btn.count(), "Visible:", await btn.is_visible())

            # Listen for new page
            popup_future = asyncio.get_event_loop().create_future()
            def on_page(p):
                if not popup_future.done():
                    popup_future.set_result(p)
            context.on("page", on_page)

            print("Clicking button...")
            await btn.click()

            # Wait for either popup or page navigation
            try:
                popup = await asyncio.wait_for(popup_future, timeout=6.0)
                print("Got popup:", popup.url)
                await popup.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(2)
                print("Popup loaded URL:", popup.url)
                await popup.screenshot(path="logs/popup_screen.png")

                # Check buttons in popup
                p_btn = popup.locator('text="Tiếp tục"').first
                if await p_btn.count() > 0:
                    print("Found 'Tiếp tục' in popup, clicking...")
                    await p_btn.click()
                    await asyncio.sleep(4)
            except asyncio.TimeoutError:
                print("No popup detected.")

            await asyncio.sleep(5)
            print("Final main page URL:", page.url)
            await page.screenshot(path="logs/main_after_sso_done.png")

        finally:
            if browser:
                await browser.close()
            else:
                await context.close()

if __name__ == "__main__":
    asyncio.run(main())
