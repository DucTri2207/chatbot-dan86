import asyncio
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

async def inspect_details():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        page = await context.new_page()
        
        url = "https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512"
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        
        # Click vào item đầu tiên trong danh sách bên trái
        threads = page.locator('div[role="listitem"], [role="grid"] [role="row"]').filter(has_text="Có những điều")
        print("Found threads:", await threads.count())
        
        # Dump chi tiết DOM của panel bình luận bên phải
        details = await page.evaluate('''() => {
            // Lấy tất cả elements có text "Trả lời"
            const replyBtns = Array.from(document.querySelectorAll('*')).filter(el => {
                return (el.innerText || '').trim() === 'Trả lời' && el.children.length === 0;
            }).map(el => {
                const parent = el.parentElement;
                const grandParent = parent ? parent.parentElement : null;
                const greatGrand = grandParent ? grandParent.parentElement : null;
                return {
                    tagName: el.tagName,
                    role: el.getAttribute('role'),
                    className: el.className,
                    parentHtml: parent ? parent.outerHTML.slice(0, 200) : '',
                    grandParentText: grandParent ? grandParent.innerText.slice(0, 200) : '',
                    rect: el.getBoundingClientRect()
                };
            });
            
            // Tìm các bình luận trong vùng chi tiết
            // Thường nằm trong container có text "Lệ Thuyền" hoặc các bình luận khác
            const allElementsWithText = Array.from(document.querySelectorAll('*')).filter(el => {
                const t = (el.innerText || '');
                return t.includes('Lệ Thuyền') && el.children.length < 5;
            }).map(el => ({
                tag: el.tagName,
                text: el.innerText.slice(0, 100),
                rect: el.getBoundingClientRect(),
                parentTag: el.parentElement ? el.parentElement.tagName : ''
            }));

            // Tìm tất cả các button hoặc action có thể có quanh comment Lệ Thuyền
            const actionEls = Array.from(document.querySelectorAll('[role="button"], div[role="button"], span[role="button"], button'))
                .filter(b => b.getBoundingClientRect().left > 700)
                .map(b => ({
                    text: (b.innerText || '').trim(),
                    ariaLabel: b.getAttribute('aria-label') || '',
                    role: b.getAttribute('role'),
                    rect: b.getBoundingClientRect()
                }));

            return {
                replyBtns,
                commentElements: allElementsWithText.slice(0, 10),
                actionEls: actionEls.slice(0, 25)
            };
        }''')
        
        print("Details Dump:")
        print(json.dumps(details, ensure_ascii=False, indent=2))
        
        # Thử hover vào bình luận của Lệ Thuyền xem có hiện thêm nút Gửi tin nhắn / Nhắn tin không
        le_thuyen = page.locator('text="Lệ Thuyền"').first
        if await le_thuyen.count() > 0:
            print("Hovering on Lệ Thuyền...")
            await le_thuyen.hover()
            await asyncio.sleep(1)
            
            hover_actions = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('[role="button"], div[role="button"], span[role="button"], button'))
                    .filter(b => b.getBoundingClientRect().left > 700)
                    .map(b => ({
                        text: (b.innerText || '').trim(),
                        ariaLabel: b.getAttribute('aria-label') || '',
                        rect: b.getBoundingClientRect()
                    }));
            }''')
            print("Hover actions:")
            print(json.dumps(hover_actions, ensure_ascii=False, indent=2))
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_details())
