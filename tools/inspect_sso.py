import asyncio
import json
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
        p = await ctx.new_page()
        print("Navigating to facebook.com...")
        await p.goto("https://www.facebook.com", wait_until="domcontentloaded")
        await asyncio.sleep(2)
        print("Navigating to MBS...")
        target_url = "https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512&mailbox_folder=DONE"
        await p.goto(target_url, wait_until="domcontentloaded")
        await asyncio.sleep(4)
        print("Current URL:", p.url)
        
        info = await p.evaluate('''() => {
            const btns = Array.from(document.querySelectorAll('button, div[role="button"], a, div'));
            return btns.map(b => ({
                tag: b.tagName,
                text: (b.innerText || '').trim(),
                href: b.href || '',
                role: b.getAttribute('role') || '',
                aria: b.getAttribute('aria-label') || '',
                id: b.id || '',
                className: b.className || ''
            })).filter(b => b.text && (b.text.includes('Facebook') || b.text.includes('Tiếp tục')));
        }''')
        print("Candidate elements:", json.dumps(info, ensure_ascii=False, indent=2))
        
        # Now let's try clicking the button and see what happens to p and ctx
        btn = p.locator('text="Tiếp tục bằng Facebook"').first
        if await btn.count() > 0:
            print("Found button! Visible:", await btn.is_visible())
            
            # Setup listeners
            ctx.on("page", lambda new_p: print("NEW PAGE EVENT:", new_p.url))
            p.on("framenavigated", lambda f: print("FRAME NAVIGATED:", f.url))
            
            print("Clicking button...")
            await btn.click()
            print("Clicked! Waiting 8 seconds...")
            await asyncio.sleep(8)
            print("All pages in context:", [pg.url for pg in ctx.pages])
            for idx, pg in enumerate(ctx.pages):
                await pg.screenshot(path=f"logs/inspect_page_{idx}.png")
                print(f"Page {idx} URL: {pg.url}, Title: {await pg.title()}")
                
        await b.close()

if __name__ == "__main__":
    asyncio.run(main())
