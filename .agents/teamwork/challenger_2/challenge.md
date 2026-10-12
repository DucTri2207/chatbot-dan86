# Empirical Adversarial Challenge Report: System & Environment Verification

## Challenge Summary

**Overall risk assessment**: LOW  
**Verdict**: **APPROVE**

All three verification targets mandated in the dispatch instructions were empirically evaluated with zero reliance on worker claims:
1. **Local PC Cleanliness (R1)**: 0 background bot processes (`2_chay_bot_truc_page.py`), 0 Playwright browser processes (`headless_shell.exe`). The only active Python process on the host is PID 19252 (`dashboard.py`), which contains 0 subprocess invocations and functions strictly as a lightweight local web monitor.
2. **VPS Cloud Runner (R4)**: Workflow run `38184826832` (`vps_bot_24_7.yml`) on `DucTri2207/chatbot-dan86` is confirmed `in_progress` (uptime 24m+), continuously running scan cycles every ~30–45s and periodically syncing heartbeat updates to `origin/master:state/bot_status.json` (latest commit `daec122`, cycle #15, heartbeat `2026-10-11 23:56:03`).
3. **Memory Store & `needs_inbox_only` Logic (R2 & R3)**: Verified via dedicated empirical test harness (`scripts/test_empirical_challenger2_harness.py`). Records with `private_inbox_sent: False` are targeted for inbox-only dispatch (`needs_inbox_only = True`), records with `private_inbox_sent: True` and existing public reply are skipped, and the 180-minute silence boundary is strictly enforced.

---

## Challenges & Adversarial Stress Tests

### [Low] Challenge 1: Local Host Process Leakage & Subprocess Spawning
- **Assumption challenged**: That the local environment is completely free of background bot runners and that `dashboard.py` (PID 19252) cannot accidentally launch headless bot instances.
- **Attack scenario**: `dashboard.py` could spawn background threads or child subprocesses that invoke Playwright or `2_chay_bot_truc_page.py`.
- **Empirical test**:
  - Queried CIM Win32 process table:
    ```powershell
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*2_chay_bot_truc_page.py*" }
    Get-Process -Name "headless_shell*"
    Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -eq 19252 }
    Get-CimInstance Win32_Process | Where-Object { $_.Name -like "*python*" }
    ```
  - Result: Only 1 Python process exists on the entire host: PID 19252 (`python dashboard.py`).
  - Audited `dashboard.py` AST and imports: 0 `subprocess`, 0 `multiprocessing`, 0 `playwright` imports.
  - Queried `http://localhost:8686/api/status`: Returns HTTP 200, reports `bot_status mode: VPS GitHub (Ca #15)`, reads status remotely without spawning local jobs.
- **Blast radius**: None observed.
- **Status**: PASSED.

---

### [Low] Challenge 2: VPS Workflow Liveness, Deadlocks, & Queue Jams
- **Assumption challenged**: That GitHub Actions workflow `vps_bot_24_7.yml` is active, healthy, and not deadlocked in `pending` or timed out.
- **Attack scenario**: Workflow could get trapped in a Playwright pointer interception timeout loop or git merge conflict, failing to update heartbeats.
- **Empirical test**:
  - Run inspection:
    ```powershell
    gh run list --repo DucTri2207/chatbot-dan86 --limit 5
    ```
    Output: Active run `38184826832` status `in_progress` (elapsed time: 24m13s, started 2026-10-11T23:35:03Z).
  - Git commit inspection on `origin/master`:
    ```powershell
    git log -n 3 --oneline origin/master
    git show origin/master:state/bot_status.json
    ```
    Commits from `dan86-bot <bot@dan86.vn>`:
    - `5d9b36c` (23:47:17Z)
    - `a5fd979` (23:51:23Z)
    - `daec122` (23:56:03Z) — cycle #15 complete, `running: True`, `last_heartbeat_str: 2026-10-11 23:56:03`.
  - Scan loop interval: 31s–45s between scan cycles.
- **Blast radius**: None.
- **Status**: PASSED.

---

### [Low] Challenge 3: Inboxing Retries (`needs_inbox_only`) & Memory State Integrity
- **Assumption challenged**: That comments with public replies in DOM but failed private messages (`private_inbox_sent: False`) are retried for inboxing, while already-inboxed comments (`private_inbox_sent: True`) are never re-sent.
- **Attack scenario**:
  - Candidate evaluation could mistakenly skip comments whose public reply was already posted even if inbox sending failed.
  - Candidate evaluation could re-inbox users repeatedly if `needs_inbox_only` does not verify `private_inbox_sent: True`.
  - Corrupted JSON or boundary conditions could cause runtime exceptions in `BotMemoryStore`.
- **Empirical test** (`scripts/test_empirical_challenger2_harness.py`):
  1. `cand1` (DOM no reply, memory none): `FULL_REPLY` (`needs_inbox_only = False`) -> PASS.
  2. `cand2` (DOM has reply, memory `private_inbox_sent = False`): `INBOX_ONLY` (`needs_inbox_only = True`) -> PASS.
  3. `cand3` (DOM has reply, memory `private_inbox_sent = True`): `SKIP` -> PASS.
  4. `cand4` (DOM has reply, memory record absent): `INBOX_ONLY` (`needs_inbox_only = True`) -> PASS.
  5. `cand5` (System label "Chỉ báo trạng thái online"): `SKIP`, returns empty key `""` -> PASS.
  6. Boundary test on 180-minute silence rule:
     - At $t_0 + 10799\text{s}$ (179m 59s): returns `NONE` (silence preserved) -> PASS.
     - At $t_0 + 10800\text{s}$ (180m 00s): returns `WAIT_STAFF_REPLY` -> PASS.
     - Subsequent message within 60s: returns `NONE` -> PASS.
  7. Corrupted JSON file recovery: `BotMemoryStore` handles malformed JSON without raising unhandled exceptions -> PASS.
  8. Extreme inputs (single character `.`, stickers, emojis, trailing spaces): accepted without false rejections -> PASS.
- **Blast radius**: None.
- **Status**: PASSED.

---

## Stress Test Results

| Scenario | Expected Behavior | Actual Behavior | Result |
|---|---|---|---|
| Local Host Bot Process Audit | 0 `2_chay_bot_truc_page.py`, 0 `headless_shell.exe` | 0 found; only PID 19252 (`dashboard.py`) | PASS |
| Dashboard Port 8686 API Query | Return valid JSON status, 0 subprocesses | HTTP 200, status `VPS GitHub (Ca #15)` | PASS |
| GitHub Actions VPS Runner Liveness | Run `38184826832` `in_progress` | Run `38184826832` `in_progress` (24m+) | PASS |
| GitHub Actions Sync Heartbeat | Fresh commits with `last_heartbeat_str` | Commit `daec122` (cycle 15, 23:56:03) | PASS |
| Unit Test Suite Discovery | 27/27 unit tests pass | 27 passed in 0.424s | PASS |
| `needs_inbox_only` targeting | Target `private_inbox_sent: False`, skip `True` | Verified in harness | PASS |
| 180m Silence Boundary (10799s vs 10800s) | Silent at 10799s, trigger at 10800s | Verified in harness | PASS |
| Corrupted Memory File Recovery | Graceful fallback to default dicts | Verified in harness | PASS |

---

## Unchallenged Areas

- **Live Facebook Meta Business Suite Network Outages**: Real Meta server 500/503 HTTP errors or captcha challenges cannot be synthetically forced on the live Facebook production account without risking account restrictions. These paths are covered via Playwright exception mock tests in `test_hardening_regression.py`.
