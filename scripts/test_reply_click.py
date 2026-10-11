import asyncio
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

async def test_reply_click():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        page = await context.new_page()
        await page.goto("https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512", wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        
        # Lấy article số 1 (Chau Kieu)
        articles = page.locator('[role="article"]')
        art = articles.nth(1)
        aria = await art.get_attribute("aria-label") or ""
        txt = await art.inner_text()
        print(f"Target article: aria='{aria}' text snippet='{txt[:50]}'")
        
        reply_btn = art.locator('div[role="button"]:has-text("Trả lời"), span:has-text("Trả lời")').first
        print("Clicking 'Trả lời'...")
        await reply_btn.click()
        await asyncio.sleep(2)
        
        active_input = await page.evaluate('''() => {
            const el = document.activeElement;
            const textboxes = Array.from(document.querySelectorAll('[role="textbox"], textarea')).map(tb => ({
                tag: tb.tagName,
                placeholder: tb.getAttribute('placeholder') || '',
                ariaLabel: tb.getAttribute('aria-label') || '',
                rect: tb.getBoundingClientRect(),
                isActive: tb === el
            }));
            return {
                activeTag: el ? el.tagName : null,
                activeRole: el ? el.getAttribute('role') : null,
                activePlaceholder: el ? el.getAttribute('placeholder') : null,
                allTextboxes: textboxes
            };
        }''')
        print("After clicking 'Trả lời':")
        print(json.dumps(active_input, ensure_ascii=False, indent=2))
        
        # Chụp màn hình để kiểm tra
        await page.screenshot(path="logs/after_reply_click.png")
        print("Saved screenshot to logs/after_reply_click.png")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_reply_click())
