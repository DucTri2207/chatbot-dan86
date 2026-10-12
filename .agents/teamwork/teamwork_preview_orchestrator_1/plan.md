# Plan: Facebook Fanpage Bot Audit, Hardening & Cloud Verification

## Objective
Fully satisfy requirements R1 - R4 in ORIGINAL_REQUEST.md:
1. Zero Local Execution: 0 local bot processes on Windows PC, bot runs 100% on GitHub Actions VPS, Dashboard only syncs state.
2. Unconditional Comment Automation: Public nested reply + 1 private inbox message for all new comments (< 3 days, regardless of text/type), never delete/hide/mark Done, eliminate pointer interception timeouts.
3. Messenger Inbox Automation: Robust selector navigation, customer vs page detection, Stage 0 -> 1 greeting, Stage 1 -> 2 after >= 180 min silence.
4. Persistent Session & VPS Loop Reliability: Preserve localStorage origins + cookies in storage state & secret value, 15-30s cycle latency, zero rebase conflicts, clean handoffs.
5. Full verification: Unit test suites pass with 0 failures, new regression tests pass, live headless MBS verification clean, GitHub Actions workflow in_progress with active heartbeat.

## Phases
1. **Phase 0: Survey & Discovery**
   - Survey 1: Check running local processes (powershell Get-Process for python, headless_shell, node, etc.) and dashboard behavior.
   - Survey 2: Investigate bot logic (comment handling, inbox handling, pointer intercept error points, timestamp parsing, stage transitions).
   - Survey 3: Investigate VPS workflow, git sync scripts, storage state preservation, and GitHub repo status.
2. **Phase 1: Milestone 1 (M1) - Local Process Cleanup & Dashboard Decoupling**
   - Ensure local environment has 0 running bot loops.
   - Verify dashboard.py / dashboard.html does not spawn local bot loops.
3. **Phase 2: Milestone 2 (M2) - Logic & Resilience Hardening**
   - Harden comment processing: unconditional reply + inbox, never delete/hide/mark Done, handle pointer-events interception via scroll/JS click/force click/dispatch events.
   - Harden messenger processing: unread/recent selectors, stage transitions, silence timer calculation.
   - Harden storage state & git sync: ensure origins localStorage + cookies format, rebase conflict avoidance in VPS loop.
4. **Phase 3: Milestone 3 (M3) - Test Automation & Regression Suite**
   - Run existing unit tests (test_bot_logic.py, test_auth_and_dashboard.py).
   - Write and run new regression tests for pointer-intercept resilience, needs_inbox_only comment handling, messenger thread detection.
5. **Phase 4: Milestone 4 (M4) - VPS Deployment & Live MBS Verification**
   - Verify GitHub Actions workflow status on DucTri2207/chatbot-dan86.
   - Live headless MBS verification.
6. **Phase 5: Audit & Delivery**
   - Independent verification & auditor gate.
   - Sentinel notification.
