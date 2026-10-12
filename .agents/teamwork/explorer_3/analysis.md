# Detailed Investigation & Regression Test Plan

## 1. Executive Summary

This investigation analyzed the test infrastructure, live execution logs, and automated verification setup for the DAN86 Fanpage 24/7 automated bot (`asset_id=104011958817512`).

Key findings:
1. **Existing Unit Test Suite**: `python -m unittest discover -s . -p "test_*.py" -v` runs **15 tests** in 1.700s with **0 failures, 0 errors, and 0 warnings**.
2. **Root Cause of Error Logs**: Recent logs in `state/bot_status.json` revealed repeated 30-second Playwright timeouts (`Locator.click: Timeout 30000ms exceeded`) caused by `<span ...>Đức Trí</span> from ... detail_column subtree intercepts pointer events` on `div[role="dialog"]`. The underlying cause is that `type_human_like` and element clickers in `bot/page_bot_engine.py` use standard `await locator.click()` without `force=True`, scroll into view, or JavaScript `evaluate("el => el.focus(); el.click()")` fallback.
3. **Critical Test Gaps**:
   - Zero tests for pointer-intercept resilience and fallback clicks.
   - Zero tests for `needs_inbox_only` comment handling (especially when `private_inbox_sent == False` in existing records or when the button is `See Chat`).
   - Missing boundary tests for timestamp thresholds (<= 3 days vs > 3 days) combined with unconditional comment contents (single dot, emojis, stickers).
   - Missing unit tests for Messenger DOM message extraction (customer left bubble vs page right bubble) and thread prioritization.
4. **Live Verification Feasibility**: Successfully verified that headless Playwright using `state/fb_storage_state.json` connects to Meta Business Suite in ~9 seconds, accurately extracts live comments and messages without triggering login redirects or modifying post state. Local PC is completely clean of any Playwright/bot loops (only read-only `dashboard.py` runs).

---

## 2. Baseline Test Suite Execution

### 2.1 Execution Command & Output
Command executed:
```bash
python -m unittest discover -s . -p "test_*.py" -v
```

Output:
```text
test_dashboard_data_collector (test_auth_and_dashboard.TestAuthAndDashboard) ... ok
test_dashboard_formatting (test_auth_and_dashboard.TestAuthAndDashboard) ... ok
test_extract_and_sync (test_auth_and_dashboard.TestAuthAndDashboard) ... ok
test_sanitize_cookie (test_auth_and_dashboard.TestAuthAndDashboard) ... ok
test_01_non_repeating_random_templates (test_bot_logic.TestDan86BotLogic) ... ok
test_02_clean_customer_name_and_system_blacklist (test_bot_logic.TestDan86BotLogic) ... ok
test_03_comment_reply_once_and_auto_inbox (test_bot_logic.TestDan86BotLogic) ... ok
test_04_inbox_exact_three_hour_silence_logic (test_bot_logic.TestDan86BotLogic) ... ok
test_05_multiple_comments_on_same_post_no_collision (test_bot_logic.TestDan86BotLogic) ... ok
test_06_short_and_sticker_comments_handled (test_bot_logic.TestDan86BotLogic) ... ok
test_07_multiple_candidates_scan_does_not_abort_on_skipped_comment (test_bot_logic.TestDan86BotLogic) ... ok
test_08_old_comment_filtering_and_clean_text (test_bot_logic.TestDan86BotLogic) ... ok
test_09_repeat_comment_from_previous_user (test_bot_logic.TestDan86BotLogic) ... ok
test_10_origins_preservation_and_secret_safety (test_bot_logic.TestDan86BotLogic) ... ok
test_11_customer_inquiry_with_year_month_not_rejected (test_bot_logic.TestDan86BotLogic) ... ok

----------------------------------------------------------------------
Ran 15 tests in 1.700s

OK
```

### 2.2 Suite Breakdown
| Test File | Test Method | Scope / Focus | Result |
|---|---|---|---|
| `test_auth_and_dashboard.py` | `test_sanitize_cookie` | Cookie sanitation rules | PASS |
| `test_auth_and_dashboard.py` | `test_extract_and_sync` | SSO cookie extraction & file sync | PASS |
| `test_auth_and_dashboard.py` | `test_dashboard_formatting` | Time ago & timestamp string formatting | PASS |
| `test_auth_and_dashboard.py` | `test_dashboard_data_collector` | Dashboard JSON payload schema | PASS |
| `test_bot_logic.py` | `test_01_non_repeating_random_templates` | Anti-repeat template randomization | PASS |
| `test_bot_logic.py` | `test_02_clean_customer_name_and_system_blacklist` | System label blacklist & real name extraction | PASS |
| `test_bot_logic.py` | `test_03_comment_reply_once_and_auto_inbox` | Comment replied once + inbox sent | PASS |
| `test_bot_logic.py` | `test_04_inbox_exact_three_hour_silence_logic` | 3-stage inbox transitions & 180m silence timer | PASS |
| `test_bot_logic.py` | `test_05_multiple_comments_on_same_post_no_collision` | Distinct key generation on same post | PASS |
| `test_bot_logic.py` | `test_06_short_and_sticker_comments_handled` | Single char, emoji, sticker acceptance | PASS |
| `test_bot_logic.py` | `test_07_multiple_candidates_scan_does_not_abort_on_skipped_comment` | Multi-candidate scan loop without early break | PASS |
| `test_bot_logic.py` | `test_08_old_comment_filtering_and_clean_text` | Regex timestamp parsing & text prefix cleaning | PASS |
| `test_bot_logic.py` | `test_09_repeat_comment_from_previous_user` | New comments by previously replied customers | PASS |
| `test_bot_logic.py` | `test_10_origins_preservation_and_secret_safety` | `business.facebook.com` localStorage preservation | PASS |
| `test_bot_logic.py` | `test_11_customer_inquiry_with_year_month_not_rejected` | Preserving inquiry content containing "1 năm" | PASS |

---

## 3. Investigation of Recent Error Logs & Pointer-Event Interception

### 3.1 Verbatim Error from `state/bot_status.json`
```json
"2026-10-11 23:25:46,627 [WARNING] Lỗi khi xử lý bình luận thứ 0: Locator.click: Timeout 30000ms exceeded."
"Call log:"
"  - waiting for locator(\"div[role=\\\"dialog\\\"]\").last.locator(\"div[role=\\\"textbox\\\"][contenteditable=\\\"true\\\"], textarea\").first"
"    - locator resolved to <div role=\"textbox\" spellcheck=\"false\" contenteditable=\"true\" class=\"notranslate _5rpu\">…</div>"
"  - attempting click action"
"    2 × waiting for element to be visible, enabled and stable"
"      - element is visible, enabled and stable"
"      - scrolling into view if needed"
"      - done scrolling"
"      - <span class=\"x1lliihq x6ikm8r x10wlt62 x1n2onr6 x1j85h84\">Đức Trí</span> from <span data-surface-wrapper=\"1\" data-surface=\"/bizweb:inbox/bizweb:INBOX/lib:bizweb_inbox:main_content/lib:bizweb_inbox:content_layout/lib:inbox:thread_and_detail/lib:inbox:detail_column\">…</span> subtree intercepts pointer events"
"    - retrying click action"
"      - waiting 500ms"
```

### 3.2 Root Cause Analysis
1. **Unprotected Focus Click in `type_human_like`**:
   In `bot/page_bot_engine.py` line 192:
   ```python
   async def type_human_like(page: Page, locator: Locator, text: str) -> None:
       await locator.click() # <--- NO timeout override, NO force=True, NO fallback!
   ```
   When the popup dialog opened to send a private inbox message, the MBS detail column overlay `<span data-surface="...">...</span>` physically overlapped the center of the textbox. Playwright's default actionability check waited for pointer events for the full default 30,000ms, failed, and threw `TimeoutError`.
2. **Cascading Failure**:
   When this exception occurred:
   - The private inbox message was never typed or sent.
   - The execution jumped to line 1445 (`except Exception as e: logger.warning(...)`).
   - `memory.mark_comment_replied` was never called for this comment.
   - In `state/bot_memory.json`, at least 8 older comments also had `"private_inbox_sent": false` (e.g., records for Hoa Lily, Huong Ho Thi, Nhi My, Phạm Đông, Mark Tran, PT Phuks, Lê Như).
3. **Defect in `needs_inbox_only` Detection**:
   In `bot/page_bot_engine.py` line 1290-1296:
   ```python
   if cand_has_reply and comment_key:
       existing_rec = memory.data["replied_comments"].get(comment_key)
       if not existing_rec:
           target_candidate = cand
           target_key = comment_key
           needs_inbox_only = True
           break
   ```
   If `existing_rec` was recorded with `private_inbox_sent: false`, `not existing_rec` evaluated to `False`. The bot completely skipped sending the private inbox on subsequent cycles!
   Furthermore, in JavaScript line 697:
   ```javascript
   const stillNeedsMsgBtn = mText.includes('gửi tin nhắn') || mText.includes('nhắn tin') || mText.includes('send message');
   ```
   If Facebook renders the button as `"See Chat"`, `stillNeedsMsgBtn` evaluated to `false`.

---

## 4. Test Gaps & Regression Test Plan

### Gap 1: Pointer-Intercept Resilience
- **Objective**: Ensure all click actions on interactive elements (buttons, inputs, dialogs) never freeze for 30s and fall back smoothly through:
  1. `locator.scroll_into_view_if_needed(timeout=...)`
  2. `locator.click(timeout=..., force=True)`
  3. `locator.evaluate("el => el.click()")` / `locator.evaluate("el => { el.focus(); el.click(); }")`
- **Proposed Test**: `test_safe_click_and_safe_focus_resilience`
  - Mock a Playwright `Locator` whose initial `.click()` raises `TimeoutError("subtree intercepts pointer events")`.
  - Verify that the safe click helper catches this error, retries with `force=True` or JS evaluate, and completes within < 1000ms.
  - Verify `type_human_like` gracefully focuses and types even when the locator's center is overlaid by a sticky header or detail column.

### Gap 2: `needs_inbox_only` Comment Handling
- **Objective**: Verify that when a comment already has a public reply in DOM (`has_page_reply_in_dom=True`), but private message was not yet sent:
  1. If comment is new to memory: `needs_inbox_only == True`, skips public reply, sends private inbox, records `private_inbox_sent=True`.
  2. If comment exists in memory with `private_inbox_sent == False`: recognizes that inbox is still required, re-attempts inbox, updates `private_inbox_sent=True`.
  3. If comment exists in memory with `private_inbox_sent == True`: ignores and does not re-send (zero duplicates).
- **Proposed Test**: `test_needs_inbox_only_comment_lifecycle`
  - Add `memory.should_send_private_inbox_for_comment(comment_key)` or verify `needs_inbox_only` condition.
  - Test transitions with mock candidates having `has_page_reply=True` and `msg_btn_text="See Chat"`.

### Gap 3: Unconditional Comment Handling & Timestamp Filtering Boundary
- **Objective**: Verify strict enforcement of the 3-day timestamp boundary:
  - <= 3 days (`vừa xong`, `giây`, `phút`, `giờ`, `hôm qua`, `1 ngày`, `2 ngày`, `3 ngày`) -> Accepted.
  - > 3 days (`4 ngày`, `5 ngày`, `1 tuần`, `2 tháng`, `1 năm`) -> Strictly rejected.
  - Unconditional content acceptance: Single dot (`.`), emojis (`❤️`, `🔥`), stickers (`[Sticker / GIPHY]`), numbers (`1`), short text (`Ib`).
  - Combination rule: A single dot posted 2 hours ago MUST be replied; a single dot posted 4 days ago MUST be ignored.
- **Proposed Test**: `test_unconditional_comment_and_timestamp_boundary`
  - Matrix test covering combinations of comment texts and timestamps.

### Gap 4: Messenger Thread Detection & 180m Silence Timer
- **Objective**:
  1. Verify thread list selector prioritization:
     - `div[role="presentation"].x1ypdohk`, `div._a6ag._a6ah`, `[role="navigation"] [role="listitem"]`.
  2. Verify message direction classification:
     - Left-aligned bubble (`r.left <= 620`) without brand signature = Customer message.
     - Right-aligned bubble (`r.left > 620`) or brand signature (`dan86.vn`, `0933 133 516`) = Page message.
  3. Verify silence timer behavior:
     - Stage 0 -> 1: Customer first message -> `FIRST_REPLY`.
     - 179 minutes mutual silence -> `NONE`.
     - Exactly 180 minutes mutual silence -> `WAIT_STAFF_REPLY`.
     - Human staff message -> resets interaction timestamp to prevent bot interruption.
     - Thread observed for the first time with unreplied customer message -> does not falsely claim already replied.
- **Proposed Test**: `test_messenger_message_direction_and_silence_boundary`

---

## 5. Live Meta Business Suite Verification Feasibility

### 5.1 Feasibility Assessment
Live headless verification against Meta Business Suite is **100% feasible and non-destructive**:
1. Session validity verified:
   - `state/fb_storage_state.json` contains 18 active cookies (`c_user`, `xs`) and origins for both `https://business.facebook.com` and `https://www.facebook.com`.
2. Live headless script test:
   - Executed `scripts/test_robust_comment_extraction.py`: connected to `https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512` in **9.2 seconds** headless, successfully extracted 3 live comments (Đức Trí, Tác giả, Lệ Thuyền).
   - Executed `scripts/inspect_messenger_details.py`: connected to `https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512` in **9.1 seconds** headless, successfully extracted 6 messages and detected customer messages ("Set quà 450k").
   - Neither script triggered Facebook security checkpoints, login redirects, or DOM mutation.

### 5.2 Local PC Cleanliness Audit
- Audit command: `Get-Process python*, *playwright*, headless_shell*`
- Result: Exactly 1 python process running: PID 19252 (`python dashboard.py`).
- Zero instances of `2_chay_bot_truc_page.py`.
- Zero instances of Playwright `headless_shell.exe`.
- Requirement R1 (Zero local bot execution) is strictly satisfied on the local machine.

### 5.3 GitHub Actions VPS Status
- Remote workflow: `.github/workflows/vps_bot_24_7.yml` on `DucTri2207/chatbot-dan86`.
- Active run: Run ID `38184826832` (`DAN86 Fanpage Bot 24-7 VPS`, branch `master`) is currently `in_progress`.
- No pending queue blockage or duplicate respawn loops detected.
