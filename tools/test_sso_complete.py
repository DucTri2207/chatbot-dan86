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
from bot.page_bot_engine import create_bot_browser_context

async def solve_sso_login(page, target_url):
    print("Checking current page URL:", page.url)
    if "login" in page.url.lower():
        print("At login page. Looking for SSO button...")
        btn = page.locator('text="Tiếp tục bằng Facebook"').first
        if await btn.count() > 0 and await btn.is_visible():
            print("Found SSO button. Setting up popup listener...")
            popup_future = asyncio.get_event_loop().create_future()
            def on_p(new_p):
                if not popup_future.done():
                    popup_future.set_result(new_p)
            page.context.on("page", on_p)
            
            await btn.click()
            try:
                popup = await asyncio.wait_for(popup_future, timeout=10.0)
                print("Popup opened! URL:", popup.url)
                await popup.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(2)
                
                # Find "Tiếp tục" button
                cont_btn = popup.locator('div[role="button"]:has-text("Tiếp tục"), button:has-text("Tiếp tục"), [aria-label*="Tiếp tục"]').first
                if await cont_btn.count() > 0:
                    print("Found 'Tiếp tục' button in popup, clicking...")
                    await cont_btn.click()
                else:
                    # Fallback click by text
                    print("Trying text locator in popup...")
                    await popup.locator('text="Tiếp tục"').first.click()
                
                print("Clicked continue in popup, waiting for popup close / navigation...")
                try:
                    await popup.wait_for_event("close", timeout=10000)
                    print("Popup closed successfully.")
                except Exception:
                    print("Popup did not close automatically within 10s.")
            except Exception as e:
                print("Popup handling error:", e)
                
        # Wait for main page to navigate
        print("Waiting for main page navigation...")
        for _ in range(15):
            await asyncio.sleep(1)
            if "login" not in page.url.lower():
                break
        print("Main page URL after wait:", page.url)
        
        # If still on login page or not at target_url, navigate
        if page.url != target_url:
            print(f"Navigating main page to target URL: {target_url}")
            await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(5)
            print("Current page URL now:", page.url)

async def main():
    async with async_playwright() as pw:
        b, ctx = await create_bot_browser_context(pw, headless=True)
        page = await ctx.new_page()
        try:
            print("1. Warm up fb...")
            await page.goto("https://www.facebook.com", wait_until="domcontentloaded")
            await asyncio.sleep(2)
            
            target_url = "https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512&mailbox_folder=DONE"
            print("2. Navigate to DONE...")
            await page.goto(target_url, wait_until="domcontentloaded")
            await asyncio.sleep(4)
            
            await solve_sso_login(page, target_url)
            
            # Save storage state
            await ctx.storage_state(path="state/fb_storage_state.json")
            print("Saved storage state.")
            
            screenshot_path = "d:\\chat bot dan 86\\logs\\sso_complete_done.png"
            await page.screenshot(path=screenshot_path)
            print(f"Saved screenshot: {screenshot_path}")
            
            # Check what's on the page
            print("Title:", await page.title())
            body_text = await page.evaluate("() => document.body.innerText.slice(0, 1000)")
            print("Body text snippet:\n", body_text)
            
        finally:
            await b.close()

if __name__ == "__main__":
    asyncio.run(main())
