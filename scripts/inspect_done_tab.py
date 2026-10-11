import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.page_bot_engine import create_bot_browser_context, verify_logged_in, human_sleep
from bot.bot_config import META_INBOX_COMMENTS_URL, META_INBOX_MESSENGER_URL

async def main():
    async with async_playwright() as pw:
        browser, context = await create_bot_browser_context(pw, headless=True)
        page = await context.new_page()
        try:
            print("Navigating to comments URL:", META_INBOX_COMMENTS_URL)
            await page.goto(META_INBOX_COMMENTS_URL, wait_until="domcontentloaded", timeout=45000)
            await human_sleep(4.0, 6.0)
            print("Initial URL:", page.url)

            is_logged_in = await verify_logged_in(page)
            print("Is logged in:", is_logged_in, "Current URL:", page.url)

            if not is_logged_in:
                print("Could not log in. Taking screenshot.")
                await page.screenshot(path="logs/login_fail.png")
                return

            await human_sleep(3.0, 5.0)

            # Inspect elements on page
            info = await page.evaluate('''() => {
                const buttons = Array.from(document.querySelectorAll('button, div[role="button"], div[role="tab"], a[role="tab"], div[role="presentation"], div._a6ag._a6ah'));
                const results = [];
                for (const b of buttons) {
                    const text = (b.innerText || '').trim().replace(/\\n/g, ' ');
                    const aria = b.getAttribute('aria-label') || '';
                    const role = b.getAttribute('role') || '';
                    const rect = b.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        results.push({
                            tag: b.tagName,
                            className: b.className,
                            role,
                            text: text.slice(0, 100),
                            aria,
                            rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}
                        });
                    }
                }
                return results;
            }''')

            print(f"Total elements: {len(info)}")
            for item in info:
                comb = (item['text'] + ' ' + item['aria']).lower()
                if any(k in comb for k in ['xong', 'done', 'chính', 'main', 'lọc', 'filter', 'spam', 'thư mục', 'đã xong']):
                    print("FILTER CANDIDATE:", item)

            rows = [it for it in info if it['rect']['x'] < 550 and it['rect']['w'] > 200 and it['rect']['h'] >= 40 and it['rect']['y'] >= 180]
            print(f"Total row candidates on left: {len(rows)}")
            for r in rows[:10]:
                print("ROW CANDIDATE:", r)

            await page.screenshot(path="logs/inbox_comments_logged_in.png")
            print("Saved screenshot to logs/inbox_comments_logged_in.png")

        finally:
            if browser:
                await browser.close()
            else:
                await context.close()

if __name__ == "__main__":
    asyncio.run(main())
