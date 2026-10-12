# Handoff Report: R2 & R3 Investigation

**Agent**: Explorer 1 (`teamwork_preview_explorer`)  
**Type**: Hard Handoff (Investigation & Analysis Complete)  
**Date**: 2026-10-12  
**Target Files Analyzed**:
- `d:\chat bot dan 86\2_chay_bot_truc_page.py`
- `d:\chat bot dan 86\bot\page_bot_engine.py`
- `d:\chat bot dan 86\bot\memory_store.py`
- `d:\chat bot dan 86\bot\bot_config.py`
- `d:\chat bot dan 86\state\bot_status.json`
- `d:\chat bot dan 86\test_bot_logic.py`

---

## 1. Observation

1. **Pointer-Event Interception Log**:
   - Exact log quote from `d:\chat bot dan 86\state\bot_status.json` (lines 19-25):
     ```
     56 × waiting for element to be visible, enabled and stable
        - element is visible, enabled and stable
        - scrolling into view if needed
        - done scrolling
        - <span class="x1lliihq x6ikm8r x10wlt62 x1n2onr6 x1j85h84">Đức Trí</span> from <span data-surface-wrapper="1" data-surface="/bizweb:inbox/bizweb:INBOX/lib:bizweb_inbox:main_content/lib:bizweb_inbox:content_layout/lib:inbox:thread_and_detail/lib:inbox:detail_column">…</span> subtree intercepts pointer events
      - retrying click action
        - waiting 500ms
     ```
   - Vulnerable click locations without `force=True`, without `scroll_into_view_if_needed`, or without timeout:
     - `bot/page_bot_engine.py:192`: `await locator.click()` in `type_human_like`
     - `bot/page_bot_engine.py:1011`: `await marked_msg_btn.click()` in `send_private_inbox_to_commenter` (no timeout, no force)
     - `bot/page_bot_engine.py:1093`: `await send_btn.click()` (no timeout, no force)
     - `bot/page_bot_engine.py:1371`: `await like_btn.click(timeout=2000)` (no force)
     - `bot/page_bot_engine.py:1381`: `await marked_reply_btn.click(timeout=2500)` (no force)
     - `bot/page_bot_engine.py:1397`: `await reply_btn.click(timeout=2500)` (no force)
     - `bot/page_bot_engine.py:1662`: `await item.click(timeout=4000)` fallback clicks center of thread row without coordinates or force.

2. **Missed Inbox for Comments with Existing Reply**:
   - In `bot/page_bot_engine.py:1288-1297`:
     ```python
     if cand_has_reply and comment_key:
         existing_rec = memory.data["replied_comments"].get(comment_key)
         if not existing_rec:
             target_candidate = cand
             target_key = comment_key
             needs_inbox_only = True
             break
     ```
     If `existing_rec` already exists in `memory` with `private_inbox_sent == False` (e.g. from an earlier cycle where private inbox failed or timed out), `if not existing_rec:` evaluates to `False`, so `needs_inbox_only` is never triggered.
   - In `bot/page_bot_engine.py:692-700` (`inspect_comment_panel` JS scraper):
     ```javascript
     const unrepliedList = parsedComments.filter(c => {
         if (c.isPageReply || c.isOldComment) return false;
         if (!c.hasPageReply) return true;
         const mText = (c.msgBtnText || '').toLowerCase();
         const tStr = (c.timeStr || '').toLowerCase();
         const stillNeedsMsgBtn = mText.includes('gửi tin nhắn') || mText.includes('nhắn tin') || mText.includes('send message');
         const isVeryRecent = /(?:vừa xong|just now|\b\d+\s*(?:giây|phút|giờ|s|m|h|mins?|hours?)\b)/i.test(tStr);
         return stillNeedsMsgBtn || isVeryRecent;
     });
     ```
     Comments aged `hôm qua` or `1-3 ngày` with `hasPageReply == true` and button "See Chat" are prematurely dropped by `unrepliedList`.

3. **Comment Text Parsing Flaws**:
   - In `bot/page_bot_engine.py:633`:
     `if (l === authorName || low.includes('tuần') || low.includes('ngày') || low.includes('phút') || low.includes('giờ') || l === '·') return false;`
     Natural Vietnamese comments containing words like "ngày" (*"mấy ngày có hàng?"*) or "giờ" (*"mấy giờ shop đóng cửa?"*) get stripped of their question, resulting in `.` as comment text.
   - In `bot/page_bot_engine.py:344` (`clean_comment_text`), `giây` and `s` are omitted from the regex.
   - In `bot/page_bot_engine.py:370` (`is_old_comment_timestamp`), `w` and `y` are omitted from the regex.

4. **Messenger Conversation Inspection Boundary**:
   - In `bot/page_bot_engine.py:1554`:
     `r.left > 380 && r.right < 1120 && r.top > 120 && r.bottom < 840 && r.height >= 16`
     On a standard 900px viewport, message bubbles near the bottom composer sit at y=840..870. The hard limit `r.bottom < 840` drops the newest message.

5. **Post Status Modification Verification**:
   - Grep for "đã xong", "done", "ẩn", "hide" across `bot/` confirms zero code deletes, hides, or marks posts as Done. List clicks specifically use `x=150, y=40`.

---

## 2. Logic Chain

1. From Observation 1, Playwright's click actionability algorithm calculates element centers and verifies that pointer hit-testing hits the target element. Because Meta Business Suite features a high z-index right panel (`detail_column`), scrolling elements into view often positions their center under `detail_column`. Without `force=True` and synthetic event fallback, clicks hang for 30s and abort cycles.
2. From Observation 2, R2 item 4 mandates: *"Whether or not the comment already had a public reply underneath it, if a private message has not yet been sent for that specific comment record in state/bot_memory.json, immediately send 1 direct private message"*. Checking only `if not existing_rec:` breaks this whenever a record exists with `private_inbox_sent: False`. Therefore, condition must be `if not existing_rec or not existing_rec.get("private_inbox_sent"):`, and JS scraper must retain all valid non-old comments.
3. From Observation 3, substring-matching Vietnamese temporal words removes valid customer queries. Replacing substring match with regex matching on dedicated timestamp lines (`/^\s*\d+\s*(?:giây|phút|giờ|ngày).../`) preserves query text.
4. From Observation 4, expanding `r.bottom < 885` while excluding `!el.closest('[role="textbox"]')` ensures the latest incoming message is never truncated.

---

## 3. Caveats

- Live Facebook layout elements may evolve over time; maintaining both class-based selectors and ARIA attributes ensures forward-compatibility.
- No direct edits to source files were made during this investigation step, in compliance with the read-only exploration role.

---

## 4. Conclusion

The codebase already has solid foundations for anti-repeat templates and state persistence, but requires 4 targeted hardening fixes:
1. Introduce `safe_click` helper with `force=True`, `scroll_into_view_if_needed`, and DOM `dispatchEvent` / `click()` fallback across all Playwright interactions.
2. Update `process_facebook_comments_tab` line 1292 to retry private inboxes when `not existing_rec or not existing_rec.get("private_inbox_sent")`.
3. Fix timestamp parsing regexes (`giây`, `s`, `w`, `y`) and replace naive substring stripping in JS `inspect_comment_panel`.
4. Fix Messenger chat bubble bounds (`r.bottom < 885`), filter date separators, and add row customer name fallback.

---

## 5. Verification Method

1. **Unit Test Suite**:
   Run:
   `python -m unittest discover -s . -p "test_*.py" -v`
   All existing 15 tests must pass.
2. **New Regression Tests**:
   Verify new tests covering:
   - `needs_inbox_only` retry when `private_inbox_sent == False`.
   - `clean_comment_text` with `giây` / `s`.
   - `is_old_comment_timestamp` with `w` / `y`.
   - Customer query with "ngày", "giờ", "phút" preserved.
   - `safe_click` simulated pointer-intercept resilience.
