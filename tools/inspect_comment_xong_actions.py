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
        print(f"Navigating to {url}...")
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
                
        # Check buttons on the header or the thread
        # 1. Look for three dots button next to "Quảng bá"
        dots_btn = await p.locator('[aria-label="Tùy chọn khác"], [aria-label="Xem thêm"], button:has([aria-label="Tùy chọn khác"])').all()
        print("Dots buttons found count:", len(dots_btn))
        
        # Or look at all buttons in the right pane header
        header_buttons = await p.evaluate('''() => {
            const btns = Array.from(document.querySelectorAll('button, div[role="button"]'));
            return btns.map(b => ({
                text: (b.innerText || '').trim(),
                ariaLabel: b.getAttribute('aria-label') || '',
                role: b.getAttribute('role') || ''
            })).filter(b => b.text || b.ariaLabel);
        }''')
        print("Header/Page buttons snippet:", json.dumps(header_buttons[:30], ensure_ascii=False, indent=2))
        
        # Try clicking the three dots button next to Quảng bá
        # Look for the three dots button
        more_btn = p.locator('div[role="button"]:has-text("...")').or_(p.locator('button:has-text("...")')).first
        if await more_btn.count() == 0:
            # Try by svg or aria
            more_btn = p.locator('div[role="button"][tabindex="0"]').filter(has=p.locator('svg')).first
            
        # Let's inspect the specific element at top right of detail pane
        right_header = await p.evaluate('''() => {
            // Find container near Quảng bá
            const qb = Array.from(document.querySelectorAll('*')).find(el => el.innerText === 'Quảng bá');
            if (qb && qb.parentElement) {
                return qb.parentElement.innerHTML;
            }
            return 'not found';
        }''')
        print("Right header around Quảng bá:", right_header[:500])
        
        await b.close()

if __name__ == "__main__":
    asyncio.run(inspect())
