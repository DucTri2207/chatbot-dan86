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
    profile_dir = r"d:\dan86\.chrome_profile"
    print(f"Launching persistent context with profile: {profile_dir}...")
    
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-notifications",
    ]
    
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=True,
            args=launch_args,
            viewport={"width": 1440, "height": 900},
            locale="vi-VN",
        )
        page = context.pages[0] if context.pages else await context.new_page()
        
        target_url = "https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512&mailbox_folder=DONE"
        print(f"Navigating to {target_url}...")
        await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        
        print("Current URL:", page.url)
        print("Page Title:", await page.title())
        
        await page.screenshot(path="profile_messenger_done.png")
        print("Saved profile_messenger_done.png")
        
        # Print snippet of text
        text = await page.evaluate("() => document.body.innerText.slice(0, 1000)")
        print("Body text snippet:\n", text)
        
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
