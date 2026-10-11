import asyncio
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.async_api import async_playwright

async def inspect_comment_node():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="state/fb_storage_state.json",
            viewport={"width": 1440, "height": 900},
            locale="vi-VN"
        )
        page = await context.new_page()
        await page.goto("https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512", wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        
        data = await page.evaluate('''() => {
            // Tìm tất cả các khối bình luận ở vùng bên phải (x > 500)
            // Lấy tất cả elements chứa nút "Trả lời"
            const replyBtns = Array.from(document.querySelectorAll('*')).filter(el => {
                return (el.innerText || '').trim() === 'Trả lời' && el.children.length === 0;
            });

            const comments = [];
            for (const rbtn of replyBtns) {
                // Đi lên các parent để tìm container của bình luận này
                let cur = rbtn;
                let commentBox = null;
                for (let step = 0; step < 10; step++) {
                    if (!cur.parentElement) break;
                    cur = cur.parentElement;
                    // Nếu cur chứa tên tác giả hoặc có border/background
                    const t = cur.innerText || '';
                    if (t.includes('Lệ Thuyền') || t.includes('Dần86Farm') || t.includes('Trí Đức') || t.includes('Chỉ báo trạng thái online')) {
                        commentBox = cur;
                    }
                }

                if (commentBox) {
                    comments.push({
                        replyBtnRect: rbtn.getBoundingClientRect(),
                        replyBtnTag: rbtn.tagName,
                        replyBtnParent: rbtn.parentElement ? rbtn.parentElement.outerHTML.slice(0, 200) : '',
                        commentBoxTag: commentBox.tagName,
                        commentBoxRect: commentBox.getBoundingClientRect(),
                        commentBoxText: commentBox.innerText,
                        allStrings: commentBox.innerText.split('\\n').map(s => s.trim()).filter(Boolean),
                        commentBoxHtmlSnippet: commentBox.outerHTML.slice(0, 500)
                    });
                }
            }
            return comments;
        }''')
        
        print(f"Comments found around 'Trả lời' buttons: {len(data)}")
        for i, c in enumerate(data):
            print(f"--- Comment #{i} ---")
            print("ReplyBtn Rect:", c["replyBtnRect"])
            print("Strings in box:", c["allStrings"][:8])
            print("Snippet:", c["commentBoxHtmlSnippet"][:200])
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_comment_node())
