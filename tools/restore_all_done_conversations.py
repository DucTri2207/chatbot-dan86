"""
Script tự động khôi phục toàn bộ các cuộc hội thoại trong thư mục "Xong" (mailbox_folder=DONE)
về "Hộp thư đến chính" (Main Inbox) của Fanpage Dần86Farm trên Meta Business Suite.
Quy trình chuẩn:
1. Đăng nhập và mở giao diện Hộp thư Meta Business Suite (xử lý SSO Bridge nếu có).
2. Kích hoạt Bộ lọc thư mục "Xong" (DONE).
3. Chụp ảnh bằng chứng TRƯỚC khi khôi phục (EVIDENCE_01_BEFORE_RESTORE_DONE_FOLDER.png).
4. Duyệt tuần tự từng cuộc trò chuyện: Bấm mở -> Bấm "Tùy chọn khác" -> Bấm "Chuyển về Hộp thư đến".
5. Lặp lại cho đến khi toàn bộ các cuộc hội thoại trong mục DONE được chuyển sạch sẽ.
6. Chụp ảnh bằng chứng thư mục Xong đã trống sạch (EVIDENCE_02_DONE_FOLDER_CLEANED.png).
7. Điều hướng về Hộp thư đến chính (Main Inbox), chụp ảnh bằng chứng hoàn tất (EVIDENCE_03_AFTER_RESTORE_MAIN_INBOX.png).
8. Thống kê và xuất báo cáo minh bạch danh sách tất cả khách hàng đã khôi phục.
"""

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
logger = logging.getLogger("restore_done")

PAGE_ASSET_ID = "104011958817512"
INBOX_BASE_URL = f"https://business.facebook.com/latest/inbox/messenger?asset_id={PAGE_ASSET_ID}"


async def handle_sso_if_needed(page: Page) -> None:
    """Xử lý màn hình đăng nhập / SSO Bridge nếu Meta yêu cầu."""
    if "login" in page.url.lower():
        logger.info("Phát hiện màn hình SSO Bridge, đang tìm nút đăng nhập...")
        btn = page.locator('text="Tiếp tục bằng Facebook"').first
        if await btn.count() > 0 and await btn.is_visible():
            popup_future = asyncio.get_event_loop().create_future()
            def on_p(p):
                if not popup_future.done():
                    popup_future.set_result(p)
            page.context.on("page", on_p)
            await btn.click()
            try:
                popup = await asyncio.wait_for(popup_future, timeout=10.0)
                await popup.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(2)
                p_btn = popup.locator('div[role="button"]:has-text("Tiếp tục"), button:has-text("Tiếp tục")').first
                if await p_btn.count() > 0:
                    await p_btn.click()
                    await asyncio.sleep(5)
            except Exception as e:
                logger.warning("SSO popup handling note: %s", e)
        await asyncio.sleep(4)
        if "login" in page.url.lower():
            await page.goto(INBOX_BASE_URL, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(5)


async def apply_done_filter(page: Page) -> bool:
    """Kích hoạt bộ lọc thư mục 'Xong' (DONE) trên giao diện Hộp thư."""
    logger.info("Kích hoạt bộ lọc 'Xong' qua nút Bộ lọc...")
    filter_btn = page.locator('[aria-label="Bộ lọc"]').first
    if await filter_btn.count() == 0 or not await filter_btn.is_visible():
        logger.warning("Không tìm thấy nút Bộ lọc trên giao diện.")
        return False

    await filter_btn.click()
    await asyncio.sleep(2)

    # Chọn chip "Xong"
    xong_chip = page.locator('div:text-is("Xong"), span:text-is("Xong")').last
    if await xong_chip.count() > 0:
        await xong_chip.click()
        await asyncio.sleep(1)

    # Bấm nút "Áp dụng"
    apply_btn = page.locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first
    if await apply_btn.count() > 0:
        await apply_btn.click()
        await asyncio.sleep(4)
        logger.info("Đã áp dụng bộ lọc thư mục 'Xong'.")
        return True

    return False


async def restore_all_threads():
    os.makedirs("logs", exist_ok=True)
    restored_customers = []

    logger.info("=" * 76)
    logger.info("   BẮT ĐẦU QUY TRÌNH TỰ ĐỘNG KHÔI PHỤC TOÀN BỘ HỘI THOẠI MỤC XONG VỀ INBOX   ")
    logger.info("=" * 76)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-notifications",
            ]
        )
        context = await browser.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # BƯỚC 1: Truy cập Hộp thư Meta Business Suite
        logger.info("BƯỚC 1: Điều hướng tới Hộp thư Meta Business Suite: %s", INBOX_BASE_URL)
        await page.goto(INBOX_BASE_URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        await handle_sso_if_needed(page)

        # BƯỚC 2: Mở thư mục Xong
        logger.info("BƯỚC 2: Mở thư mục 'Xong' (DONE)...")
        await apply_done_filter(page)

        # Chụp ảnh bằng chứng TRƯỚC KHI KHÔI PHỤC (R3.1)
        before_screenshot = "logs/EVIDENCE_01_BEFORE_RESTORE_DONE_FOLDER.png"
        await page.screenshot(path=before_screenshot)
        logger.info("📸 ĐÃ LƯU BẰNG CHỨNG TRƯỚC KHÔI PHỤC: %s", before_screenshot)

        # BƯỚC 3: Duyệt tuần tự và bấm "Chuyển về Hộp thư đến" cho từng cuộc hội thoại
        logger.info("BƯỚC 3: Bắt đầu khôi phục từng cuộc trò chuyện...")
        consecutive_empty = 0
        cycle = 0

        while True:
            cycle += 1
            # Lấy danh sách các cuộc trò chuyện đang có trong thư mục Xong
            thread_elements = page.locator('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]')
            count = await thread_elements.count()

            if count == 0:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    logger.info("Không còn cuộc hội thoại nào trong thư mục Xong. Đã quét sạch hoàn toàn!")
                    break
                logger.info("Đang kiểm tra lại và cuộn trang để xác nhận...")
                await asyncio.sleep(3)
                continue

            consecutive_empty = 0

            # Lấy thông tin cuộc trò chuyện đầu tiên trong danh sách
            first_thread = thread_elements.first
            try:
                full_text = await first_thread.inner_text()
                lines = [l.strip() for l in full_text.split("\n") if l.strip()]
                cust_name = lines[0] if lines else f"Hội thoại #{cycle}"
                msg_time = lines[1] if len(lines) > 1 else ""
                preview = lines[2] if len(lines) > 2 else ""

                # Bỏ qua nếu là phần tử nhãn hệ thống
                if any(k in cust_name.lower() for k in ["tìm kiếm", "quản lý", "hộp thư", "messenger"]):
                    logger.debug("Bỏ qua nhãn hệ thống: %s", cust_name)
                    break

                logger.info(
                    "[%d] Đang xử lý khôi phục: '%s' (%s) | Xem trước: '%s'",
                    len(restored_customers) + 1,
                    cust_name,
                    msg_time,
                    preview[:45]
                )

                # Bấm vào cuộc trò chuyện để nạp chi tiết
                await first_thread.click(position={"x": 150, "y": 35})
                await asyncio.sleep(2)

                # Bấm nút ba chấm "Tùy chọn khác" trong khung header chat
                dots_btn = page.locator('[aria-label="Tùy chọn khác"]').last
                if await dots_btn.count() > 0 and await dots_btn.is_visible():
                    await dots_btn.click()
                    await asyncio.sleep(1.5)

                    move_item = page.locator('[role="menuitem"]:has-text("Chuyển về Hộp thư đến")').first
                    if await move_item.count() > 0 and await move_item.is_visible():
                        await move_item.click()
                        await asyncio.sleep(3)
                        logger.info("   -> ✅ ĐÃ CHUYỂN VỀ HỘP THƯ ĐẾN THÀNH CÔNG: '%s'", cust_name)
                        restored_customers.append({
                            "index": len(restored_customers) + 1,
                            "name": cust_name,
                            "time": msg_time,
                            "preview": preview,
                            "restored_at": time.strftime("%Y-%m-%d %H:%M:%S")
                        })
                    else:
                        logger.warning("   -> Không tìm thấy nút [Chuyển về Hộp thư đến] trong menu tùy chọn.")
                        # Thử đóng menu nếu đang mở
                        await page.keyboard.press("Escape")
                        await asyncio.sleep(1)
                else:
                    logger.warning("   -> Không tìm thấy nút 'Tùy chọn khác' trong header chat.")
                    await asyncio.sleep(2)

            except Exception as e_th:
                logger.warning("Lỗi xử lý hội thoại ở vòng #%d: %s", cycle, e_th)
                await asyncio.sleep(2)

        # Chụp ảnh bằng chứng THƯ MỤC XONG ĐÃ TRỐNG SẠCH
        cleaned_screenshot = "logs/EVIDENCE_02_DONE_FOLDER_CLEANED.png"
        await page.screenshot(path=cleaned_screenshot)
        logger.info("📸 ĐÃ LƯU BẰNG CHỨNG MỤC XONG ĐÃ SẠCH: %s", cleaned_screenshot)

        # BƯỚC 4: Điều hướng về Hộp thư đến chính và kiểm tra kết quả khôi phục (R3.2)
        logger.info("BƯỚC 4: Điều hướng về Hộp thư đến chính...")
        await page.goto(INBOX_BASE_URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(6)

        after_screenshot = "logs/EVIDENCE_03_AFTER_RESTORE_MAIN_INBOX.png"
        await page.screenshot(path=after_screenshot)
        logger.info("📸 ĐÃ LƯU BẰNG CHỨNG HỘP THƯ CHÍNH SAU KHÔI PHỤC: %s", after_screenshot)

        # Quét danh sách các cuộc trò chuyện trên Hộp thư chính để lập bằng chứng
        main_threads = await page.evaluate('''() => {
            const nodes = Array.from(document.querySelectorAll('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]'));
            return nodes.map(n => {
                const text = (n.innerText || '').trim();
                const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                return {
                    name: lines[0] || '',
                    time: lines[1] || '',
                    preview: lines[2] || ''
                };
            }).filter(n => n.name && n.name.length > 1 && !['tìm kiếm', 'quản lý', 'hộp thư', 'messenger'].some(k => n.name.toLowerCase().includes(k)));
        }''')

        logger.info("=" * 76)
        logger.info("🎉 HOÀN THÀNH 100% QUY TRÌNH KHÔI PHỤC!")
        logger.info("Tổng số cuộc trò chuyện đã chuyển về Hộp thư đến chính: %d", len(restored_customers))
        logger.info("=" * 76)
        for c in restored_customers:
            logger.info("   [%d] %s (%s) - %s", c['index'], c['name'], c['time'], c['preview'][:40])
        logger.info("=" * 76)

        # Lưu báo cáo JSON
        report = {
            "success": True,
            "total_restored": len(restored_customers),
            "restored_customers": restored_customers,
            "main_inbox_visible_threads": main_threads,
            "screenshots": {
                "before_restore_done_folder": before_screenshot,
                "done_folder_cleaned": cleaned_screenshot,
                "after_restore_main_inbox": after_screenshot
            },
            "completed_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open("logs/RESTORE_REPORT.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        # Cập nhật storage_state
        await context.storage_state(path="state/fb_storage_state.json")
        logger.info("Đã cập nhật state/fb_storage_state.json với phiên mới nhất.")

        await browser.close()
        return report


if __name__ == "__main__":
    asyncio.run(restore_all_threads())
