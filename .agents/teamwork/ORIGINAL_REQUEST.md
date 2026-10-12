# Original User Request

## 2026-10-11T23:38:37Z

Audit, harden, and verify the 24/7 automated Facebook Fanpage bot (`Dần86Farm - Sản phẩm và Quà tặng thuần Việt Nam`, `asset_id=104011958817512`) so it runs **100% on GitHub Actions VPS** (zero background bot processes on the user's local PC) and responds rapidly and reliably whenever a new comment or new Messenger message arrives.

Working directory: d:\chat bot dan 86
Integrity mode: development

## Requirements

### R1. Zero Local Execution — 100% Cloud VPS Operation
The bot must not run as a background process on the user's Windows PC. All continuous 24/7 scanning and replying must execute exclusively on the GitHub Actions VPS workflow (`DucTri2207/chatbot-dan86`, `.github/workflows/vps_bot_24_7.yml`), while the local Dashboard (`dashboard.py` / `dashboard.html`) only reads/syncs live state from GitHub without spawning local Playwright bot loops.

### R2. Immediate & Unconditional New Comment Handling (Public Reply + 1 Direct Inbox Message)
Whenever a new comment is posted on any Fanpage post (timestamps `vừa xong`, `giây`, `phút`, `giờ`, `hôm qua`, `1–3 ngày`), regardless of comment content (including single characters like `.`, emojis, stickers) and regardless of whether the commenter has commented or chatted in the past:
1. Never delete, hide, or mark any post as "Done" (`Đã xong`).
2. Strictly ignore old comments (`tuần`, `tháng`, `năm`, or `> 3 ngày`).
3. If the comment does not yet have a Page reply underneath it, post 1 non-repeating randomized nested public reply (`Nested Reply`) directly under that comment.
4. Whether or not the comment already had a public reply underneath it, if a private message has not yet been sent for that specific comment record in `state/bot_memory.json`, immediately send 1 direct private message (`Inbox`) to that commenter (via Popup Modal, `See Chat` composer, or Messenger search fallback) without pointer-event interception timeouts.

### R3. Immediate Automated Messenger Inbox Handling
Whenever a customer sends a direct message to the Fanpage Messenger Inbox (`inbox/messenger`):
1. Ensure the Messenger thread list selector reliably opens the top unread/recent conversation rows (`div[role="presentation"].x1ypdohk`, `div._a6ag._a6ah`) and accurately detects whether the last message is from the customer vs. the Page.
2. First-time customer message (`Stage 0 -> Stage 1`): immediately send 1 randomized greeting & product consultation message (`FIRST_INBOX_REPLIES`), then pause bot replies so human staff can take over.
3. Returning message after >= 180 minutes (3 hours) of mutual silence (`Stage 1 -> Stage 2`): send 1 randomized "please wait for staff" message (`WAIT_STAFF_REPLIES`), then remain silent.

### R4. Persistent Session & Fast VPS Loop Reliability
1. Preserve `origins` (`https://business.facebook.com` `localStorage`) and cookies in `state/fb_storage_state.json` and `state/GITHUB_SECRET_VALUE.txt` so the VPS session never redirects to `business/loginpage`.
2. Ensure the VPS scan loop runs continuously with minimal latency between cycles (`15–30s`), syncs `state/bot_memory.json` and `state/bot_status.json` to `origin/master` without Git rebase conflicts, and hands off shifts cleanly without getting stuck in `pending`.

## Verification Resources

- Existing unit test suites: `test_bot_logic.py` and `test_auth_and_dashboard.py` (`python -m unittest discover -s . -p "test_*.py" -v`).
- Live session state: `state/fb_storage_state.json` and GitHub repository `DucTri2207/chatbot-dan86`.
- Recent VPS logs in `state/bot_status.json` showing pointer-event interception (`subtree intercepts pointer events`) during click actions that must be eliminated.

## Acceptance Criteria

### Local PC Cleanliness
- [ ] Zero `2_chay_bot_truc_page.py` or Playwright `headless_shell.exe` bot processes running on the local Windows machine.

### Automated Comment & Messenger Verification
- [ ] All unit tests in `test_bot_logic.py` and `test_auth_and_dashboard.py` pass (`0` failures), plus new regression tests covering pointer-intercept resilience, `needs_inbox_only` comment handling, and Messenger thread detection.
- [ ] Live headless verification against Meta Business Suite (`inbox/facebook` and `inbox/messenger`) confirms zero `subtree intercepts pointer events` click timeouts, accurate detection of newest comments and unread/latest customer Messenger messages, and zero modification of post status.
- [ ] GitHub Actions workflow `vps_bot_24_7.yml` on `DucTri2207/chatbot-dan86` is verified in `in_progress` state (no `pending` queue jam) and actively pushing fresh `last_heartbeat_str` updates to `origin/master:state/bot_status.json`.

Keep your final report concise (summary of changes, short diffs, file paths, and verification results).
