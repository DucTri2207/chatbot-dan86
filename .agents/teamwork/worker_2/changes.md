# Changes Summary — Worker 2

## 1. Overview
Fixed the false positive vulnerability reported by Challenger 1 where comment preview text (`cand.get("innerPreview")`) was passed into `is_old_comment_timestamp`, causing fresh comments mentioning time units like "1 năm" (e.g., anniversary gift consultations) to be falsely dropped as old comments.

## 2. File Modifications

### A. `bot/page_bot_engine.py` (Line 1307)
- **Problem**:
  ```python
  if cand.get("is_old_comment") or is_old_comment_timestamp(cand.get("time_str", ""), cand.get("innerPreview", "")):
  ```
  `innerPreview` contains customer comment text (e.g. `"Nguyễn Văn A\n1 giờ trước\nShop ơi tư vấn set quà kỷ niệm 1 năm thành lập công ty với"`). Because `is_old_comment_timestamp(text, aria)` concatenates both arguments and runs regex matching for `\b\d+\s*(?:tuần|tháng|năm|...)\b`, having `"1 năm"` in the comment body triggers the old timestamp regex, erroneously dropping fresh comments.
- **Fix**:
  ```python
  if cand.get("is_old_comment") or is_old_comment_timestamp(cand.get("time_str", "")):
  ```
  Only the dedicated timestamp string `time_str` extracted from the timestamp DOM node is evaluated by `is_old_comment_timestamp`.

### B. `test_hardening_regression.py`
- Added regression test `test_fresh_comment_with_year_in_body_not_dropped`:
  ```python
  def test_fresh_comment_with_year_in_body_not_dropped(self) -> None:
      cand = {
          "author_name": "Nguyễn Văn A",
          "comment_text": "Shop ơi tư vấn set quà kỷ niệm 1 năm thành lập công ty với",
          "time_str": "1 giờ trước",
          "innerPreview": "Nguyễn Văn A\n1 giờ trước\nShop ơi tư vấn set quà kỷ niệm 1 năm thành lập công ty với",
          "is_old_comment": False,
          "has_page_reply": False,
          "dom_index": 0,
      }
      is_old = is_old_comment_timestamp(cand.get("time_str", ""))
      self.assertFalse(is_old)
      is_skipped = cand.get("is_old_comment") or is_old_comment_timestamp(cand.get("time_str", ""))
      self.assertFalse(is_skipped)
      should_reply, comment_key = self.memory.should_reply_comment(
          author_name=cand["author_name"],
          comment_text=cand["comment_text"],
          has_page_reply_in_dom=cand["has_page_reply"],
          post_id="post_test_year_in_body",
          dom_index=cand["dom_index"],
      )
      self.assertTrue(should_reply)
      self.assertIsNotNone(comment_key)
  ```

## 3. Verification Commands & Results
- `python -m unittest discover -s . -p "test_*.py" -v`: 38 tests ran, 38 passed (0 errors, 0 failures).
- `python test_challenger_adversarial.py -v`: 10 tests ran, 10 passed (0 errors, 0 failures).
- `python -m py_compile bot/page_bot_engine.py test_hardening_regression.py`: Clean compilation, no syntax errors.
