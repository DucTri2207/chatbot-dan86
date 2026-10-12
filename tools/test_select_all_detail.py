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

async def run():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(storage_state='state/fb_storage_state.json', viewport={'width': 1440, 'height': 900}, locale='vi-VN')
        p = await ctx.new_page()
        await p.goto('https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512', wait_until='domcontentloaded')
        await asyncio.sleep(4)
        
        # Apply Xong
        f_btn = p.locator('[aria-label="Bộ lọc"]').first
        await f_btn.click()
        await asyncio.sleep(1.5)
        await p.locator('div:text-is("Xong"), span:text-is("Xong")').last.click()
        await asyncio.sleep(1)
        await p.locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first.click()
        await asyncio.sleep(4)
        
        # Click Quản lý
        manage_btn = p.locator('div[role="button"]:has-text("Quản lý"), button:has-text("Quản lý")').first
        await manage_btn.click()
        await asyncio.sleep(2)
        
        # Find element containing 'Chọn tất cả những gì đang hiển thị'
        el_info = await p.evaluate('''() => {
            const els = Array.from(document.querySelectorAll('*'));
            for (const el of els) {
                if ((el.innerText || '').includes('Chọn tất cả những gì đang hiển thị') && el.children.length === 0) {
                    const r = el.getBoundingClientRect();
                    return {
                        tag: el.tagName,
                        text: el.innerText,
                        className: el.className,
                        rect: {x: r.x, y: r.y, w: r.width, h: r.height}
                    };
                }
            }
            return null;
        }''')
        print("el_info:", el_info)
        
        # Click it by text or coordinates
        loc = p.get_by_text('Chọn tất cả những gì đang hiển thị', exact=False).first
        print("get_by_text count:", await loc.count())
        if await loc.count() > 0:
            await loc.click()
            await asyncio.sleep(2)
            await p.screenshot(path='logs/test_after_select_all_click.png')
            
            # Print what options are visible now
            options = await p.evaluate('''() => {
                const els = Array.from(document.querySelectorAll('div, span, button, [role="button"]'));
                return els.map(e => {
                    const r = e.getBoundingClientRect();
                    return {
                        tag: e.tagName,
                        role: e.getAttribute('role'),
                        text: (e.innerText || '').trim(),
                        aria: e.getAttribute('aria-label') || '',
                        rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}
                    };
                }).filter(e => e.rect.w > 40 && e.rect.h > 15 && e.rect.x > 400 && e.rect.y > 200 && e.text && !e.text.includes('\\n'));
            }''')
            print("Options visible after selecting all:", json.dumps(options, ensure_ascii=False, indent=2))
        
        await b.close()

if __name__ == "__main__":
    asyncio.run(run())
