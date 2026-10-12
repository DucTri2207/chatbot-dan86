import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.async_api import async_playwright
from bot.page_bot_engine import create_bot_browser_context, verify_logged_in, safe_click, human_sleep

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("restore_done")

async def main():
    async with async_playwright() as playwright:
        browser, context = await create_bot_browser_context(playwright, headless=True)
        page = await context.new_page()
        
        target_urls = [
            ("Messenger DONE", "https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512&mailbox_folder=DONE"),
            ("All DONE", "https://business.facebook.com/latest/inbox/all?asset_id=104011958817512&mailbox_folder=DONE"),
            ("Comments DONE", "https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512&mailbox_folder=DONE"),
        ]
        
        for name, url in target_urls:
            logger.info("--- Kiểm tra thư mục: %s ---", name)
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await human_sleep(4.0, 6.0)
            
            is_ok = await verify_logged_in(page)
            logger.info("Trạng thái đăng nhập: %s (URL: %s)", is_ok, page.url)
            if not is_ok:
                logger.warning("Chưa đăng nhập được vào %s, bỏ qua.", name)
                continue
                
            # Lưu ảnh chụp màn hình
            safe_name = name.lower().replace(" ", "_")
            screenshot_path = f"logs/folder_{safe_name}.png"
            os.makedirs("logs", exist_ok=True)
            await page.screenshot(path=screenshot_path)
            logger.info("Đã chụp ảnh màn hình: %s", screenshot_path)
            
            # Quét danh sách các hội thoại trong mục DONE
            items_info = await page.evaluate('''() => {
                const listItems = Array.from(document.querySelectorAll(
                    'div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"], [role="row"]'
                ));
                return listItems.map((el, idx) => {
                    const text = (el.innerText || '').trim().replace(/\\n+/g, ' | ');
                    const rect = el.getBoundingClientRect();
                    return { idx, text: text.slice(0, 100), top: rect.top, height: rect.height, visible: rect.height > 20 };
                }).filter(i => i.visible && i.top > 60 && i.top < 880);
            }''')
            
            logger.info("Tìm thấy %d mục trong %s:", len(items_info), name)
            for it in items_info[:10]:
                logger.info("  [%d] %s", it['idx'], it['text'])
                
            # Quét các nút thao tác trên thanh header / toolbar
            buttons_info = await page.evaluate('''() => {
                const btns = Array.from(document.querySelectorAll('[role="button"], button'));
                return btns.map(b => {
                    const aria = b.getAttribute('aria-label') || '';
                    const text = (b.innerText || '').trim();
                    const title = b.getAttribute('title') || '';
                    const rect = b.getBoundingClientRect();
                    return { aria, text: text.slice(0, 40), title, top: rect.top, left: rect.left };
                }).filter(b => (b.aria || b.text || b.title) && b.top > 40 && b.top < 200);
            }''')
            
            action_keywords = ['hộp thư', 'chuyển', 'inbox', 'move', 'chưa đọc', 'xong', 'lưu trữ', 'bỏ', 'khôi phục', 'chính', 'đánh dấu']
            for b in buttons_info:
                comb = f"{b['aria']} {b['text']} {b['title']}".lower()
                if any(k in comb for k in action_keywords):
                    logger.info("   Nút thao tác: aria='%s', text='%s', title='%s' (top=%.0f, left=%.0f)", b['aria'], b['text'], b['title'], b['top'], b['left'])

        await context.close()
        if browser:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
