# Changes Log — Worker 1 (Hardening & Regression Testing)

**Date**: 2026-10-12  
**Agent**: Worker 1 (`teamwork_preview_worker`)  
**Scope**: `dashboard.py`, `bot/bot_config.py`, `bot/page_bot_engine.py`, `test_hardening_regression.py`

---

## 1. Summary of Changes

### 1.1 `dashboard.py`
- **Location**: Line 17
- **Change**: Removed unused `import subprocess`.
- **Rationale**: Strict compliance with R1 (Zero Local Execution). Ensures `dashboard.py` is strictly a passive, read-only telemetry and sync server with zero process-spawning capabilities.

### 1.2 `bot/bot_config.py`
- **Location**: Line 166
- **Change**: Updated `SCAN_INTERVAL_SECONDS = (15, 30)` (previously `(25, 45)`).
- **Rationale**: Strictly satisfies R4 requirement of 15–30s latency between VPS scan cycles.

### 1.3 `bot/page_bot_engine.py`
- **`safe_click` Helper Function Added**:
  - Implemented `safe_click(locator, timeout=2500, position=None)`:
    * Scrolls element into view with `locator.scroll_into_view_if_needed(timeout=1500)`
    * Attempts `locator.click(timeout=timeout, force=True, position=position)`
    * Catches any exception (e.g. pointer interception by Meta Business Suite right detail column) and executes synthetic DOM event fallback via `locator.evaluate`:
      `el => { el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window})); el.click(); }`
    * Returns `True` on success, `False` on total failure without crashing the bot loop.
- **Vulnerable Clicks Replaced with `safe_click`**:
  * Line 227: `type_human_like` focus click -> `await safe_click(locator, timeout=2500)`
  * Line 931: `send_inbox_via_messenger_search` thread item -> `await safe_click(item, timeout=3000, position={"x": 150, "y": 40})`
  * Line 941: `send_inbox_via_messenger_search` search box -> `await safe_click(search_box, timeout=2500)`
  * Line 949: `send_inbox_via_messenger_search` search result -> `await safe_click(first_res, timeout=3000, position={"x": 150, "y": 40})`
  * Line 1047: `marked_msg_btn` -> `await safe_click(marked_msg_btn, timeout=2500)`
  * Line 1129: `send_btn` -> `await safe_click(send_btn, timeout=2500)`
  * Line 1264: `process_facebook_comments_tab` post item selection -> `await safe_click(item, timeout=3000, position={"x": 150, "y": 40})`
  * Line 1407: `like_btn` -> `await safe_click(like_btn, timeout=2000)`
  * Line 1417: `marked_reply_btn` -> `reply_clicked = await safe_click(marked_reply_btn, timeout=2500)`
  * Line 1432: `reply_btn` -> `reply_clicked = await safe_click(reply_btn, timeout=2500)`
  * Line 1695: `process_messenger_inbox_tab` thread item -> `await safe_click(item, timeout=3000, position={"x": 150, "y": 40})` with unpositioned fallback
- **`needs_inbox_only` Retries Fix in `process_facebook_comments_tab`**:
  * Changed condition at line 1328 from `if not existing_rec:` to:
    `if not existing_rec or not existing_rec.get("private_inbox_sent"):`
  * Guarantees that if a public reply already exists or was posted, but private inbox failed in a prior cycle (due to pointer intercept timeout), the bot retries sending the private message.
- **JS Scraper `inspect_comment_panel` Fixes**:
  * `contentLines` filtering: Replaced broad `low.includes('ngày')` / `low.includes('giờ')` check with dedicated timestamp line regex (`/^\s*\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm|s|m|h|d|w|y|secs?|mins?|hours?|days?|weeks?|months?|years?)\s*(?:trước|ago)?\s*$/i`). Legitimate customer inquiries like *"Mấy ngày có hàng shop ơi?"* or *"Có giao trong ngày không?"* are now 100% preserved.
  * Preserved `giây` and `s` in stripping regex.
  * `unrepliedList` filter: Now preserves comments aged `hôm qua` or `1-3 ngày` with `hasPageReply == true` whenever a message button is present ("gửi tin nhắn", "nhắn tin", "send message", "see chat", "xem đoạn chat", or `!!c.msgBtnText`).
- **Python Helpers Hardening**:
  * `clean_comment_text`: Added `giây`, `s`, `secs?` to the timestamp prefix stripper.
  * `is_old_comment_timestamp`: Added English abbreviations `w` and `y`, and day abbreviations `d` to properly recognize `1w`, `2w`, `1y`, `4d`.
- **Messenger Message Extraction Bounds Expansion in `inspect_messenger_conversation`**:
  * Expanded `r.bottom < 840` to `r.bottom < 885` so recent customer messages sitting right above the composer (y=840..870) are never clipped.
  * Explicitly excluded textbox elements: `if (el.closest('[role="textbox"], textarea, input')) return false;`.

### 1.4 `test_hardening_regression.py`
- Added 12 comprehensive unit tests:
  1. `test_safe_click_success_standard`: Normal click flow with force=True.
  2. `test_safe_click_pointer_intercepted_triggers_js_fallback`: Simulated pointer interception triggering JS synthetic click.
  3. `test_safe_click_with_position_parameter`: Target position `x=150, y=40` preservation.
  4. `test_safe_click_total_failure_returns_false_safely`: Graceful error recovery without throwing.
  5. `test_needs_inbox_only_when_private_inbox_not_sent`: Retry logic when `private_inbox_sent: False`.
  6. `test_unconditional_comment_cleaning_and_preservation`: 1 char, emojis, stickers, questions containing "ngày"/"giờ", and time prefixes.
  7. `test_timestamp_boundaries_new_vs_old`: Boundary checks for <= 3 days (NEW) vs > 3 days (OLD) and shorthand units.
  8. `test_messenger_bubble_direction_and_sender_detection`: Bubble alignment (left customer vs right page bubbles and brand signatures).
  9. `test_messenger_vertical_bounds_excludes_textbox`: Y-bounds < 885 and composer exclusion.
  10. `test_messenger_3_stage_transitions_and_180min_rule`: 3-stage transitions and 180-minute mutual silence window.
  11. `test_scan_interval_satisfies_r4`: `SCAN_INTERVAL_SECONDS == (15, 30)`.
  12. `test_dashboard_has_zero_subprocess_imports`: AST audit confirming zero subprocess imports in `dashboard.py`.

---

## 2. Test Execution Results

Command:
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
test_dashboard_has_zero_subprocess_imports (test_hardening_regression.TestHardeningRegression) ... ok
test_messenger_3_stage_transitions_and_180min_rule (test_hardening_regression.TestHardeningRegression) ... ok
test_messenger_bubble_direction_and_sender_detection (test_hardening_regression.TestHardeningRegression) ... ok
test_messenger_vertical_bounds_excludes_textbox (test_hardening_regression.TestHardeningRegression) ... ok
test_needs_inbox_only_when_private_inbox_not_sent (test_hardening_regression.TestHardeningRegression) ... ok
test_safe_click_pointer_intercepted_triggers_js_fallback (test_hardening_regression.TestHardeningRegression) ... ok
test_safe_click_success_standard (test_hardening_regression.TestHardeningRegression) ... ok
test_safe_click_total_failure_returns_false_safely (test_hardening_regression.TestHardeningRegression) ... ok
test_safe_click_with_position_parameter (test_hardening_regression.TestHardeningRegression) ... ok
test_scan_interval_satisfies_r4 (test_hardening_regression.TestHardeningRegression) ... ok
test_timestamp_boundaries_new_vs_old (test_hardening_regression.TestHardeningRegression) ... ok
test_unconditional_comment_cleaning_and_preservation (test_hardening_regression.TestHardeningRegression) ... ok

----------------------------------------------------------------------
Ran 27 tests in 0.507s

OK
```
Result: **27 passed, 0 failed, 0 errors (100% pass rate)**.
