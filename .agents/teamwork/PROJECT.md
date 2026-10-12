# Project: Dần86Farm 24/7 Facebook Fanpage Bot Hardening & Cloud Verification

## Architecture
- **Local PC**: 0 bot processes. Purely read-only `dashboard.py` (Flask/HTTP) reading GitHub state or local sync.
- **Cloud VPS**: GitHub Actions 24/7 runner (`.github/workflows/vps_bot_24_7.yml`) executing `2_chay_bot_truc_page.py` with Playwright in headless mode.
- **Core Engine**: `bot/page_bot_engine.py` (Playwright automation for Meta Business Suite `inbox/facebook` and `inbox/messenger`), `bot/memory_store.py` (persistent memory of replied comments and messenger threads), `bot/bot_config.py` (configuration and reply templates).
- **Session & State Persistence**: `state/fb_storage_state.json` and `state/GITHUB_SECRET_VALUE.txt` (storing 29 cookies + 2 origins localStorage), `state/bot_memory.json` (replied records), `state/bot_status.json` (runtime telemetry and heartbeats).
- **Test Automation**: `test_bot_logic.py`, `test_auth_and_dashboard.py`, `test_hardening_regression.py`, `test_challenger_adversarial.py`.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Zero Local Bot Execution | Verify 0 background bot processes on Windows PC, ensure dashboard.py cannot launch local bots. | M1 | ORIGINAL_REQUEST § R1 |
| F2 | Safe Click & Pointer-Event Resilience | Implement `safe_click` with scroll, short timeout, `force=True`, and synthetic JS dispatchEvent/click fallback to eliminate subtree interception crashes. | M2 | ORIGINAL_REQUEST § R2, R4 |
| F3 | Unconditional Comment Handling | Handle all comments < 3 days regardless of text (emojis, single char, words containing 'ngày'/'giờ'), never delete/hide/mark Done, ignore > 3 days. | M2 | ORIGINAL_REQUEST § R2 |
| F4 | Robust Inbox Retries (needs_inbox_only) | Ensure private inbox is sent even if public reply exists whenever `private_inbox_sent` is False or missing. | M2 | ORIGINAL_REQUEST § R2 |
| F5 | Messenger Inbox Automation | Robust thread selectors, bubble orientation detection (customer vs page), Stage 0->1 greeting, Stage 1->2 after >= 180m silence. | M2 | ORIGINAL_REQUEST § R3 |
| F6 | Fast VPS Scan Latency & Session Safety | Set `SCAN_INTERVAL_SECONDS = (15, 30)`, preserve cookies & origins, prevent rebase conflicts. | M2 | ORIGINAL_REQUEST § R4 |
| F7 | Unit & Regression Test Suite | Pass existing 15 tests + 23 new regression tests (total 38 tests) covering safe_click, needs_inbox_only, timestamp parsing, messenger detection. | M3 | ORIGINAL_REQUEST § Acceptance Criteria |
| F8 | Live VPS & MBS Verification | Verify active VPS run in_progress with fresh heartbeat, verify headless MBS extraction non-destructively. | M4 | ORIGINAL_REQUEST § Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1: Local Isolation & Cleanliness | Audit & verify 0 local bot processes, remove unused subprocess in dashboard.py. | none | DONE |
| 2 | M2: Bot Engine & Config Hardening | Implement safe_click, fix needs_inbox_only, fix timestamp parsing, fix messenger boundary, tune latency to 15-30s. | M1 | DONE |
| 3 | M3: Comprehensive Test Suite | Run existing unit tests and add regression test suite covering all hardened features. | M2 | DONE |
| 4 | M4: Live Verification & VPS Sync | Verify GitHub Actions workflow in_progress, push updates if needed, verify live MBS. | M3 | DONE |

## Interface Contracts
### `bot/page_bot_engine.py` ↔ Playwright DOM
- `safe_click(locator, timeout=2500, position=None)`: Attempts standard click with `force=True`; on error or interception, falls back to `locator.evaluate("el => { el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window})); el.click(); }")`.
- `type_human_like(page, locator, text)`: Uses `safe_click` to focus and types characters with natural human jitter.
- `clean_comment_text(raw_text)`: Preserves Vietnamese inquiries containing 'ngày', 'giờ', 'phút' when part of sentences; strips dedicated timestamp prefixes/suffixes.
- `is_old_comment_timestamp(time_str)`: Accurately identifies `> 3 ngày`, `tuần`, `tháng`, `năm`, `w`, `y` strictly from time string.
