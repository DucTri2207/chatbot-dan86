import asyncio
import json
import logging
import os
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from playwright.async_api import async_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("clean_fb_comments")

PAGE_ASSET_ID = "104011958817512"

async def apply_xong_filter(page):
    """Áp dụng bộ lọc Xong trên tab Bình luận Facebook một cách tin cậy."""
    filter_btn = page.locator('[aria-label="Bộ lọc"]').first
    if await filter_btn.count() == 0:
        logger.warning("Không tìm thấy nút Bộ lọc")
        return False
        
    await filter_btn.click()
    await asyncio.sleep(2)
    
    # Cuộn dialog bộ lọc nếu cần
    await page.evaluate('''() => {
        const dialog = document.querySelector('[role="dialog"]');
        if (dialog) {
            const scrollable = Array.from(dialog.querySelectorAll('*')).filter(el => el.scrollHeight > el.clientHeight && el.clientHeight > 200);
            for (const s of scrollable) {
                s.scrollTop = s.scrollHeight;
            }
        }
    }''')
    await asyncio.sleep(1)
    
    xong_elem = page.locator('[role="dialog"]').locator('div:text-is("Xong"), span:text-is("Xong")').first
    if await xong_elem.count() > 0:
        await xong_elem.click()
        await asyncio.sleep(1)
    else:
        logger.warning("Không tìm thấy mục Xong trong dialog")
        return False
        
    apply_btn = page.locator('[role="dialog"]').locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first
    if await apply_btn.count() > 0:
        await apply_btn.click()
        await asyncio.sleep(4)
        logger.info("Đã áp dụng bộ lọc Xong thành công.")
        return True
    return False

async def scroll_list_container(page, delta=700):
    """Cuộn danh sách bài viết / bình luận để trigger lazy loading."""
    scrolled = await page.evaluate('''(delta) => {
        const containers = Array.from(document.querySelectorAll('div[style*="overflow"], div[class*="scroll"], div[role="navigation"], div[role="grid"]'))
            .filter(el => {
                const r = el.getBoundingClientRect();
                return r.x >= 50 && r.x <= 380 && r.height > 300;
            });
        let any = false;
        for (const c of containers) {
            c.scrollTop += delta;
            any = true;
        }
        return any;
    }''', delta)
    return scrolled

async def scroll_to_top_container(page):
    """Cuộn về đầu danh sách bài viết."""
    await page.evaluate('''() => {
        const containers = Array.from(document.querySelectorAll('div[style*="overflow"], div[class*="scroll"], div[role="navigation"], div[role="grid"]'))
            .filter(el => {
                const r = el.getBoundingClientRect();
                return r.x >= 50 && r.x <= 380 && r.height > 300;
            });
        for (const c of containers) {
            c.scrollTop = 0;
        }
    }''')

async def check_empty_state(page):
    """Kiểm tra thông báo rỗng trên giao diện."""
    return await page.evaluate('''() => {
        const text = document.body.innerText || '';
        return text.includes('Không có kết quả nào khớp với bộ lọc') || 
               text.includes('Không có bình luận') ||
               text.includes('Không có tin nhắn') ||
               text.includes('Không có cuộc trò chuyện');
    }''')

async def run():
    os.makedirs("logs/audit", exist_ok=True)
    
    # Tải danh sách đã chuyển trước đó nếu có
    prev_moved = []
    if os.path.exists("logs/audit/fb_comments_moved.json"):
        try:
            with open("logs/audit/fb_comments_moved.json", "r", encoding="utf-8") as f:
                d = json.load(f)
                prev_moved = d.get("moved_posts", [])
        except Exception:
            pass

    newly_moved_posts = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = await browser.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        url = f"https://business.facebook.com/latest/inbox/facebook?asset_id={PAGE_ASSET_ID}"
        
        overall_completed = False
        pass_count = 0
        max_passes = 12

        while not overall_completed and pass_count < max_passes:
            pass_count += 1
            logger.info("=== BẮT ĐẦU PASS #%d: Điều hướng tới %s ===", pass_count, url)
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(5)
            
            applied = await apply_xong_filter(page)
            if not applied:
                logger.warning("Không áp dụng được bộ lọc Xong tại pass %d, thử lại...", pass_count)
                continue

            if pass_count == 1:
                await page.screenshot(path="logs/audit/fb_comments_before_clean.png")

            iteration = 0
            consecutive_scrolls = 0
            
            while iteration < 300:
                iteration += 1
                move_btns = page.locator('div[aria-label="Chuyển đến thư mục Chính"], [role="gridcell"][aria-label="Chuyển đến thư mục Chính"]')
                count = await move_btns.count()
                
                if count > 0:
                    consecutive_scrolls = 0
                    target_btn = move_btns.first
                    
                    try:
                        row_text = await target_btn.evaluate('''el => {
                            const row = el.closest('div[role="presentation"], div._a6ag._a6ah, [role="listitem"]');
                            return row ? (row.innerText || '').split('\\n')[0] : '';
                        }''')
                    except Exception:
                        row_text = f"Post #{len(newly_moved_posts) + 1}"

                    title = row_text.strip() if row_text else f"Post #{len(newly_moved_posts) + 1}"
                    newly_moved_posts.append(title)
                    logger.info("Pass #%d [Action #%d] (Available: %d): Chuyển '%s' về Hộp thư đến...", 
                                pass_count, len(newly_moved_posts), count, title[:45])
                    
                    try:
                        await target_btn.click(timeout=5000)
                    except Exception as e:
                        logger.warning("Standard click failed, force clicking: %s", e)
                        await target_btn.click(force=True, timeout=5000)
                        
                    await asyncio.sleep(1.3)
                else:
                    consecutive_scrolls += 1
                    logger.info("Không thấy nút chuyển trực tiếp (Lần cuộn thử #%d). Đang cuộn danh sách...", consecutive_scrolls)
                    await scroll_list_container(page, delta=600)
                    await asyncio.sleep(1.8)
                    
                    # Kiểm tra lại sau khi cuộn
                    new_count = await move_btns.count()
                    if new_count == 0:
                        if consecutive_scrolls >= 4:
                            logger.info("Đã cuộn %d lần liên tiếp nhưng không còn nút nào trong view hiện tại.", consecutive_scrolls)
                            break
                    else:
                        consecutive_scrolls = 0

            # Kiểm tra trạng thái rỗng và deep scroll audit trong pass này
            empty = await check_empty_state(page)
            remaining_btns = await page.locator('div[aria-label="Chuyển đến thư mục Chính"]').count()
            logger.info("Kết thúc pass #%d. Empty state: %s, Remaining btns in view: %d", pass_count, empty, remaining_btns)

            # Deep scroll audit: cuộn 12 lần liên tiếp để xem có load thêm bài cũ nào không
            logger.info("Đang thực hiện Deep Scroll Audit để kiểm tra bài ẩn sâu...")
            await scroll_to_top_container(page)
            await asyncio.sleep(1)
            
            hidden_found = False
            for s in range(12):
                await scroll_list_container(page, delta=800)
                await asyncio.sleep(1.2)
                btns_deep = await page.locator('div[aria-label="Chuyển đến thư mục Chính"]').count()
                if btns_deep > 0:
                    logger.info("Phát hiện %d bài viết xuất hiện ở độ sâu s=%d! Tiếp tục pass mới...", btns_deep, s)
                    hidden_found = True
                    break
                    
            if not hidden_found and remaining_btns == 0 and empty:
                logger.info("✅ XÁC NHẬN: Không còn bài viết nào trong thư mục Xong sau deep scroll audit!")
                overall_completed = True
            else:
                logger.info("Vẫn còn bài viết hoặc chưa đạt empty state, tiếp tục pass kế tiếp...")

        # Chụp ảnh bằng chứng nghiệm thu hoàn tất
        logger.info("Chụp ảnh bằng chứng hoàn tất dọn sạch...")
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        await apply_xong_filter(page)
        await asyncio.sleep(3)
        
        await page.screenshot(path="logs/04_EVIDENCE_FB_COMMENTS_DONE_CLEANED.png")
        await page.screenshot(path="logs/audit/fb_comments_cleaned.png")
        await page.screenshot(path="logs/audit/final_fb_comments_xong.png")
        
        final_empty = await check_empty_state(page)
        final_btns = await page.locator('div[aria-label="Chuyển đến thư mục Chính"]').count()
        logger.info("=== KẾT QUẢ CUỐI CÙNG FB COMMENTS XONG ===")
        logger.info("Empty state text present: %s", final_empty)
        logger.info("Remaining move buttons: %d", final_btns)
        logger.info("Total posts moved in this run: %d", len(newly_moved_posts))
        
        # Kết hợp danh sách bài viết đã chuyển
        all_moved_posts = prev_moved + newly_moved_posts
        # Lưu kết quả
        with open("logs/audit/fb_comments_moved.json", "w", encoding="utf-8") as f:
            json.dump({
                "total_moved": len(all_moved_posts),
                "moved_posts": all_moved_posts,
                "newly_moved_in_this_run": newly_moved_posts,
                "empty_state": final_empty,
                "remaining_btns": final_btns
            }, f, ensure_ascii=False, indent=2)

        # Cập nhật storage state
        await context.storage_state(path="state/fb_storage_state.json")
        await browser.close()
        logger.info("Hoàn tất quy trình khôi phục Facebook Comments DONE!")

if __name__ == "__main__":
    asyncio.run(run())
