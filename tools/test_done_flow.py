import asyncio
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.async_api import async_playwright
from bot.page_bot_engine import create_bot_browser_context, human_sleep

async def handle_sso_if_needed(page, target_url):
    url = page.url.lower()
    print(f"Checking SSO for URL: {page.url}")
    if "login" in url:
        print("Detected login page, checking SSO button...")
        btn = page.locator('div:has-text("Tiếp tục bằng Facebook"), button:has-text("Tiếp tục bằng Facebook"), a:has-text("Tiếp tục bằng Facebook")').first
        if await btn.count() > 0 and await btn.is_visible():
            print("Found SSO button, clicking with popup listener...")
            popup_future = asyncio.get_event_loop().create_future()
            def on_page(p):
                if not popup_future.done():
                    popup_future.set_result(p)
            page.context.on("page", on_page)
            await btn.click()
            try:
                popup = await asyncio.wait_for(popup_future, timeout=8.0)
                print(f"Popup opened: {popup.url}")
                await popup.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(2)
                p_btn = popup.locator('div[role="button"]:has-text("Tiếp tục"), button:has-text("Tiếp tục")').last
                if await p_btn.count() > 0 and await p_btn.is_visible():
                    print("Clicking Tiếp tục in popup...")
                    await p_btn.click()
                await asyncio.sleep(5)
            except Exception as e:
                print(f"Popup handling note: {e}")
            await asyncio.sleep(3)
        
        # Navigate back to target_url if not already there
        if "login" in page.url.lower():
            print("Re-navigating to target URL after SSO...")
            await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(4)

async def main():
    os.makedirs("logs", exist_ok=True)
    async with async_playwright() as pw:
        browser, context = await create_bot_browser_context(pw, headless=True)
        page = await context.new_page()
        try:
            # 1. Warm up facebook.com
            print("1. Opening facebook.com...")
            await page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            print("FB URL:", page.url)
            
            # 2. Go to Messenger DONE
            done_url = "https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512&mailbox_folder=DONE"
            print(f"2. Navigating to: {done_url}")
            await page.goto(done_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(4)
            print("Landing URL:", page.url)
            
            await handle_sso_if_needed(page, done_url)
            print("Post-SSO URL:", page.url)
            
            # Save storage state
            await context.storage_state(path="state/fb_storage_state.json")
            
            # Take screenshot
            screenshot_path = "logs/test_messenger_done.png"
            await page.screenshot(path=screenshot_path)
            print(f"Saved screenshot: {screenshot_path}")
            
            # Dump title, text snippet
            title = await page.title()
            print("Page title:", title)
            
            # Inspect elements
            page_text = await page.evaluate("() => document.body.innerText.slice(0, 500)")
            print("Page body preview:\n", page_text)
            
        finally:
            if browser:
                await browser.close()
            else:
                await context.close()

if __name__ == "__main__":
    asyncio.run(main())
