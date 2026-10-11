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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        p = await ctx.new_page()
        print("1. Navigating to facebook.com...")
        await p.goto("https://www.facebook.com", wait_until="domcontentloaded")
        print("FB URL:", p.url)

        print("2. Navigating to Meta Business Suite comments...")
        await p.goto("https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512", wait_until="domcontentloaded")
        await asyncio.sleep(4)
        print("MBS URL:", p.url)

        if "login" in p.url.lower():
            btn = p.locator('text="Tiếp tục bằng Facebook"').first
            if await btn.count() > 0:
                print("3. Found SSO button, clicking...")
                popup_future = asyncio.get_event_loop().create_future()
                ctx.on("page", lambda page: popup_future.set_result(page) if not popup_future.done() else None)
                await btn.click()
                try:
                    popup = await asyncio.wait_for(popup_future, timeout=10.0)
                    print("4. Popup opened:", popup.url)
                    await popup.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(3)
                    print("5. Popup after wait:", popup.url)
                    await popup.screenshot(path="logs/popup_details.png")

                    # Look for buttons in popup
                    p_btns = popup.locator('div[role="button"], button')
                    count = await p_btns.count()
                    for idx in range(count):
                        txt = (await p_btns.nth(idx).inner_text() or "").strip()
                        print(f"Popup button {idx}: {txt}")
                        if "tiếp tục" in txt.lower():
                            print(f"Clicking popup button: {txt}")
                            await p_btns.nth(idx).click()
                            break
                    await asyncio.sleep(6)
                except Exception as e:
                    print("Popup handling exception:", e)

        print("6. Final main page URL:", p.url)
        await p.screenshot(path="logs/final_after_sso_chain.png")

        # Save cookies
        await ctx.storage_state(path="state/fb_storage_state.json")
        print("7. Saved updated storage state.")
        await b.close()

if __name__ == "__main__":
    asyncio.run(main())
