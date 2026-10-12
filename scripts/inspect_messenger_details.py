import asyncio
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

PAGE_NAMES = [
    "dần86",
    "dan86",
    "dần 86",
    "dan 86",
    "dan86farm",
    "dần86farm",
    "bá lộc green",
    "ba loc green",
    "quà tặng thuần việt dan86",
    "quà tặng thuần việt",
    "dan86 - quà tặng thuần việt",
    "dan86 quà tặng thuần việt",
]

async def inspect_messenger_details():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        page = await context.new_page()
        await page.goto("https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512", wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        
        details = await page.evaluate('''() => {
            // 1. Tên khách hàng ở tiêu đề chat
            let customerName = "bạn";
            // Header trên cùng của khung chat
            const headerNameEl = document.querySelector('div[role="main"] h2, div[role="main"] h1, [role="region"] h2');
            if (headerNameEl) {
                customerName = headerNameEl.innerText.trim();
            } else {
                // Fallback: Tìm các heading ở giữa màn hình (x: 400..1000, y < 150)
                const headings = Array.from(document.querySelectorAll('h1, h2, h3, [role="heading"]'))
                    .filter(h => {
                        const r = h.getBoundingClientRect();
                        return r.left > 350 && r.left < 900 && r.top < 150 && h.innerText.trim().length > 1;
                    });
                if (headings.length > 0) {
                    customerName = headings[0].innerText.trim();
                }
            }

            // 2. Tìm tất cả các tin nhắn trong vùng chat
            // Các bong bóng chat nằm trong khoảng x: 380 đến 1100
            const chatNodes = Array.from(document.querySelectorAll('[dir="auto"], [role="row"]'))
                .filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.left > 380 && r.right < 1120 && r.top > 120 && r.bottom < 840 && r.height >= 16;
                });

            // Lọc ra các dòng text thực sự là tin nhắn
            const messageList = [];
            for (const node of chatNodes) {
                const txt = (node.innerText || '').trim();
                if (!txt || txt.length < 1) continue;
                // Bỏ qua các text tiêu đề hệ thống
                if (txt.includes('Đoạn chat này chứa tin trả lời') || txt.includes('đã trả lời một quảng cáo') || txt.includes('Bạn có muốn được chỉ định')) {
                    continue;
                }
                const r = node.getBoundingClientRect();
                // Phân biệt tin của Page hay của Khách:
                // Tin của Page: nằm bên phải (r.left > 650) HOẶC có background xanh (rgb(0, 132, 255) / #0084ff)
                const computedStyle = window.getComputedStyle(node);
                const parentStyle = node.parentElement ? window.getComputedStyle(node.parentElement) : null;
                const isRight = r.left > 620;
                
                messageList.push({
                    text: txt,
                    left: r.left,
                    top: r.top,
                    width: r.width,
                    isRight: isRight
                });
            }

            // Tìm composer box
            const composer = document.querySelector('div[role="textbox"][contenteditable="true"], textarea');

            return {
                customerName,
                totalMessages: messageList.length,
                messages: messageList,
                hasComposer: !!composer,
                composerPlaceholder: composer ? (composer.getAttribute('placeholder') || composer.getAttribute('aria-label')) : null
            };
        }''')
        
        print("Messenger details:")
        print(json.dumps(details, ensure_ascii=False, indent=2))
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_messenger_details())
