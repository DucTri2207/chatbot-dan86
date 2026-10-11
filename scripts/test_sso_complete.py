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

        if "login" in p.url.lower():
            btn = p.locator('text="Tiếp tục bằng Facebook"').first
            popup_future = asyncio.get_event_loop().create_future()
            ctx.on("page", lambda page: popup_future.set_result(page) if not popup_future.done() else None)
            await btn.click()
            popup = await asyncio.wait_for(popup_future, timeout=10.0)
            await popup.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)
            
            # Click Tiếp tục
            btn_cont = popup.locator('div[role="button"]:has-text("Tiếp tục"), button:has-text("Tiếp tục")').first
            print("Clicking Tiếp tục in popup...")
            await btn_cont.click()

            # Wait for popup to close or navigate
            print("Waiting for popup / main page...")
            for step in range(12):
                await asyncio.sleep(2)
                print(f"Step {step}: Main URL={p.url}")
                if popup.is_closed():
                    print("Popup is closed!")
                    break
                else:
                    print(f"Popup URL={popup.url}")

            await asyncio.sleep(5)
            print("FINAL Main URL:", p.url)
            await p.screenshot(path="logs/mbs_final_landing.png")
            await ctx.storage_state(path="state/fb_storage_state.json")
            from bot.auth_helper import export_github_secret_file
            export_github_secret_file("state/fb_storage_state.json")
            print("Storage state and github secret saved!")

        await b.close()

if __name__ == "__main__":
    asyncio.run(main())
