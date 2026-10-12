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

async def open_xong_folder(page):
    target_url = "https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512"
    print(f"Navigating to {target_url}...")
    await page.goto(target_url, wait_until="domcontentloaded")
    await asyncio.sleep(5)
    
    # Check if filter icon already has '1' (Xong applied)
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
    print("Xong folder opened. Current URL:", page.url)

async def scan_all_xong_threads(page):
    seen_names = set()
    threads_data = []
    
    # Find the scrollable container for the conversation list
    # Usually it's the list container on the left (x < 400)
    list_container = page.locator('[role="navigation"], [role="grid"], div._a6ag').first
    
    for round_idx in range(15):
        # Read current visible threads
        current_threads = await page.evaluate('''() => {
            const nodes = Array.from(document.querySelectorAll('div[role="presentation"].x1ypdohk, div._a6ag._a6ah, [role="listitem"]'));
            return nodes.map(n => {
                const text = (n.innerText || '').trim();
                const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                const name = lines[0] || '';
                const time = lines[1] || '';
                const preview = lines[2] || '';
                const rect = n.getBoundingClientRect();
                return { name, time, preview, fullText: text.replace(/\\n+/g, ' | '), rect: {y: rect.y, h: rect.height} };
            }).filter(n => n.name && n.name.length > 1 && n.rect.y > 150 && n.rect.h > 30);
        }''')
        
        added_new = 0
        for t in current_threads:
            if t['name'] not in seen_names and not any(k in t['name'].lower() for k in ['tìm kiếm', 'quản lý', 'hộp thư', 'messenger', 'chưa đọc', 'ưu tiên']):
                seen_names.add(t['name'])
                threads_data.append(t)
                added_new += 1
                
        print(f"Round {round_idx}: Total unique customers in Xong folder: {len(seen_names)} (new this round: {added_new})")
        
        # Scroll the conversation list down
        scroll_res = await page.evaluate('''() => {
            // Find the list container
            const containers = Array.from(document.querySelectorAll('div[style*="overflow"], div[class*="scroll"], div[role="navigation"], div[role="grid"]'))
                .filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.x >= 50 && r.x <= 360 && r.height > 300;
                });
            let scrolled = false;
            for (const c of containers) {
                if (c.scrollHeight > c.clientHeight) {
                    c.scrollTop += 600;
                    scrolled = true;
                }
            }
            if (!scrolled) {
                window.scrollBy(0, 600);
            }
            return scrolled;
        }''')
        await asyncio.sleep(2.5)
        if added_new == 0 and round_idx >= 3:
            # Reached end
            print("No more new conversations found after scrolling.")
            break
            
    return threads_data

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        page = await ctx.new_page()
        await open_xong_folder(page)
        
        # Take BEFORE screenshot of full page
        await page.screenshot(path="logs/EVIDENCE_01_BEFORE_DONE_FOLDER.png")
        print("Saved logs/EVIDENCE_01_BEFORE_DONE_FOLDER.png")
        
        threads = await scan_all_xong_threads(page)
        print(f"\n===== TỔNG KẾT DANH SÁCH KHÁCH HÀNG TRONG MỤC XONG ({len(threads)}) =====")
        for idx, t in enumerate(threads):
            print(f"{idx+1}. {t['name']} ({t['time']}) - {t['preview'][:60]}")
            
        with open("logs/xong_threads_scanned.json", "w", encoding="utf-8") as f:
            json.dump(threads, f, ensure_ascii=False, indent=2)
            
        await b.close()

if __name__ == "__main__":
    asyncio.run(main())
