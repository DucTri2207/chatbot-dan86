import asyncio
import json
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from playwright.async_api import async_playwright

PAGE_ASSET_ID = "104011958817512"

async def inspect():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        p = await ctx.new_page()
        url = f"https://business.facebook.com/latest/inbox/facebook?asset_id={PAGE_ASSET_ID}"
        await p.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(5)
        
        # Apply Xong filter
        filter_btn = p.locator('[aria-label="Bộ lọc"]').first
        if await filter_btn.count() > 0:
            await filter_btn.click()
            await asyncio.sleep(2)
            xong_elem = p.locator('[role="dialog"]').locator('div:text-is("Xong"), span:text-is("Xong")').first
            if await xong_elem.count() > 0:
                await xong_elem.click()
                await asyncio.sleep(1)
            apply_btn = p.locator('[role="dialog"]').locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first
            if await apply_btn.count() > 0:
                await apply_btn.click()
                await asyncio.sleep(4)

        # Inspect the green checkmark elements or the right icons in the thread list
        icons = await p.evaluate('''() => {
            // Find all svg elements in the thread list
            const svgs = Array.from(document.querySelectorAll('div[role="presentation"].x1ypdohk svg, div._a6ag._a6ah svg, [role="listitem"] svg'));
            return svgs.map(s => {
                const parent = s.closest('button, [role="button"], div');
                return {
                    ariaLabel: s.getAttribute('aria-label') || (parent ? parent.getAttribute('aria-label') : ''),
                    title: s.getAttribute('title') || (parent ? parent.getAttribute('title') : ''),
                    parentRole: parent ? parent.getAttribute('role') : '',
                    viewBox: s.getAttribute('viewBox'),
                    innerHTML: s.innerHTML
                };
            });
        }''')
        print("SVGs found in thread list:", json.dumps(icons[:15], ensure_ascii=False, indent=2))
        
        # Also check what happens if we look at the second item:
        second_item = p.locator('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]').nth(1)
        if await second_item.count() > 0:
            await second_item.hover()
            await asyncio.sleep(1)
            hover_icons = await p.evaluate('''() => {
                const el = Array.from(document.querySelectorAll('*')).filter(e => {
                    const l = e.getAttribute('aria-label') || '';
                    return l.includes('Chuyển') || l.includes('Xong') || l.includes('Hộp thư') || l.includes('Chính') || l.includes('Bỏ đánh dấu');
                });
                return el.map(e => ({
                    tag: e.tagName,
                    role: e.getAttribute('role'),
                    ariaLabel: e.getAttribute('aria-label'),
                    text: e.innerText
                }));
            }''')
            print("Elements with matching labels on hover:", json.dumps(hover_icons, ensure_ascii=False, indent=2))
            
        await b.close()

if __name__ == "__main__":
    asyncio.run(inspect())
