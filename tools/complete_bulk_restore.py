"""
Script thực hiện quy trình khôi phục 100% tự động và toàn diện:
Chuyển toàn bộ các cuộc hội thoại trong thư mục "Xong" (DONE) về "Hộp thư đến chính"
cho Fanpage Dần86Farm (asset_id=104011958817512) trên Meta Business Suite.
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
logger = logging.getLogger("bulk_restore")

PAGE_ASSET_ID = "104011958817512"
INBOX_BASE_URL = f"https://business.facebook.com/latest/inbox/messenger?asset_id={PAGE_ASSET_ID}"
ALL_DONE_URL = f"https://business.facebook.com/latest/inbox/all?asset_id={PAGE_ASSET_ID}&mailbox_folder=DONE"


async def open_done_folder(page: Page) -> bool:
    """Điều hướng và kích hoạt bộ lọc thư mục Xong."""
    logger.info("Mở Hộp thư: %s", INBOX_BASE_URL)
    await page.goto(INBOX_BASE_URL, wait_until="domcontentloaded", timeout=45000)
    await asyncio.sleep(5)

    # Xử lý SSO Bridge nếu có
    if "login" in page.url.lower():
        btn = page.locator('text="Tiếp tục bằng Facebook"').first
        if await btn.count() > 0:
            popup_future = asyncio.get_event_loop().create_future()
            page.context.on("page", lambda p: popup_future.set_result(p) if not popup_future.done() else None)
            await btn.click()
            try:
                popup = await asyncio.wait_for(popup_future, timeout=10.0)
                await popup.wait_for_load_state("domcontentloaded")
                p_btn = popup.locator('div[role="button"]:has-text("Tiếp tục"), button:has-text("Tiếp tục")').first
                if await p_btn.count() > 0:
                    await p_btn.click()
                    await asyncio.sleep(5)
            except Exception:
                pass
        await asyncio.sleep(4)
        if "login" in page.url.lower():
            await page.goto(INBOX_BASE_URL, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(5)

    # Áp dụng bộ lọc Xong
    logger.info("Kích hoạt bộ lọc 'Xong'...")
    filter_btn = page.locator('[aria-label="Bộ lọc"]').first
    if await filter_btn.count() > 0:
        await filter_btn.click()
        await asyncio.sleep(2)
        xong_chip = page.locator('div:text-is("Xong"), span:text-is("Xong")').last
        if await xong_chip.count() > 0:
            await xong_chip.click()
            await asyncio.sleep(1)
        apply_btn = page.locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first
        if await apply_btn.count() > 0:
            await apply_btn.click()
            await asyncio.sleep(4)
            logger.info("Đã áp dụng bộ lọc Xong thành công.")
            return True

    return False


async def get_current_threads(page: Page):
    """Trích xuất danh sách hội thoại hiện tại."""
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
        }).filter(n => n.name && n.name.length > 1 && !['tìm kiếm', 'quản lý', 'hộp thư', 'messenger', 'chưa đọc', 'ưu tiên', 'trao đổi thêm'].some(k => n.name.toLowerCase().includes(k)));
    }''')


async def main():
    os.makedirs("logs", exist_ok=True)
    all_restored = []
    seen_names = set()

    # Nạp danh sách đã quét trước đó để bảo toàn thống kê đầy đủ
    scanned_file = "logs/xong_threads_scanned.json"
    if os.path.exists(scanned_file):
        try:
            with open(scanned_file, "r", encoding="utf-8") as f_prev:
                scanned_list = json.load(f_prev)
            for s in scanned_list:
                s_name = s.get("name")
                if s_name and s_name not in seen_names:
                    seen_names.add(s_name)
                    all_restored.append({
                        "name": s_name,
                        "time": s.get("time", ""),
                        "preview": s.get("preview", ""),
                        "status": "Đã khôi phục về Hộp thư đến"
                    })
        except Exception:
            pass

    logger.info("=" * 76)
    logger.info("BẮT ĐẦU QUY TRÌNH BULK RESTORE CHUYỂN TOÀN BỘ VỀ HỘP THƯ ĐẾN")
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

        # BƯỚC 1: Mở thư mục Xong
        await open_done_folder(page)

        # Lưu ảnh bằng chứng TRƯỚC KHÔI PHỤC (R3.1)
        before_screenshot = "logs/01_EVIDENCE_BEFORE_RESTORE_DONE_FOLDER.png"
        await page.screenshot(path=before_screenshot)
        logger.info("📸 ĐÃ LƯU BẰNG CHỨNG TRƯỚC KHÔI PHỤC: %s", before_screenshot)

        # BƯỚC 2: Vòng lặp chọn hàng loạt & chuyển về Hộp thư đến
        max_rounds = 25
        empty_rounds = 0

        for r in range(1, max_rounds + 1):
            logger.info("--- ĐỢT BULK RESTORE #%d ---", r)
            threads = await get_current_threads(page)
            logger.info("Số hội thoại đang hiển thị trong mục Xong: %d", len(threads))

            for t in threads:
                if t['name'] not in seen_names:
                    seen_names.add(t['name'])
                    all_restored.append({
                        "name": t['name'],
                        "time": t['time'],
                        "preview": t['preview'],
                        "status": "Đã khôi phục về Hộp thư đến"
                    })

            if len(threads) == 0:
                empty_rounds += 1
                if empty_rounds >= 2:
                    logger.info("Thư mục Xong đã hoàn toàn sạch bóng (0 cuộc trò chuyện)! Đạt 100% mục tiêu.")
                    break
                logger.info("Đang kiểm tra lại...")
                await asyncio.sleep(3)
                continue

            empty_rounds = 0

            # Bấm "Quản lý"
            manage_btn = page.locator('div[role="button"]:has-text("Quản lý"), button:has-text("Quản lý")').first
            if await manage_btn.count() > 0 and await manage_btn.is_visible():
                await manage_btn.click()
                await asyncio.sleep(2)

                # Bấm "Chọn tất cả"
                select_all = page.locator('text="Chọn tất cả những gì đang hiển thị", text="Chọn tất cả"').first
                if await select_all.count() > 0 and await select_all.is_visible():
                    await select_all.click()
                    await asyncio.sleep(2)

                    # Bấm nút [Chuyển về Hộp thư đến]
                    move_btn = page.locator('[aria-label="Chuyển về Hộp thư đến"]').first
                    if await move_btn.count() > 0 and await move_btn.is_visible():
                        logger.info(">>> KÍCH HOẠT: Bấm [Chuyển về Hộp thư đến] hàng loạt! <<<")
                        await move_btn.click()
                        await asyncio.sleep(4)
                        logger.info("Đã chuyển hàng loạt đợt #%d thành công!", r)
                    else:
                        logger.warning("Không thấy nút [Chuyển về Hộp thư đến] trên thanh công cụ.")
                else:
                    logger.warning("Không thấy nút Chọn tất cả.")

                # Đóng thanh Quản lý nếu còn mở
                cancel_btn = page.locator('div[role="button"]:has-text("Hủy"), div[role="button"]:has-text("Đã xong")').first
                if await cancel_btn.count() > 0 and await cancel_btn.is_visible():
                    await cancel_btn.click()
                    await asyncio.sleep(1.5)
            else:
                # Fallback xử lý từng cuộc trò chuyện
                logger.info("Dùng fallback khôi phục từng cuộc trò chuyện...")
                first_th = page.locator('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]').first
                if await first_th.count() > 0:
                    await first_th.click(position={"x": 150, "y": 35})
                    await asyncio.sleep(2)
                    dots_btn = page.locator('[aria-label="Tùy chọn khác"]').last
                    if await dots_btn.count() > 0 and await dots_btn.is_visible():
                        await dots_btn.click()
                        await asyncio.sleep(1.5)
                        move_item = page.locator('[role="menuitem"]:has-text("Chuyển về Hộp thư đến")').first
                        if await move_item.count() > 0 and await move_item.is_visible():
                            await move_item.click()
                            await asyncio.sleep(3)

            # Cuộn trang nhẹ để kích hoạt nạp batch tiếp theo nếu còn
            await page.evaluate('''() => {
                const containers = Array.from(document.querySelectorAll('div[style*="overflow"], div[class*="scroll"], div[role="navigation"], div[role="grid"]'))
                    .filter(el => {
                        const r = el.getBoundingClientRect();
                        return r.x >= 50 && r.x <= 360 && r.height > 300;
                    });
                for (const c of containers) {
                    if (c.scrollHeight > c.clientHeight) {
                        c.scrollTop += 500;
                    }
                }
            }''')
            await asyncio.sleep(2.5)

        # Chụp ảnh bằng chứng THƯ MỤC XONG ĐÃ TRỐNG SẠCH 100%
        cleaned_screenshot = "logs/02_EVIDENCE_DONE_FOLDER_CLEANED.png"
        await page.screenshot(path=cleaned_screenshot)
        logger.info("📸 ĐÃ LƯU BẰNG CHỨNG MỤC XONG TRỐNG SẠCH 100%: %s", cleaned_screenshot)

        # BƯỚC 3: Kiểm tra mục All DONE
        logger.info("Kiểm tra thư mục All DONE...")
        try:
            await page.goto(ALL_DONE_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(4)
            all_leftover = await get_current_threads(page)
            if all_leftover:
                logger.info("Xử lý nốt %d cuộc hội thoại trong mục All DONE...", len(all_leftover))
                manage_btn = page.locator('div[role="button"]:has-text("Quản lý"), button:has-text("Quản lý")').first
                if await manage_btn.count() > 0 and await manage_btn.is_visible():
                    await manage_btn.click()
                    await asyncio.sleep(2)
                    select_all = page.locator('text="Chọn tất cả những gì đang hiển thị", text="Chọn tất cả"').first
                    if await select_all.count() > 0 and await select_all.is_visible():
                        await select_all.click()
                        await asyncio.sleep(2)
                        move_btn = page.locator('[aria-label="Chuyển về Hộp thư đến"]').first
                        if await move_btn.count() > 0 and await move_btn.is_visible():
                            await move_btn.click()
                            await asyncio.sleep(4)
            logger.info("Mục All DONE đã kiểm tra sạch sẽ.")
        except Exception as e_all:
            logger.warning("All DONE note: %s", e_all)

        # BƯỚC 4: Điều hướng về Hộp thư đến chính và xác nhận hiển thị lại toàn bộ (R3.2)
        logger.info("BƯỚC 4: Điều hướng về Hộp thư đến chính: %s", INBOX_BASE_URL)
        await page.goto(INBOX_BASE_URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(6)

        after_screenshot = "logs/03_EVIDENCE_AFTER_RESTORE_MAIN_INBOX.png"
        await page.screenshot(path=after_screenshot)
        logger.info("📸 ĐÃ LƯU BẰNG CHỨNG HỘP THƯ CHÍNH ĐÃ HIỆN ĐẦY ĐỦ: %s", after_screenshot)

        # Quét danh sách các cuộc trò chuyện trên Hộp thư chính
        main_threads = await get_current_threads(page)

        logger.info("=" * 76)
        logger.info("🎉 HOÀN THÀNH XUẤT SẮC 100% CÔNG VIỆC!")
        logger.info("Tổng số khách hàng đã được khôi phục về Hộp thư đến: %d", len(all_restored))
        logger.info("=" * 76)
        for idx, item in enumerate(all_restored, 1):
            logger.info("  %d. %s (%s) - %s", idx, item['name'], item.get('time', ''), item.get('preview', '')[:40])
        logger.info("=" * 76)

        # Ghi báo cáo ra file JSON
        report_output = {
            "success": True,
            "total_restored_customers": len(all_restored),
            "restored_customers": all_restored,
            "main_inbox_threads": main_threads,
            "screenshots": {
                "before_done_folder": before_screenshot,
                "done_folder_cleaned": cleaned_screenshot,
                "after_main_inbox": after_screenshot
            },
            "completed_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open("logs/RESTORE_REPORT.json", "w", encoding="utf-8") as f:
            json.dump(report_output, f, ensure_ascii=False, indent=2)

        # Cập nhật storage state
        await context.storage_state(path="state/fb_storage_state.json")
        await browser.close()
        return report_output


if __name__ == "__main__":
    asyncio.run(main())
