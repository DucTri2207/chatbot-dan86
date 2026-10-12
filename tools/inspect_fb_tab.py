import asyncio
from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(storage_state='state/fb_storage_state.json', viewport={'width': 1440, 'height': 900}, locale='vi-VN')
        p = await ctx.new_page()
        await p.goto('https://business.facebook.com/latest/inbox/all?asset_id=104011958817512', wait_until='domcontentloaded')
        await asyncio.sleep(5)
        tabs = await p.evaluate('''() => {
            return Array.from(document.querySelectorAll('*')).filter(el => (el.innerText || '').trim() === 'Bình luận trên Facebook').slice(0, 5).map(el => ({
                tag: el.tagName,
                role: el.getAttribute('role'),
                href: el.getAttribute('href'),
                className: el.className
            }));
        }''')
        print('FB comment tabs found:', tabs)
        
        # Click the tab
        tab_btn = p.get_by_text("Bình luận trên Facebook", exact=True).first
        print("Tab count:", await tab_btn.count())
        if await tab_btn.count() > 0:
            await tab_btn.click()
            await asyncio.sleep(4)
            await p.screenshot(path="logs/audit/fb_comments_tab_view.png")
            print("Current URL:", p.url)
            # check filter
            filter_btn = p.locator('[aria-label="Bộ lọc"]').first
            print("Filter button count in FB comments:", await filter_btn.count())
            if await filter_btn.count() > 0:
                await filter_btn.click()
                await asyncio.sleep(2)
                dialog_text = await p.evaluate('''() => (document.querySelector('[role="dialog"]') || document.body).innerText''')
                print("Dialog text snippet:", dialog_text[:300].replace('\n', ' | '))
                print("Has Xong:", "Xong" in dialog_text)
                
        await b.close()

if __name__ == "__main__":
    asyncio.run(inspect())
