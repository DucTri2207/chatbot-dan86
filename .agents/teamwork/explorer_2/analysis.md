# Investigation Report: R1 (Zero Local Execution) & R4 (Session Persistence & VPS Reliability)

**Investigator**: Explorer 2 (`teamwork_preview_explorer`)  
**Workspace**: `d:\chat bot dan 86`  
**Target Milestone**: Investigation Milestone (R1 & R4)  
**Date**: 2026-10-12 (UTC: 2026-10-11T23:44:00Z)  

---

## 1. Executive Summary

- **Local PC Cleanliness (R1)**: Verified **100% Zero local bot execution**. No `2_chay_bot_truc_page.py`, no Playwright `headless_shell.exe`, and no background bot runner threads are running on the local Windows PC. The only active Python process is `dashboard.py` (PID 19252), which operates strictly as a read-only HTTP monitor and state visualizer without any process-spawning capabilities.
- **Active VPS Cloud Operation (R4)**: Verified that GitHub Actions run `#38184826832` (`vps_bot_24_7.yml`) is currently in `in_progress` state on repository `DucTri2207/chatbot-dan86`. It is executing `2_chay_bot_truc_page.py --headless --max-minutes 320` and actively pushing live status updates (cycles #1 through #6) to `origin/master:state/bot_status.json` (latest commit `72ce889`, heartbeat timestamp `2026-10-11 23:43:16`).
- **Scan Loop Latency Tuning**: Current `SCAN_INTERVAL_SECONDS` in `bot/bot_config.py:166` is `(25, 45)`. Live cycle sleep times were measured at 27s to 35s. To strictly guarantee the R4 requirement of `15–30s` latency, `SCAN_INTERVAL_SECONDS` should be tuned to `(15, 30)`.
- **Session Persistence & SSO Preservation**: `state/fb_storage_state.json` and `state/GITHUB_SECRET_VALUE.txt` preserve both 29 cookies (including `c_user`, `xs`, `datr`, `sb`, `fr`) and all origins (specifically `https://business.facebook.com` with 23 localStorage keys and `https://www.facebook.com` with 5 keys). The VPS runner decodes `FB_STORAGE_STATE` directly into Playwright's `storage_state`, preventing redirects to `business/loginpage`.
- **Concurrency & Shift Handoff**: Workflow concurrency group `dan86-fanpage-bot-singleton` with `cancel-in-progress: ${{ github.event_name == 'workflow_dispatch' }}` and Step 6 with `if: ${{ !cancelled() }}` prevents duplicate run storms and ensures clean handoff without `pending` queue deadlocks.

---

## 2. Detailed Technical Investigation

### Task 1: Local Windows Environment & Dashboard Inspection (R1)

#### 1.1 Local Process Inspection
- **Command executed**:
  ```powershell
  Get-Process | Where-Object { $_.ProcessName -match "python|headless_shell|chrome|node" }
  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "2_chay_bot|playwright|headless_shell" }
  ```
- **Observations**:
  - `PID 19252`: `python.exe` running `python dashboard.py` (Started: `10/12/2026 3:38:34 AM`).
  - `PID 11200`: `chrome.exe` displaying `http://localhost:8686`.
  - **Zero** instances of `2_chay_bot_truc_page.py`.
  - **Zero** instances of `headless_shell.exe` or Playwright browser instances.

#### 1.2 `dashboard.py` and `dashboard.html` Architecture
- **File**: `dashboard.py` (lines 1–1937)
  - `DashboardHTTPRequestHandler` (lines 1790–1887) implements:
    - `GET /` and `/index.html`: renders HTML dashboard via `build_rendered_dashboard_html()`.
    - `GET /api/status`: reads local state (`collect_dashboard_data()`) and synchronizes with GitHub Actions API (`fetch_github_live_data()`).
    - `GET /api/logs`: reads latest logs from GitHub status payload and fallback local log file.
    - `GET /api/secret`: returns the Base64 GitHub secret value from `state/GITHUB_SECRET_VALUE.txt`.
    - `GET /api/sync_github` / `POST /api/sync_github`: forces immediate pull of `state/bot_status.json` and `state/bot_memory.json` from `raw.githubusercontent.com`.
    - `POST /api/sync_cookies`: calls `sync_facebook_credentials_from_dan86()` (extracts cookies from Chrome CDP or `d:\dan86\dan86_saved_cookies.json` to local json).
- **Process Spawning Check**:
  - Grep search for `subprocess`, `Popen`, `spawn`, `os.system`, or `asyncio.create_subprocess` in request handlers returned **0 results**.
  - `dashboard.py` imports `subprocess` at line 17, but it is **never called** in `dashboard.py`.
  - There are no endpoints, buttons, or background threads in `dashboard.py` or `dashboard.html` that can start `2_chay_bot_truc_page.py`.
- **How Zero Local Execution is Ensured**:
  - The dashboard operates solely as a telemetry monitor.
  - To prevent accidental local bot starts by users, batch file `2_CHAY_THU_TREN_MAY.bat` exists for manual debug only, while standard operation relies on `4_MO_DASHBOARD.bat` (which only starts `python dashboard.py`).

---

### Task 2: VPS Workflow, Git Synchronization & Reliability (R4)

#### 2.1 Workflow Architecture (`.github/workflows/vps_bot_24_7.yml`)
- **File**: `.github/workflows/vps_bot_24_7.yml` (lines 1–69)
- **Trigger**:
  - `workflow_dispatch` (manual or programmatic trigger).
  - `schedule`: cron `"*/30 * * * *"` (watchdog to ensure bot stays alive).
- **Execution**:
  - Job `truc-page-24-7` runs on `ubuntu-latest` with `timeout-minutes: 350`.
  - Step 4 (lines 40–48): executes `python 2_chay_bot_truc_page.py --headless --max-minutes 320`.
  - 320 minutes (5 hours 20 minutes) matches GitHub Actions job timeout headroom (350 min).

#### 2.2 Continuous Run & Shift Handoff Mechanics
- **Shift Termination**:
  - In `2_chay_bot_truc_page.py:250-258`:
    ```python
    if max_minutes > 0:
        elapsed_min = (time.time() - start_time) / 60.0
        if elapsed_min >= max_minutes:
            logger.info("Đã chạy đủ %.1f / %.1f phút của ca VPS hiện tại. Lưu bộ nhớ và chuyển ca mới...")
            break
    ```
  - When 320 minutes elapse, the loop breaks cleanly, memory is saved, and Python exits with code 0.
- **Handoff Step (Step 6, lines 62–67)**:
  ```yaml
  - name: 6. Tự động gọi Ca VPS tiếp theo nối đuôi 24/24
    if: ${{ !cancelled() }}
    env:
      GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    run: |
      gh workflow run vps_bot_24_7.yml || true
  ```
  - Crucial fix verified (Commit `8667887`): Condition `if: ${{ !cancelled() }}` prevents cancelled runs from spawning duplicate jobs.
- **Singleton Concurrency & Preventing 'Pending' Queues (lines 10–12)**:
  ```yaml
  concurrency:
    group: dan86-fanpage-bot-singleton
    cancel-in-progress: ${{ github.event_name == 'workflow_dispatch' }}
  ```
  - When `gh workflow run` triggers the next shift (`workflow_dispatch`), `cancel-in-progress` evaluates to `true`.
  - If any prior job was lagging or if a user triggers a manual dispatch, the old job is immediately replaced rather than stacking in a `pending` queue deadlock.

#### 2.3 Live State Synchronization & Conflict Prevention
- **In-flight sync during bot execution**:
  - `2_chay_bot_truc_page.py:243`:
    ```python
    if cmt_replied > 0 or inbox_replied > 0 or cycle % 3 == 0:
        sync_state_to_github_if_vps(logger)
    ```
  - In `sync_state_to_github_if_vps` (lines 94–139):
    - Aborts any lingering rebase: `git rebase --abort`.
    - Stages only `state/bot_memory.json` and `state/bot_status.json`.
    - Commits: `git commit -m "chore: sync bot live status [skip ci]"`.
    - Rebases with strategy `-X ours`:
      ```bash
      git pull --rebase -X ours origin master
      ```
    - Pushes to `origin/master`.
- **Shift completion sync** (`.github/workflows/vps_bot_24_7.yml:49-60`):
  ```bash
  git config user.name "dan86-bot"
  git config user.email "bot@dan86.vn"
  git rebase --abort 2>/dev/null || true
  git add state/bot_memory.json state/bot_status.json || true
  if ! git diff --staged --quiet; then
    git commit -m "chore: cap nhat bo nho bot & trang thai VPS [skip ci]" || true
    git pull --rebase -X ours origin master || git rebase --abort || true
    git push origin HEAD:master || true
  fi
  ```
- **Conflict Prevention Analysis**:
  - The runner only touches `state/bot_memory.json` and `state/bot_status.json`.
  - Developer commits typically touch code (`bot/*.py`, `dashboard.py`). Git rebase cleanly merges code changes without conflicts.
  - `-X ours` during rebase and `git rebase --abort` fallback guarantee that the rebase never hangs waiting for interactive user input.

#### 2.4 Loop Interval & Cycle Latency Analysis
- **Current Configuration**:
  - `bot/bot_config.py:166`:
    ```python
    SCAN_INTERVAL_SECONDS = (25, 45) # Khoảng nghỉ giữa mỗi chu kỳ quét (25 - 45 giây)
    ```
- **Observed VPS Cycle Timing** (from commit `72ce889` logs):
  - Cycle 1 sleep: 27s
  - Cycle 2 sleep: 32s
  - Cycle 3 sleep: 27s
  - Cycle 4 sleep: 27s
  - Cycle 5 sleep: 35s
- **Evaluation vs R4**:
  - R4 requires: "minimal latency between cycles (`15–30s`)".
  - While 27s is within 15–30s, the current upper bound (45s) caused sleeps of 32s and 35s.
  - **Proposed Fix**: Set `SCAN_INTERVAL_SECONDS = (15, 30)` in `bot/bot_config.py:166` (or allow override via env `SCAN_INTERVAL_MIN` and `SCAN_INTERVAL_MAX`).

---

### Task 3: Session Persistence & SSO Secret Verification (R4)

#### 3.1 Session Files Inspection
1. **`state/fb_storage_state.json`**:
   - Total size: 11,010 bytes.
   - `cookies`: 29 cookies across `.facebook.com`, `.messenger.com`, `.work.meta.com`.
     - Crucial auth cookies present: `c_user` (`100014512141403`), `xs` (`37%3AGQMRxwnt...`), `datr` (`d4FDaSGww2...`), `sb` (`d4FDaegDw...`), `fr`.
   - `origins`: 2 origin objects:
     - `https://business.facebook.com`: 23 localStorage keys, including `CacheStorageVersion`, `bizInboxRecentPrivateReplies`, `bizInboxRecentCommentReplies`, `Session`, `ps:*` session tokens.
     - `https://www.facebook.com`: 5 localStorage keys.
2. **`state/GITHUB_SECRET_VALUE.txt`**:
   - Total size: 10,904 bytes.
   - Single-line Base64 string.
   - When decoded: Exactly reproduces `fb_storage_state.json`, retaining all 29 cookies and both `origins` (`https://business.facebook.com` and `https://www.facebook.com`).

#### 3.2 Loading Secret into GitHub Actions & Preventing Login Redirects
- **Workflow Step 4** (`.github/workflows/vps_bot_24_7.yml:41-42`):
  ```yaml
  env:
    FB_STORAGE_STATE: ${{ secrets.FB_STORAGE_STATE }}
  ```
- **Engine Recovery** (`bot/page_bot_engine.py:44-96`):
  - `restore_storage_state_from_env()` checks `os.environ.get("FB_STORAGE_STATE")`.
  - Supports both raw JSON and Base64-encoded strings.
  - Decodes and writes directly to `state/fb_storage_state.json`.
- **Browser Context Initialization** (`bot/page_bot_engine.py:143-151`):
  ```python
  browser = await playwright.chromium.launch(headless=headless, args=launch_args)
  context = await browser.new_context(
      storage_state=STORAGE_STATE_FILE,
      viewport={"width": 1440, "height": 900},
      locale="vi-VN",
      user_agent=user_agent,
  )
  ```
  - Playwright natively sets both cookies and origin localStorage.
  - When navigating to `https://business.facebook.com/latest/inbox/facebook` and `/messenger`:
    Meta Business Suite recognizes the active session immediately, **preventing redirect to `business/loginpage`**.
- **SSO Fallback in `verify_logged_in`** (`bot/page_bot_engine.py:215-288`):
  - If a transition bridge screen appears, the bot automatically detects and clicks SSO buttons ("Tiếp tục bằng Facebook", "Tiếp tục dưới tên Đức Trí", "Log in with Facebook").
- **Origins Preservation on State Export**:
  - In `bot/page_bot_engine.py:298-324` and `2_chay_bot_truc_page.py:280-310`:
    When saving updated storage state back to disk, the engine reads existing `origins` and merges them, ensuring that Playwright's `context.storage_state()` never drops the `business.facebook.com` localStorage entries.
  - Verified by unit test `test_10_origins_preservation_and_secret_safety` in `test_bot_logic.py:495-543`.

---

## 3. Proposed Fixes & Hardening Recommendations

### Recommendation 1: Align `SCAN_INTERVAL_SECONDS` with R4 (`15–30s`)
- **File**: `bot/bot_config.py:166`
- **Current**:
  ```python
  SCAN_INTERVAL_SECONDS = (25, 45)          # Khoảng nghỉ giữa mỗi chu kỳ quét (25 - 45 giây)
  ```
- **Proposed**:
  ```python
  SCAN_INTERVAL_SECONDS = (15, 30)          # Khoảng nghỉ giữa mỗi chu kỳ quét theo chuẩn R4 (15 - 30 giây)
  ```
- **Rationale**: Direct compliance with Requirement R4 ("minimal latency between cycles (`15–30s`)").

### Recommendation 2: Live Sync Frequency Optimization
- **File**: `2_chay_bot_truc_page.py:243`
- **Current**:
  ```python
  if cmt_replied > 0 or inbox_replied > 0 or cycle % 3 == 0:
      sync_state_to_github_if_vps(logger)
  ```
- **Proposed**:
  ```python
  # Đồng bộ tức thì nếu có tương tác mới; đồng bộ định kỳ mỗi 2 chu kỳ để Dashboard cập nhật nhanh hơn
  if cmt_replied > 0 or inbox_replied > 0 or cycle % 2 == 0:
      sync_state_to_github_if_vps(logger)
  ```
- **Rationale**: With 15–30s intervals, syncing every 2 cycles ensures heartbeat updates reach GitHub within ~45–60s rather than 3–5 minutes.

### Recommendation 3: Remove Unused `subprocess` import in `dashboard.py`
- **File**: `dashboard.py:17`
- **Current**: `import subprocess`
- **Proposed**: Remove unused import to prevent any ambiguity about whether `dashboard.py` executes subprocesses.
