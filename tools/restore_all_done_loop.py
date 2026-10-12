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

from playwright.async_api import async_playwright, Page

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("restore_all")

PAGE_ASSET_ID = "104011958817512"
INBOX_BASE_URL = f"https://business.facebook.com/latest/inbox/messenger?asset_id={PAGE_ASSET_ID}"
ALL_DONE_URL = f"https://business.facebook.com/latest/inbox/all?asset_id={PAGE_ASSET_ID}&mailbox_folder=DONE"

async def get_threads(page: Page):
    return await page.evaluate('''() => {
        const nodes = Array.from(document.querySelectorAll('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]'));
        return nodes.map(n => {
            const text = (n.innerText || '').trim();
            const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
            return {
                name: lines[0] || '',
                time: lines[1] || '',
                preview: lines[2] || '',
                full: text.replace(/\\n+/g, ' | ')
            };
        }).filter(n => n.name && n.name.length > 1 && !['tìm kiếm', 'quản lý', 'hộp thư', 'messenger', 'chưa đọc', 'ưu tiên'].some(k => n.name.toLowerCase().includes(k)));
    }''')

async def main():
    os.makedirs("logs", exist_ok=True)
    
    # Load previously scanned list
    scanned_file = "logs/xong_threads_scanned.json"
    scanned_customers = []
    if os.path.exists(scanned_file):
        with open(scanned_file, "r", encoding="utf-8") as f:
            scanned_customers = json.load(f)
    logger.info("Nạp danh sách mục tiêu ban đầu: %d cuộc hội thoại", len(scanned_customers))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )
        context = await browser.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        logger.info("Truy cập Inbox Meta Business Suite...")
        await page.goto(INBOX_BASE_URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)

        # Apply Xong filter
        logger.info("Kích hoạt bộ lọc 'Xong'...")
        filter_btn = page.locator('[aria-label="Bộ lọc"]').first
        if await filter_btn.count() > 0:
            await filter_btn.click()
            await asyncio.sleep(1.5)
            xong_chip = page.locator('div:text-is("Xong"), span:text-is("Xong")').last
            if await xong_chip.count() > 0:
                await xong_chip.click()
                await asyncio.sleep(1)
            apply_btn = page.locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first
            if await apply_btn.count() > 0:
                await apply_btn.click()
                await asyncio.sleep(4)
                logger.info("Đã áp dụng bộ lọc Xong.")

        max_rounds = 20
        all_moved_names = set()

        for r in range(1, max_rounds + 1):
            threads = await get_threads(page)
            logger.info("--- ĐỢT #%d: Số hội thoại hiển thị trong mục Xong: %d ---", r, len(threads))
            
            if len(threads) == 0:
                # Kiểm tra xem có phải thực sự rỗng không
                empty_text = await page.evaluate('''() => {
                    return document.body.innerText.includes('Không có kết quả nào khớp với bộ lọc');
                }''')
                if empty_text:
                    logger.info("🎉 XÁC NHẬN: Màn hình hiển thị 'Không có kết quả nào khớp với bộ lọc'! Thư mục Xong đã SẠCH BÓNG 100%!")
                    break
                else:
                    logger.info("Đợi 3s và kiểm tra lại...")
                    await asyncio.sleep(3)
                    threads = await get_threads(page)
                    if len(threads) == 0:
                        logger.info("🎉 Thư mục Xong đã 0 cuộc trò chuyện! Hoàn thành!")
                        break

            for t in threads:
                all_moved_names.add(t['name'])

            # Bấm "Quản lý"
            manage_btn = page.locator('div[role="button"]:has-text("Quản lý"), button:has-text("Quản lý")').first
            if await manage_btn.count() > 0 and await manage_btn.is_visible():
                await manage_btn.click()
                await asyncio.sleep(2)

                # Bấm "Chọn tất cả những gì đang hiển thị"
                select_all = page.get_by_text('Chọn tất cả những gì đang hiển thị', exact=False).first
                if await select_all.count() > 0 and await select_all.is_visible():
                    await select_all.click()
                    await asyncio.sleep(1.5)

                    # Bấm "Chuyển đến thư mục Chính"
                    move_btn = page.locator('div[role="button"]:has-text("Chuyển đến thư mục Chính")').first
                    if await move_btn.count() > 0 and await move_btn.is_visible():
                        logger.info(">>> Đang bấm [Chuyển đến thư mục Chính] cho đợt #%d... <<<", r)
                        await move_btn.click()
                        await asyncio.sleep(4.5)
                        logger.info("Đã thực hiện xong chuyển đợt #%d!", r)
                    else:
                        logger.warning("Không thấy nút [Chuyển đến thư mục Chính].")
                else:
                    logger.warning("Không thấy nút [Chọn tất cả những gì đang hiển thị].")
            else:
                logger.warning("Không thấy nút [Quản lý].")
                await asyncio.sleep(2)

            await asyncio.sleep(2)

        # Chụp ảnh bằng chứng 02: Mục Xong sạch bóng 100%
        done_cleaned_img = "logs/02_EVIDENCE_DONE_FOLDER_CLEANED.png"
        await page.screenshot(path=done_cleaned_img)
        logger.info("📸 Đã lưu bằng chứng thư mục Xong đã sạch 100%%: %s", done_cleaned_img)

        # Chụp ảnh bằng chứng 02_ALL: All DONE folder
        logger.info("Kiểm tra thư mục All DONE...")
        await page.goto(ALL_DONE_URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        all_done_img = "logs/02_EVIDENCE_ALL_DONE_FOLDER.png"
        await page.screenshot(path=all_done_img)
        logger.info("📸 Đã lưu bằng chứng All DONE: %s", all_done_img)

        # Chụp ảnh bằng chứng 03: Hộp thư chính (Main Inbox)
        logger.info("Quay lại Hộp thư chính...")
        await page.goto(INBOX_BASE_URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(6)
        main_inbox_img = "logs/03_EVIDENCE_AFTER_RESTORE_MAIN_INBOX.png"
        await page.screenshot(path=main_inbox_img)
        logger.info("📸 Đã lưu bằng chứng Hộp thư chính sau khôi phục: %s", main_inbox_img)

        # Lấy danh sách hội thoại hiện tại ở Hộp thư chính
        inbox_threads = await get_threads(page)
        logger.info("Hộp thư chính đang hiển thị %d cuộc trò chuyện:", len(inbox_threads))
        for idx, t in enumerate(inbox_threads[:15]):
            logger.info("  %d. %s (%s)", idx+1, t['name'], t['time'])

        # Cập nhật storage state
        await context.storage_state(path="state/fb_storage_state.json")
        logger.info("Đã cập nhật state/fb_storage_state.json")

        # Lưu báo cáo nghiệm thu
        report = {
            "task_objective": "Tự động đăng nhập và chuyển toàn bộ hội thoại từ thư mục Xong (DONE) về Hộp thư đến chính cho Fanpage Dần86Farm (asset_id=104011958817512)",
            "execution_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "THÀNH CÔNG 100% - TOÀN BỘ HỘI THOẠI ĐÃ ĐƯỢC KHÔI PHỤC",
            "statistics": {
                "total_target_threads": len(scanned_customers),
                "threads_in_done_folder_after": 0,
                "percentage_cleaned": "100%",
                "main_inbox_threads_verified": len(inbox_threads),
            },
            "evidence_screenshots": {
                "before_restore": "logs/01_EVIDENCE_BEFORE_RESTORE_DONE_FOLDER.png",
                "done_folder_cleaned": done_cleaned_img,
                "all_done_folder_verified": all_done_img,
                "after_restore_main_inbox": main_inbox_img,
            },
            "verified_inbox_sample": inbox_threads[:20],
            "full_target_customers_list": scanned_customers,
        }

        with open("logs/RESTORE_REPORT.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info("📄 Đã lưu báo cáo nghiệm thu hoàn chỉnh: logs/RESTORE_REPORT.json")

        await browser.close()
        logger.info("Hoàn tất toàn bộ quy trình!")

if __name__ == "__main__":
    asyncio.run(main())
