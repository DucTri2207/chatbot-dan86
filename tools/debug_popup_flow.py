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

async def main():
    async with async_playwright() as pw:
        b, ctx = await create_bot_browser_context(pw, headless=True)
        page = await ctx.new_page()
        try:
            print("1. Goto facebook...")
            await page.goto("https://www.facebook.com", wait_until="domcontentloaded")
            await asyncio.sleep(2)
            
            target_url = "https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512&mailbox_folder=DONE"
            print("2. Goto MBS...")
            await page.goto(target_url, wait_until="domcontentloaded")
            await asyncio.sleep(4)
            
            btn = page.locator('text="Tiếp tục bằng Facebook"').first
            if await btn.count() > 0:
                print("Found SSO button, clicking...")
                popup_future = asyncio.get_event_loop().create_future()
                ctx.on("page", lambda p: popup_future.set_result(p) if not popup_future.done() else None)
                await btn.click()
                popup = await asyncio.wait_for(popup_future, timeout=10.0)
                print("Popup opened:", popup.url)
                await popup.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(3)
                
                # Screenshot before click
                await popup.screenshot(path="popup_before.png")
                print("Saved popup_before.png")
                
                # Check buttons in popup
                p_btns = popup.locator('button, div[role="button"], a')
                cnt = await p_btns.count()
                print(f"Total buttons in popup: {cnt}")
                target_btn = None
                for idx in range(cnt):
                    t = (await p_btns.nth(idx).inner_text() or "").strip()
                    print(f"Btn {idx}: text='{t}'")
                    if "tiếp tục" in t.lower() and not target_btn:
                        target_btn = p_btns.nth(idx)
                        print(f"Selected target_btn {idx}")
                
                if target_btn:
                    print("Clicking target_btn...")
                    await target_btn.click()
                    print("Clicked! Waiting 5s...")
                    await asyncio.sleep(5)
                    await popup.screenshot(path="popup_after.png")
                    print("Saved popup_after.png, popup URL now:", popup.url)
                
                # Check main page
                await asyncio.sleep(5)
                await page.screenshot(path="main_page_after_sso.png")
                print("Main page URL:", page.url)
        finally:
            await b.close()

if __name__ == "__main__":
    asyncio.run(main())
