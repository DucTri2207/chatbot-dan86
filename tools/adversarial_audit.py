import asyncio
import json
import os
import sys

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
        return text.includes('Không có kết quả nào khớp với bộ lọc') || text.includes('Không có tin nhắn') || text.includes('Không có cuộc trò chuyện');
    }''')

async def main():
    os.makedirs("logs/audit", exist_ok=True)
    scanned_file = "logs/xong_threads_scanned.json"
    target_names = []
    if os.path.exists(scanned_file):
        with open(scanned_file, "r", encoding="utf-8") as f:
            target_data = json.load(f)
            target_names = [x["name"] for x in target_data]
    print(f"[AUDIT] Total target customer names from original scan: {len(target_names)}")

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

        # TEST 1: Direct navigation to Messenger DONE URL
        print("\n=== TEST 1: Direct navigation to Messenger DONE URL ===")
        url_messenger_done = f"https://business.facebook.com/latest/inbox/messenger?asset_id={PAGE_ASSET_ID}&mailbox_folder=DONE"
        print(f"Navigating to {url_messenger_done}...")
        await page.goto(url_messenger_done, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(6)
        await page.screenshot(path="logs/audit/01_direct_messenger_done_url.png")
        t1_threads = await extract_threads(page)
        t1_empty = await check_empty_state(page)
        print(f"URL current: {page.url}")
        print(f"Empty state text found: {t1_empty}")
        print(f"Extracted threads count: {len(t1_threads)}")
        if t1_threads:
            print(f"First 3 threads: {[t['name'] for t in t1_threads[:3]]}")

        # Check if filter chip 'Xong' is active or can be opened
        print("Checking filter chip in Messenger...")
        filter_btn = page.locator('[aria-label="Bộ lọc"]').first
        if await filter_btn.count() > 0:
            await filter_btn.click()
            await asyncio.sleep(2)
            await page.screenshot(path="logs/audit/01b_messenger_filter_popup.png")
            # Check what's in filter popup
            filter_text = await page.evaluate('''() => {
                const pop = document.querySelector('[role="dialog"]') || document.body;
                return pop.innerText;
            }''')
            print(f"Filter popup text snippet: {filter_text[:200].replace(chr(10), ' | ')}")
            # Apply Xong explicitly if not applied
            xong_chip = page.locator('div:text-is("Xong"), span:text-is("Xong")').last
            if await xong_chip.count() > 0:
                await xong_chip.click()
                await asyncio.sleep(1)
            apply_btn = page.locator('button:has-text("Áp dụng"), div[role="button"]:has-text("Áp dụng")').first
            if await apply_btn.count() > 0:
                await apply_btn.click()
                await asyncio.sleep(4)
        await page.screenshot(path="logs/audit/01c_messenger_xong_applied.png")
        t1_xong_threads = await extract_threads(page)
        t1_xong_empty = await check_empty_state(page)
        print(f"Messenger with Xong filter - Threads: {len(t1_xong_threads)}, Empty text: {t1_xong_empty}")

        # TEST 2: Direct navigation to All DONE URL
        print("\n=== TEST 2: Direct navigation to All DONE URL ===")
        url_all_done = f"https://business.facebook.com/latest/inbox/all?asset_id={PAGE_ASSET_ID}&mailbox_folder=DONE"
        print(f"Navigating to {url_all_done}...")
        await page.goto(url_all_done, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(6)
        await page.screenshot(path="logs/audit/02_direct_all_done_url.png")
        t2_threads = await extract_threads(page)
        t2_empty = await check_empty_state(page)
        print(f"URL current: {page.url}")
        print(f"Empty state text found: {t2_empty}")
        print(f"Extracted threads count: {len(t2_threads)}")

        # Now apply Xong filter in ALL tab
        print("Checking filter chip in ALL tab...")
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
        await page.screenshot(path="logs/audit/02b_all_xong_applied.png")
        t2_xong_threads = await extract_threads(page)
        t2_xong_empty = await check_empty_state(page)
        print(f"ALL tab with Xong filter - Threads: {len(t2_xong_threads)}, Empty text: {t2_xong_empty}")

        # TEST 3: Check Main Inbox (Messenger) and scroll to count restored threads
        print("\n=== TEST 3: Deep scroll verification in Main Inbox ===")
        url_inbox = f"https://business.facebook.com/latest/inbox/messenger?asset_id={PAGE_ASSET_ID}"
        print(f"Navigating to Main Inbox: {url_inbox}...")
        await page.goto(url_inbox, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(6)

        # Ensure no filters are applied
        clear_filter = page.locator('button:has-text("Xóa bộ lọc"), div[role="button"]:has-text("Xóa bộ lọc")').first
        if await clear_filter.count() > 0 and await clear_filter.is_visible():
            await clear_filter.click()
            await asyncio.sleep(3)

        seen_in_main = set()
        matched_targets = set()
        for scroll_round in range(25):
            curr_threads = await extract_threads(page)
            new_this_round = 0
            for t in curr_threads:
                if t['name'] not in seen_in_main:
                    seen_in_main.add(t['name'])
                    new_this_round += 1
                    if t['name'] in target_names:
                        matched_targets.add(t['name'])

            print(f"Scroll #{scroll_round + 1}: Total seen in Main: {len(seen_in_main)}, Restored targets matched: {len(matched_targets)}/{len(target_names)}")

            # Scroll list down
            scrolled = await page.evaluate('''() => {
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
            await asyncio.sleep(2)
            if new_this_round == 0 and scroll_round >= 8:
                print("End of list reached or no new items loading.")
                break

        await page.screenshot(path="logs/audit/03_deep_scroll_main_inbox.png")

        # Summary of audit
        audit_summary = {
            "test_1_messenger_done_url_threads": len(t1_threads),
            "test_1_messenger_xong_filter_threads": len(t1_xong_threads),
            "test_1_messenger_xong_empty_state": t1_xong_empty,
            "test_2_all_done_url_threads": len(t2_threads),
            "test_2_all_xong_filter_threads": len(t2_xong_threads),
            "test_2_all_xong_empty_state": t2_xong_empty,
            "test_3_main_inbox_total_seen": len(seen_in_main),
            "test_3_matched_targets_count": len(matched_targets),
            "test_3_target_total": len(target_names),
            "test_3_matched_percentage": f"{len(matched_targets)/len(target_names)*100:.1f}%" if target_names else "0%",
            "matched_targets_list": list(matched_targets),
            "unmatched_targets_list": list(set(target_names) - matched_targets),
        }
        with open("logs/audit/audit_summary.json", "w", encoding="utf-8") as f:
            json.dump(audit_summary, f, ensure_ascii=False, indent=2)
        print("\n=== AUDIT SUMMARY ===")
        print(json.dumps(audit_summary, ensure_ascii=False, indent=2))

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
