# Adversarial Challenge Report — Challenger 1

## Challenge Summary

**Overall risk assessment**: HIGH (due to line 1307 bug dropping fresh customer inquiry comments containing "1 năm" / "1 tháng")

The core functions `safe_click`, `is_old_comment_timestamp`, and `clean_comment_text` are unit-level sound and robust against synthetic pointer events and adversarial Vietnamese strings. However, empirical stress-testing revealed a critical integration bug at line 1307 of `bot/page_bot_engine.py` where passing `cand.get("innerPreview")` into `is_old_comment_timestamp` causes fresh customer inquiries to be falsely rejected as old comments.

---

## Challenges

### [High] Challenge 1: `innerPreview` Pollution in Candidate Loop Drops Fresh Inquiries

- **Assumption challenged**: Calling `is_old_comment_timestamp(cand.get("time_str", ""), cand.get("innerPreview", ""))` safely falls back to comment preview text when timestamp extraction is uncertain.
- **Attack scenario**:
  A customer posts a brand-new comment (timestamp: `"1 giờ trước"`):
  `"Shop ơi tư vấn set quà kỷ niệm 1 năm thành lập công ty với"`
  The DOM article element has `innerText` starting with:
  `"Nguyễn Văn A\n1 giờ trước\nShop ơi tư vấn set quà kỷ niệm 1 năm..."`
  `cand.get("innerPreview")` contains this string.
  When line 1307 evaluates:
  ```python
  if cand.get("is_old_comment") or is_old_comment_timestamp(cand.get("time_str", ""), cand.get("innerPreview", "")):
  ```
  `is_old_comment_timestamp` concatenates `text` and `aria` into `combined`:
  ```python
  combined = f"{text or ''} {aria or ''}".lower()
  if re.search(r'\b\d+\s*(?:tuần|tháng|năm|week|month|year|w|y)s?\b', combined):
      return True
  ```
  Because `"1 năm"` appears in `innerPreview`, `is_old_comment_timestamp` evaluates to `True`.
  The bot logs: `Bình luận cũ từ [Nguyễn Văn A] (Thời gian: '1 giờ trước'). BỎ QUA 100%!`, skips the comment, and **never replies**.
- **Blast radius**: Any new customer comment asking for 1-year/2-year anniversary gifts, 1-month newborn gifts, or delivery within 4 days is permanently dropped and ignored.
- **Mitigation**:
  In `bot/page_bot_engine.py` line 1307, change:
  ```python
  # BEFORE:
  if cand.get("is_old_comment") or is_old_comment_timestamp(cand.get("time_str", ""), cand.get("innerPreview", "")):
  # AFTER:
  if cand.get("is_old_comment") or is_old_comment_timestamp(cand.get("time_str", "")):
  ```
  Never pass raw `innerPreview` (which contains customer comment text) into `is_old_comment_timestamp`.

---

### [Low] Challenge 2: Leading Digits in Customer Questions vs. Timestamp Prefixes

- **Assumption challenged**: `clean_comment_text` differentiates timestamp prefixes from customer inquiries.
- **Attack scenario**:
  A customer asks: `"4 ngày nữa có hàng không shop?"` (starts with a digit and time unit).
  `clean_comment_text` strips `"4 ngày "` and leaves `"nữa có hàng không shop?"`.
  However, for natural questions like:
  `"Mấy ngày có hàng?"`, `"Bao nhiêu giờ ship tới?"`, `"Shop mở cửa tới mấy giờ?"`, `"Có giao hàng trong ngày không?"`
  The leading token is non-numeric, so `clean_comment_text` leaves them 100% intact.
- **Blast radius**: Low. Even if `"4 ngày "` is stripped, the core intent is preserved, and the comment is still replied to.
- **Mitigation**: Robust as designed.

---

## Stress Test Results

| # | Test Scenario | Input / Conditions | Expected Behavior | Actual Behavior | Result |
|---|---|---|---|---|---|
| 1 | `safe_click` Playwright TimeoutError | `locator.click` raises `PlaywrightTimeoutError("Timeout 2500ms exceeded")` | Fallback JS evaluate called with synthetic `MouseEvent('click')` & `el.click()` | Evaluated with `dispatchEvent` and `MouseEvent`, returns `True` | PASS |
| 2 | `safe_click` Pointer Interception | `locator.click` raises `Exception("subtree intercepts pointer events")` | Fallback JS evaluate called | Evaluated, returns `True` | PASS |
| 3 | `safe_click` Scroll Failure | `scroll_into_view_if_needed` raises Exception, click succeeds | Recovers, clicks with `force=True`, returns `True` | Returns `True` without crash | PASS |
| 4 | `safe_click` Catastrophic Failure | Both click and evaluate throw exceptions | Gracefully returns `False` without uncaught exception | Returns `False` | PASS |
| 5 | `safe_click` Position Support | `position={"x": 150, "y": 40}` passed | Click receives position | Click awaited with `position={"x": 150.0, "y": 40.0}` | PASS |
| 6 | Mandatory Timestamps (<= 3 days) | "vừa xong", "1 giây trước", "45s", "5 phút", "23 giờ", "hôm qua", "1 ngày", "2 ngày", "3 ngày" | `is_old_comment_timestamp == False` | All return `False` | PASS |
| 7 | Mandatory Timestamps (> 3 days) | "4 ngày", "1 tuần", "2 tháng", "1 năm", "1w", "2w", "1y" | `is_old_comment_timestamp == True` | All return `True` | PASS |
| 8 | Customer Inquiries | "Mấy ngày có hàng?", "Bao nhiêu giờ ship tới?" | `is_old == False`, `clean_comment_text` unmangled | `is_old == False`, text unchanged | PASS |
| 9 | Timestamp Prefix Stripping | "vừa xong Cho em xin giá", "1 giây trước Cho em xin giá", "45s Cho em xin giá", "5 phút...", "23 giờ...", "hôm qua...", "1-4 ngày...", "1 tuần...", "2 tháng...", "1 năm...", "1w...", "2w...", "1y..." | Prefix stripped, payload `"Cho em xin giá"` preserved | Exactly `"Cho em xin giá"` returned | PASS |
| 10 | **Vulnerability Repro: innerPreview Pollution** | `time_str="1 giờ trước"`, `innerPreview="Nguyễn Văn A\n1 giờ trước\nShop ơi tư vấn set quà kỷ niệm 1 năm thành lập công ty với"` | Comment must NOT be dropped | Evaluates to `True` (BUG CONFIRMED: falsely marked old) | **FAIL (BUG REPRODUCED)** |

---

## Unchallenged Areas

- Live browser DOM rendering under production Facebook network throttling (covered by Explorer/Auditor in M4 live verification).
