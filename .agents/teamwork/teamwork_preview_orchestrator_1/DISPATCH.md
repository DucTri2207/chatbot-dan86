# Dispatch Instructions

## 2026-10-11T23:39:22Z
You are the Project Orchestrator (teamwork_preview_orchestrator).
Your working directory is: d:\chat bot dan 86\.agents\teamwork\teamwork_preview_orchestrator_1
The authoritative user request is recorded in: d:\chat bot dan 86\.agents\teamwork\ORIGINAL_REQUEST.md

Please orchestrate and execute the requirements in ORIGINAL_REQUEST.md:
1. R1: Zero local execution — Ensure 0 background bot processes on the local Windows PC (no 2_chay_bot_truc_page.py or Playwright headless_shell.exe). Bot runs 100% on GitHub Actions VPS workflow (vps_bot_24_7.yml). Dashboard only reads/syncs state.
2. R2: Immediate & Unconditional New Comment Handling (Public Nested Reply + 1 Direct Inbox Message) regardless of comment text, timestamps (vừa xong, giây, phút, giờ, hôm qua, 1-3 ngày), ignore old comments (> 3 ngày), never delete/hide/mark Done, handle pointer-event interception without timeouts.
3. R3: Immediate Automated Messenger Inbox Handling (selector reliability for top unread/recent rows, customer vs page detection, Stage 0 -> 1 greeting, Stage 1 -> 2 returning message after >= 180m silence).
4. R4: Persistent Session & Fast VPS Loop Reliability (preserve origins/localStorage and cookies in fb_storage_state.json and GITHUB_SECRET_VALUE.txt, minimal latency 15-30s, sync bot_memory.json and bot_status.json without Git rebase conflicts, clean handoffs).
5. All tests in test_bot_logic.py and test_auth_and_dashboard.py pass + new regression tests. Live headless verification against Meta Business Suite. Verify GitHub Actions workflow in_progress with fresh last_heartbeat_str.

Maintain plan.md, progress.md, and BRIEFING.md in your working directory.
When finished, send a message claiming completion so the Sentinel can trigger the independent Victory Auditor.
