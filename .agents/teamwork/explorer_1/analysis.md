# Detailed Investigation & Analysis: R2 (Comments) & R3 (Messenger Inbox)

**Investigator**: Explorer 1 (`teamwork_preview_explorer`)  
**Date**: 2026-10-12  
**Target Codebase**: `d:\chat bot dan 86`  
**Reference Specification**: `d:\chat bot dan 86\.agents\teamwork\ORIGINAL_REQUEST.md`

---

## 1. Executive Summary

This investigation analyzed the automation loops, DOM scrapers, memory storage, and Playwright execution paths for:
- **R2: Comment Automation** (`process_facebook_comments_tab`, `inspect_comment_panel`, `send_private_inbox_to_commenter`, `memory_store.py`)
- **R3: Messenger Inbox Automation** (`process_messenger_inbox_tab`, `inspect_messenger_conversation`, `decide_inbox_action`)

### Critical Findings:
1. **Pointer-Event Interception Failure (`subtree intercepts pointer events`)**:
   - Live VPS logs in `state/bot_status.json` revealed:
     `<span class="x1lliihq x6ikm8r x10wlt62 x1n2onr6 x1j85h84">Đức Trí</span> from <span data-surface-wrapper="1" data-surface="/bizweb:inbox/bizweb:INBOX/lib:bizweb_inbox:main_content/lib:bizweb_inbox:content_layout/lib:inbox:thread_and_detail/lib:inbox:detail_column">…</span> subtree intercepts pointer events`
   - Root cause: Multiple `.click()` calls in `bot/page_bot_engine.py` (lines 192, 1011, 1093, 1371, 1381, 1397, 1662) lack `force=True`, lack `scroll_into_view_if_needed`, or have default 30-second Playwright timeouts without JS fallback. The fixed right column (`detail_column`) overlaps middle pane elements during scroll/coordinate hit-testing.
2. **Missed Private Inboxes on Comments with Existing Page Reply (`needs_inbox_only`)**:
   - In `process_facebook_comments_tab` (lines 1288-1297), the check is `if not existing_rec:`. If a comment was previously recorded in `memory.data["replied_comments"]` with `private_inbox_sent: False` (e.g. after a previous click interception timeout or failure), the bot **never retries sending the private inbox**, violating R2 item 4.
   - In `inspect_comment_panel` (lines 691-700), the JavaScript DOM scraper filtered out comments with `c.hasPageReply == True` unless `isVeryRecent` (`giây|phút|giờ`) or button had text "gửi tin nhắn". If a comment is `hôm qua` or `1-3 ngày` and has a public reply, but button is `See Chat`, JS dropped it before Python could inspect it.
3. **Comment Content Parsing Corruption**:
   - In JS `inspect_comment_panel` line 633, `contentLines` excluded any line where `low.includes('ngày') || low.includes('giờ') || low.includes('phút')`. If a customer asks *"Bao nhiêu ngày thì nhận được hàng?"*, the entire question is deleted, collapsing into `.`!
   - In Python `clean_comment_text` (line 344) and JS line 648, `giây` and `s` prefixes were missing from the stripping regex.
4. **Messenger Latest Message Clipping (`r.bottom < 840`)**:
   - In `inspect_messenger_conversation` line 554, `chatNodes` used `r.bottom < 840`. On a 900px viewport, the latest customer message bubble immediately above the composer frequently sits at y=840..870. The scraper clipped the newest customer message, causing the bot to read an older Page message and remain silent.
   - Date separators ("Hôm nay", "12 tháng 10") with `r.left > 620` could be mistaken for Page messages if positioned at the bottom of the chat.

---

## 2. In-Depth Investigation: R2 (Comment Automation)

### 2.1 File Map & Entry Points
- **Runner Entry**: `2_chay_bot_truc_page.py` (lines 211-215):
  ```python
  cmt_replied = await process_facebook_comments_tab(
      page=page,
      memory=memory,
      dry_run=dry_run,
  )
  ```
- **Core Engine**: `bot/page_bot_engine.py`:
  - `process_facebook_comments_tab`: lines 1167-1470
  - `inspect_comment_panel`: lines 483-798
  - `tag_comment_target_in_dom`: lines 800-859
  - `send_private_inbox_to_commenter`: lines 980-1165
  - `send_inbox_via_messenger_search`: lines 861-962
  - `is_old_comment_timestamp`: lines 360-390
  - `clean_comment_text`: lines 334-358
  - `ensure_newest_comments_filter`: lines 392-438
  - `expand_all_comment_replies`: lines 444-481
- **State & Memory Management**: `bot/memory_store.py`:
  - `should_reply_comment`: lines 121-188
  - `prepare_comment_and_inbox_replies`: lines 189-208
  - `mark_comment_replied`: lines 209-247
  - `make_comment_key`: lines 33-66

### 2.2 Comment Timestamp Parsing and Evaluation
1. **Extraction**:
   - In JS `inspect_comment_panel` (lines 602-612):
     ```javascript
     let timeStr = "";
     const tAria = aria.match(/(?:vào|at|on)\s+(.+?)(?:$)/i);
     if (tAria && tAria[1]) {
         timeStr = tAria[1].trim();
     }
     if (!timeStr) {
         const timeLine = lines.find(l => /^\s*\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm|m|h|d|w|y|mins?|hours?|days?|weeks?|months?|years?)\s*(?:trước|ago)?\s*$/i.test(l.trim()) || /^(?:vừa xong|just now|hôm qua|yesterday)$/i.test(l.trim()));
         if (timeLine) {
             timeStr = timeLine.trim();
         }
     }
     ```
2. **Old vs New Evaluation**:
   - Timestamps to **Process**: `vừa xong`, `just now`, `giây`, `s`, `phút`, `m`, `giờ`, `h`, `hôm qua`, `yesterday`, `1–3 ngày` (`1-3 days`).
   - Timestamps to **Ignore**: `tuần`, `tháng`, `năm`, `w`, `y`, `week`, `month`, `year`, and `> 3 ngày` (4 ngày, 5 ngày...).
   - **Flaws identified**:
     - Python `is_old_comment_timestamp` (line 370) checked `\b\d+\s*(tuần|tháng|năm|week|month|year)s?\b`, missing English abbreviations `w` and `y` (e.g. `2w`, `1y`).
     - Python `clean_comment_text` (line 344) and JS line 648 did not include `giây` or `s` in the prefix cleaner:
       `r'^\s*\d+\s*(?:phút|giờ|ngày|tuần|tháng|năm|m|h|d|w|y|mins?|hours?|days?|weeks?|months?|years?)...'`
       If a customer comments `"15 giây Cho em xin giá"`, the time prefix is not cleaned.

### 2.3 Comment Filtering & Unconditional Handling
- In `bot/memory_store.py` (`should_reply_comment` lines 141-188):
  - Correctly excludes system labels (`is_system_label`).
  - Correctly permits short comments, single characters (`.`), emojis (`❤️`), stickers (`[Sticker / GIPHY]`).
  - Correctly isolates comments by `cmt:{post_id}:{dom_index}:{digest}`, so previous commenters are **not** permanently blocked from having new comments replied to.
- **Flaws identified**:
  - In JS `inspect_comment_panel` (line 633):
    `if (l === authorName || low.includes('tuần') || low.includes('ngày') || low.includes('phút') || low.includes('giờ') || l === '·') return false;`
    This naive substring check (`low.includes('ngày')`) destroys legitimate Vietnamese comments like:
    *"Shop ơi giao hàng mấy ngày tới nơi?"* or *"Ngày mai có gửi được không?"*.
    **Fix**: Only filter out lines that match strict timestamp line regex, e.g.:
    `/^\s*\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm|m|h|d|w|y|mins?|hours?|days?|weeks?|months?|years?)\s*(?:trước|ago)?\s*$/i.test(l.trim()) || /^(?:vừa xong|just now|hôm qua|yesterday|·)$/i.test(l.trim())`

### 2.4 Nested Public Replies and Private Direct Messages
- **Public Reply Trigger**:
  `should_reply_comment` returns `True` when `has_page_reply_in_dom == False` and `key not in memory.data["replied_comments"]`.
  Bot likes comment, clicks `[data-dan86-reply-btn="true"]` / "Trả lời", types randomized template from `COMMENT_REPLIES`, presses Enter.
- **Private Direct Message Trigger**:
  Bot calls `send_private_inbox_to_commenter`:
  1. Popup Modal: types in `div[role="textbox"][contenteditable="true"]` inside `div[role="dialog"]`, clicks send / Enter.
  2. See Chat composer: types in message composer on customer chat view.
  3. Messenger Search Fallback: opens `META_INBOX_MESSENGER_URL`, searches customer name, opens thread, sends message.
- **Flaws identified**:
  - In `process_facebook_comments_tab` (lines 1288-1297):
    ```python
    if cand_has_reply and comment_key:
        existing_rec = memory.data["replied_comments"].get(comment_key)
        if not existing_rec:
            target_candidate = cand
            target_key = comment_key
            needs_inbox_only = True
            break
    ```
    If `existing_rec` exists, but `existing_rec.get("private_inbox_sent")` is `False`, the bot **never retries sending the private message**.
    **Fix**:
    ```python
    if comment_key:
        existing_rec = memory.data["replied_comments"].get(comment_key)
        if cand_has_reply and (not existing_rec or not existing_rec.get("private_inbox_sent")):
            target_candidate = cand
            target_key = comment_key
            needs_inbox_only = True
            break
    ```
  - In JS `inspect_comment_panel` (lines 691-700):
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
    If a comment is 1-3 days old or has button `See Chat`, `unrepliedList` drops it, preventing Python from checking if `private_inbox_sent` is missing!
    **Fix**: Keep all new comments (`!c.isPageReply && !c.isOldComment`) in `unrepliedList` so Python can check memory for `has_page_reply` and `private_inbox_sent`.

### 2.5 Verification of Post Status Modifications (Delete/Hide/Done)
- Scanned entire repository for "đã xong", "done", "ẩn", "hide", "xóa", "delete".
- Verified: **Zero logic deletes, hides, or marks posts as Done**.
- Post selection at line 1228 explicitly clicks at `x=150, y=40` on list rows to avoid the menu/delete trigger at `x=490`.
- Dialog closer at line 965 only closes dialogs with `[aria-label="Đóng"], [aria-label="Close"]` inside `div[role="dialog"]`.

### 2.6 Pointer-Event Interception Root Cause & Playwright Click Hardening
- **Direct Evidence**: `state/bot_status.json` lines 21-25:
  ```
  - scrolling into view if needed
  - done scrolling
  - <span class="x1lliihq x6ikm8r x10wlt62 x1n2onr6 x1j85h84">Đức Trí</span> from <span data-surface-wrapper="1" data-surface="/bizweb:inbox/bizweb:INBOX/lib:bizweb_inbox:main_content/lib:bizweb_inbox:content_layout/lib:inbox:thread_and_detail/lib:inbox:detail_column">…</span> subtree intercepts pointer events
  - retrying click action
  - waiting 500ms
  ```
- **Locations of Vulnerable Clicks**:
  1. `marked_msg_btn.click()` (line 1011): no timeout, no `force=True`.
  2. `send_btn.click()` (line 1093): no timeout, no `force=True`.
  3. `locator.click()` in `type_human_like` (line 192): no timeout, no `force=True`.
  4. `like_btn.click(timeout=2000)` (line 1371): no `force=True`.
  5. `marked_reply_btn.click(timeout=2500)` (line 1381): no `force=True`.
  6. `reply_btn.click(timeout=2500)` (line 1397): no `force=True`.
  7. `item.click(timeout=4000)` (line 1662): clicks center without coordinates, overlapping `detail_column`.
- **Proposed Solution**:
  Introduce a robust helper `safe_click`:
  ```python
  async def safe_click(
      locator: Locator,
      position: Optional[dict] = None,
      timeout_ms: int = 3000,
  ) -> bool:
      try:
          await locator.scroll_into_view_if_needed(timeout=1500)
      except Exception:
          pass
      try:
          if position:
              await locator.click(timeout=timeout_ms, force=True, position=position)
          else:
              await locator.click(timeout=timeout_ms, force=True)
          return True
      except Exception:
          try:
              await locator.evaluate("""el => {
                  el.scrollIntoView({block: 'center', inline: 'nearest'});
                  el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true, view: window}));
                  el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true, view: window}));
                  el.click();
              }""")
              return True
          except Exception:
              return False
  ```

---

## 3. In-Depth Investigation: R3 (Messenger Inbox Automation)

### 3.1 File Map & Entry Points
- **Runner Entry**: `2_chay_bot_truc_page.py` lines 218-222:
  ```python
  inbox_replied = await process_messenger_inbox_tab(
      page=page,
      memory=memory,
      dry_run=dry_run,
  )
  ```
- **Engine Methods**: `bot/page_bot_engine.py`:
  - `process_messenger_inbox_tab`: lines 1610-1725
  - `inspect_messenger_conversation`: lines 1476-1608
- **Memory Logic**: `bot/memory_store.py`:
  - `decide_inbox_action`: lines 251-337
  - `record_inbox_reply`: lines 338-363
  - `touch_staff_interaction`: lines 364-379

### 3.2 Thread List Selectors
- In `process_messenger_inbox_tab` (lines 1630-1636):
  ```python
  thread_selectors = [
      'div[role="presentation"].x1ypdohk',
      'div._a6ag._a6ah',
      '[role="navigation"] [role="listitem"]',
      '[role="grid"] [role="row"]',
      'div[role="listitem"]',
  ]
  ```
- Iterates over top `MAX_THREADS_PER_CYCLE` (10) conversation rows.
- Clicks at `position={"x": 150, "y": 40}`.
- **Improvement**: In line 1662, fallback `await item.click(timeout=4000)` must also specify `position={"x": 150, "y": 40}` and `force=True`, or use `safe_click(item, position={"x": 150, "y": 40})`.
- **Name Extraction Enhancement**: When clicking `item`, read the customer name from `(await item.inner_text()).split("\n")[0]`. If `inspect_messenger_conversation` fails to detect the name in the chat header and returns `"bạn"`, fallback to the row's customer name.

### 3.3 Customer vs Page Message Detection
- In `inspect_messenger_conversation` (lines 1550-1590):
  - Gathers chat nodes matching `[dir="auto"], [role="row"]`.
  - Determines if sender is Page via:
    - `hasBrandSignature`: checks `dan86.vn`, `0933 133 516`, `nhân viên tư vấn`, `bộ phận tư vấn`.
    - `isRightAligned = r.left > 620`: Outgoing Page bubbles are right-aligned.
    - `isPage = hasBrandSignature || isRightAligned`.
  - Determines `lastMsg = messages[messages.length - 1]`.
  - Sets `last_sender_is_page = lastMsg.isPage`.
  - Sets `has_prior_page_messages = messages.slice(0, -1).some(m => m.isPage)`.
- **Flaws identified**:
  1. `r.bottom < 840` in line 1554:
     In a 900px viewport, the lowest message bubble is often at y=840..870. The newest incoming message gets excluded!
     **Fix**: Change condition to `r.bottom < 885` and exclude elements inside `[role="textbox"]`.
  2. Date dividers / status markers:
     Pills like "Hôm nay", "12 tháng 10", "Đã xem" with `r.left > 620` can be misidentified as Page messages.
     **Fix**: Filter out lines matching `/^(hôm nay|today|hôm qua|yesterday|thứ [hai|ba|tư|năm|sáu|bảy]|chủ nhật|\d{1,2}\s+tháng\s+\d{1,2}|\d{1,2}:\d{2}(\s*(am|pm))?|đã xem|seen)$/i`.

### 3.4 3-Stage Lifecycle and Human Staff Handoff
- **Stage 0 -> Stage 1 (First Customer Message)**:
  - `record is None and not has_prior_page_messages_in_dom`.
  - Bot generates randomized `FIRST_INBOX_REPLIES` greeting & product consultation message.
  - Bot records conversation in `memory.data["conversations"][thread_key]` with `stage = 1`, `last_bot_reply_ts = now`.
  - **Pause**: All future customer messages within 180 minutes return `NONE` (bot remains silent).
- **Stage 1 -> Stage 2 (Returning Customer after >= 180 Minutes Silence)**:
  - If `elapsed_seconds >= silence_threshold` (10,800 seconds / 3 hours):
  - Bot sends randomized `WAIT_STAFF_REPLIES` message ("please wait for staff").
  - Bot records `stage = 2` with `last_bot_reply_ts = now`.
  - **Pause**: Any immediate follow-up message returns `NONE` (bot remains silent).
- **Staff Interaction (`touch_staff_interaction`)**:
  - When `last_sender_is_page == True`:
  - Bot calls `touch_staff_interaction`, updating `last_interaction_ts = now` and resetting `stage = 1`.
  - Resets the 180-minute countdown, ensuring the bot never interrupts ongoing human conversations.

---

## 4. Proposed Fixes & Code Changes

### Proposed Fix 1: Add `safe_click` & Harden All Clicks (`bot/page_bot_engine.py`)
Replace naked `.click()` calls with `safe_click` and ensure fallback to keyboard Enter.

### Proposed Fix 2: Enhance Timestamp Parsing & Text Cleaning (`bot/page_bot_engine.py`)
- Add `giây` and `s` to `clean_comment_text`.
- Add `w` and `y` to `is_old_comment_timestamp`.
- In JS `inspect_comment_panel`, only filter timestamp lines using full line regex rather than `low.includes('ngày')`.

### Proposed Fix 3: Fix `needs_inbox_only` Retries (`bot/page_bot_engine.py`)
In `process_facebook_comments_tab` (lines 1288-1297):
```python
# Before:
if cand_has_reply and comment_key:
    existing_rec = memory.data["replied_comments"].get(comment_key)
    if not existing_rec:
        target_candidate = cand
        target_key = comment_key
        needs_inbox_only = True
        break

# After:
if comment_key:
    existing_rec = memory.data["replied_comments"].get(comment_key)
    if cand_has_reply and (not existing_rec or not existing_rec.get("private_inbox_sent")):
        target_candidate = cand
        target_key = comment_key
        needs_inbox_only = True
        break
```

### Proposed Fix 4: Messenger Scraper Bounds & Date Filter (`bot/page_bot_engine.py`)
- Change `r.bottom < 840` to `r.bottom < 885` and exclude `!el.closest('[role="textbox"]')`.
- Filter date separators and "Đã xem" / "Seen".
- Add thread row customer name fallback.
