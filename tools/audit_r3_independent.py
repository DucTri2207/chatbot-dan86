import asyncio
import json
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

PAGE_ASSET_ID = "104011958817512"

async def extract_threads(page):
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

async def check_empty_state(page):
    return await page.evaluate('''() => {
        const text = document.body.innerText || '';
        return text.includes('Không có kết quả nào khớp với bộ lọc') || 
               text.includes('Không có tin nhắn') || 
               text.includes('Không có cuộc trò chuyện');
    }''')

async def apply_xong_filter(page):
    filter_btn = page.locator('[aria-label="Bộ lọc"]').first
    if await filter_btn.count() == 0:
        return False
    await filter_btn.click()
    await asyncio.sleep(2)
    
    # Scroll dialog
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
    count_xong = await xong_elem.count()
    if count_xong > 0:
        await xong_elem.click()
        await asyncio.sleep(1)
    
    apply_btn = page.locator('[role="dialog"]').locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first
    if await apply_btn.count() > 0:
        await apply_btn.click()
        await asyncio.sleep(4)
        return True
    return False

async def main():
    os.makedirs("logs/audit", exist_ok=True)
    report = {}

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

        # Step 1: Check Messenger DONE url directly
        url_msgr_done = f"https://business.facebook.com/latest/inbox/messenger?asset_id={PAGE_ASSET_ID}&mailbox_folder=DONE"
        print(f"[R3 AUDIT] Step 1: Navigating to {url_msgr_done}")
        await page.goto(url_msgr_done, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        await page.screenshot(path="logs/audit/r3_01_direct_messenger_done.png")
        
        # Now apply Xong filter to test specifically
        print("[R3 AUDIT] Applying Xong filter on Messenger...")
        await apply_xong_filter(page)
        await page.screenshot(path="logs/audit/r3_02_messenger_xong_filter.png")
        msgr_threads = await extract_threads(page)
        msgr_empty = await check_empty_state(page)
        print(f"[R3 AUDIT] Messenger Xong - Threads count: {len(msgr_threads)}, Empty text present: {msgr_empty}")
        report["messenger_xong_threads_count"] = len(msgr_threads)
        report["messenger_xong_empty_state"] = msgr_empty

        # Step 2: Check All inbox DONE url directly
        url_all_done = f"https://business.facebook.com/latest/inbox/all?asset_id={PAGE_ASSET_ID}&mailbox_folder=DONE"
        print(f"\n[R3 AUDIT] Step 2: Navigating to {url_all_done}")
        await page.goto(url_all_done, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        await page.screenshot(path="logs/audit/r3_03_direct_all_done.png")
        
        # Apply Xong filter on All inbox
        print("[R3 AUDIT] Applying Xong filter on All inbox...")
        await apply_xong_filter(page)
        await page.screenshot(path="logs/audit/r3_04_all_xong_filter.png")
        all_threads = await extract_threads(page)
        all_empty = await check_empty_state(page)
        print(f"[R3 AUDIT] All inbox Xong - Threads count: {len(all_threads)}, Empty text present: {all_empty}")
        report["all_xong_threads_count"] = len(all_threads)
        report["all_xong_empty_state"] = all_empty

        # Step 3: Check Main Inbox
        url_main = f"https://business.facebook.com/latest/inbox/messenger?asset_id={PAGE_ASSET_ID}"
        print(f"\n[R3 AUDIT] Step 3: Navigating to Main Inbox {url_main}")
        await page.goto(url_main, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        
        # Clear filter if active
        clear_btn = page.locator('button:has-text("Xóa bộ lọc"), div[role="button"]:has-text("Xóa bộ lọc")').first
        if await clear_btn.count() > 0 and await clear_btn.is_visible():
            print("Clearing filter on main inbox...")
            await clear_btn.click()
            await asyncio.sleep(3)

        # Deep scroll and collect threads
        seen_threads = {}
        for s in range(20):
            batch = await extract_threads(page)
            new_found = 0
            for t in batch:
                if t['name'] not in seen_threads:
                    seen_threads[t['name']] = t
                    new_found += 1
            # Scroll thread list
            await page.evaluate('''() => {
                const containers = Array.from(document.querySelectorAll('div[style*="overflow"], div[class*="scroll"], div[role="navigation"], div[role="grid"]'))
                    .filter(el => {
                        const r = el.getBoundingClientRect();
                        return r.x >= 50 && r.x <= 380 && r.height > 300;
                    });
                for (const c of containers) {
                    if (c.scrollHeight > c.clientHeight) {
                        c.scrollTop += 800;
                        return true;
                    }
                }
                window.scrollBy(0, 800);
                return false;
            }''')
            await asyncio.sleep(1.5)
            if new_found == 0 and s > 8:
                break
        
        await page.screenshot(path="logs/audit/r3_05_main_inbox_deep_scroll.png")
        print(f"[R3 AUDIT] Total conversations collected from Main Inbox: {len(seen_threads)}")
        report["main_inbox_total_scanned"] = len(seen_threads)
        
        # Check date range in main inbox threads
        sample_times = [t['time'] for t in seen_threads.values() if t['time']]
        print(f"[R3 AUDIT] Sample times from main inbox: {sample_times[:15]}")
        report["main_inbox_sample_times"] = sample_times[:20]

        # Step 4: Check Facebook Comments tab
        url_comments = f"https://business.facebook.com/latest/inbox/fb_comments?asset_id={PAGE_ASSET_ID}"
        print(f"\n[R3 AUDIT] Step 4: Navigating to FB comments {url_comments}")
        await page.goto(url_comments, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        await page.screenshot(path="logs/audit/r3_06_fb_comments.png")
        comments_text = await page.evaluate('''() => document.body.innerText || '' ''')
        filter_buttons = await page.locator('[aria-label="Bộ lọc"]').count()
        print(f"[R3 AUDIT] FB comments filter buttons count: {filter_buttons}")
        report["fb_comments_filter_buttons_count"] = filter_buttons

        with open("logs/audit/r3_audit_results.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print("\n[R3 AUDIT] Audit results written to logs/audit/r3_audit_results.json")
        print(json.dumps(report, ensure_ascii=False, indent=2))

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
