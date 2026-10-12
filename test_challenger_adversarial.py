# -*- coding: utf-8 -*-
"""
Adversarial Stress Test Suite - Challenger 1
Focus Areas:
1. safe_click under failure conditions (mocking TimeoutError & interception, checking fallback JS)
2. is_old_comment_timestamp on Vietnamese timestamps & adversarial customer questions
3. clean_comment_text preservation of customer questions and timestamp stripping
4. Edge-case vulnerability detection: innerPreview pollution in candidate filtering
"""

import asyncio
import re
import unittest
from unittest.mock import AsyncMock, patch

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from bot.page_bot_engine import (
    clean_comment_text,
    is_old_comment_timestamp,
    safe_click,
)


class TestAdversarialSafeClick(unittest.TestCase):
    """Stress-testing safe_click under simulated DOM and Playwright failures."""

    def test_safe_click_timeout_error_invokes_js_fallback(self) -> None:
        """Playwright TimeoutError triggers evaluate with synthetic MouseEvent fallback."""
        mock_locator = AsyncMock()
        mock_locator.scroll_into_view_if_needed = AsyncMock()
        mock_locator.click = AsyncMock(
            side_effect=PlaywrightTimeoutError("Locator.click: Timeout 2500ms exceeded")
        )
        mock_locator.evaluate = AsyncMock(return_value=None)

        result = asyncio.run(safe_click(mock_locator, timeout=2500))

        self.assertTrue(result, "safe_click should return True when JS evaluate fallback succeeds")
        mock_locator.scroll_into_view_if_needed.assert_awaited_once_with(timeout=1500)
        mock_locator.click.assert_awaited_once_with(timeout=2500, force=True)
        mock_locator.evaluate.assert_awaited_once()

        js_script = mock_locator.evaluate.call_args[0][0]
        self.assertIn("dispatchEvent", js_script)
        self.assertIn("MouseEvent", js_script)
        self.assertIn("bubbles: true", js_script)
        self.assertIn("cancelable: true", js_script)
        self.assertIn("view: window", js_script)
        self.assertIn("el.click()", js_script)

    def test_safe_click_pointer_interception_error_invokes_fallback(self) -> None:
        """Pointer event interception error triggers evaluate fallback."""
        mock_locator = AsyncMock()
        mock_locator.scroll_into_view_if_needed = AsyncMock()
        mock_locator.click = AsyncMock(
            side_effect=Exception(
                "Locator.click: Timeout 2500ms exceeded. <div class='blocking'> intercepts pointer events"
            )
        )
        mock_locator.evaluate = AsyncMock(return_value=None)

        result = asyncio.run(safe_click(mock_locator, timeout=2500))

        self.assertTrue(result)
        mock_locator.evaluate.assert_awaited_once()

    def test_safe_click_scroll_fails_but_click_succeeds(self) -> None:
        """If scrolling fails (element hidden/detached), click is still attempted and succeeds."""
        mock_locator = AsyncMock()
        mock_locator.scroll_into_view_if_needed = AsyncMock(
            side_effect=Exception("Element cannot be scrolled")
        )
        mock_locator.click = AsyncMock(return_value=None)
        mock_locator.evaluate = AsyncMock()

        result = asyncio.run(safe_click(mock_locator, timeout=2500))

        self.assertTrue(result)
        mock_locator.click.assert_awaited_once_with(timeout=2500, force=True)
        mock_locator.evaluate.assert_not_called()

    def test_safe_click_position_parameter_forwarded(self) -> None:
        """Ensure position coordinate parameter is properly forwarded to locator.click."""
        mock_locator = AsyncMock()
        mock_locator.scroll_into_view_if_needed = AsyncMock()
        mock_locator.click = AsyncMock(return_value=None)

        pos = {"x": 150.0, "y": 40.0}
        result = asyncio.run(safe_click(mock_locator, timeout=3000, position=pos))

        self.assertTrue(result)
        mock_locator.click.assert_awaited_once_with(timeout=3000, force=True, position=pos)

    def test_safe_click_catastrophic_failure_returns_false_safely(self) -> None:
        """When both Playwright click and JS evaluate fail, safe_click returns False without crashing."""
        mock_locator = AsyncMock()
        mock_locator.scroll_into_view_if_needed = AsyncMock(side_effect=Exception("Detached"))
        mock_locator.click = AsyncMock(side_effect=PlaywrightTimeoutError("Click timeout"))
        mock_locator.evaluate = AsyncMock(side_effect=Exception("Evaluate context destroyed"))

        result = asyncio.run(safe_click(mock_locator, timeout=2000))
        self.assertFalse(result, "Catastrophic failure must return False gracefully")


class TestAdversarialTimestampsAndCleaning(unittest.TestCase):
    """Stress-testing timestamp parsing and comment text cleaning against Vietnamese adversarial inputs."""

    def test_mandatory_adversarial_timestamp_samples(self) -> None:
        """Verify all mandatory adversarial strings from dispatch instructions:
        - <= 3 days are NOT marked old (is_old == False)
        - > 3 days ARE marked old (is_old == True)
        """
        cases = [
            # Sample string, Expected is_old
            ("vừa xong", False),
            ("1 giây trước", False),
            ("45s", False),
            ("5 phút", False),
            ("23 giờ", False),
            ("hôm qua", False),
            ("1 ngày", False),
            ("2 ngày", False),
            ("3 ngày", False),
            ("4 ngày", True),
            ("1 tuần", True),
            ("2 tháng", True),
            ("1 năm", True),
            ("Mấy ngày có hàng?", False),
            ("Bao nhiêu giờ ship tới?", False),
            ("1w", True),
            ("2w", True),
            ("1y", True),
        ]
        for text, expected in cases:
            with self.subTest(text=text, expected=expected):
                actual = is_old_comment_timestamp(text)
                self.assertEqual(
                    actual,
                    expected,
                    f"Timestamp '{text}' expected is_old={expected}, but got {actual}",
                )

    def test_adversarial_extended_boundaries(self) -> None:
        """Extended stress boundaries: seconds, minutes, hours, abbreviations, mixed case."""
        new_samples = [
            "1s", "30s", "59s", "10 giây", "59 giây trước", "45 secs ago",
            "1m", "5m", "15 phút", "59 phút", "30m ago",
            "1h", "12h", "23h", "1 giờ", "23 giờ trước",
            "hôm qua", "yesterday", "hôm qua lúc 18:30",
            "1 ngày trước", "2 ngày trước", "3 ngày trước",
            "1d", "2d", "3d", "1 day ago", "3 days",
            "VỪA XONG", "1 GIÂY TRƯỚC", "5 PHÚT", "23 GIỜ", "HÔM QUA", "3 NGÀY",
        ]
        for ts in new_samples:
            self.assertFalse(
                is_old_comment_timestamp(ts),
                f"Fresh timestamp '{ts}' should NOT be marked old",
            )

        old_samples = [
            "4 ngày", "5 ngày", "7 ngày", "10 ngày", "30 ngày", "365 ngày",
            "4 ngày trước", "10 ngày trước", "4d", "7d", "30d",
            "4 days", "10 days ago",
            "1 tuần", "2 tuần", "3 tuần", "4 tuần", "10 tuần",
            "1 tuần trước", "3 tuần trước", "1w", "2w", "4w", "52w",
            "1 tháng", "2 tháng", "6 tháng", "12 tháng",
            "1 tháng trước", "1 month ago", "6 months",
            "1 năm", "2 năm", "5 năm", "10 năm",
            "1 năm trước", "2 năm trước", "1y", "2y", "5y",
            "4 NGÀY", "1 TUẦN", "2 THÁNG", "1 NĂM", "1W", "1Y",
        ]
        for ts in old_samples:
            self.assertTrue(
                is_old_comment_timestamp(ts),
                f"Old timestamp '{ts}' MUST be marked old",
            )

    def test_customer_questions_not_mangled_by_clean_comment_text(self) -> None:
        """Verify customer questions containing time words are NEVER mangled by clean_comment_text."""
        questions = [
            "Mấy ngày có hàng?",
            "Bao nhiêu giờ ship tới?",
            "Shop mở cửa tới mấy giờ?",
            "Có giao hàng trong ngày không?",
            "Chờ 5 phút rồi chưa thấy shop rep",
            "Shop ơi mấy ngày nữa có hàng vậy?",
            "Có ship nhanh trong 1 giờ được không?",
        ]
        for q in questions:
            cleaned = clean_comment_text(q)
            self.assertEqual(
                cleaned,
                q,
                f"Customer question '{q}' was mangled into '{cleaned}'",
            )

    def test_timestamp_prefixes_cleaned_from_comment_text(self) -> None:
        """Verify leading timestamp noise is stripped while actual comment content is preserved."""
        cases = [
            ("vừa xong Cho em xin giá", "Cho em xin giá"),
            ("1 giây trước Cho em xin giá", "Cho em xin giá"),
            ("45s Cho em xin giá", "Cho em xin giá"),
            ("5 phút Cho em xin giá", "Cho em xin giá"),
            ("23 giờ Cho em xin giá", "Cho em xin giá"),
            ("hôm qua Cho em xin giá", "Cho em xin giá"),
            ("1 ngày Cho em xin giá", "Cho em xin giá"),
            ("2 ngày Cho em xin giá", "Cho em xin giá"),
            ("3 ngày Cho em xin giá", "Cho em xin giá"),
            ("4 ngày Cho em xin giá", "Cho em xin giá"),
            ("1 tuần Cho em xin giá", "Cho em xin giá"),
            ("2 tháng Cho em xin giá", "Cho em xin giá"),
            ("1 năm Cho em xin giá", "Cho em xin giá"),
            ("1w Cho em xin giá", "Cho em xin giá"),
            ("2w Cho em xin giá", "Cho em xin giá"),
            ("1y Cho em xin giá", "Cho em xin giá"),
        ]
        for raw, expected in cases:
            cleaned = clean_comment_text(raw)
            self.assertEqual(
                cleaned,
                expected,
                f"Raw '{raw}' expected '{expected}', but got '{cleaned}'",
            )


class TestAdversarialVulnerabilityDiscovery(unittest.TestCase):
    """Deep adversarial inquiry: surface architectural bugs and failure modes."""

    def test_vulnerability_innerpreview_pollution_rejects_fresh_customer_comments(self) -> None:
        """
        VULNERABILITY REPRODUCTION:
        In bot/page_bot_engine.py line 1307:
            if cand.get("is_old_comment") or is_old_comment_timestamp(cand.get("time_str", ""), cand.get("innerPreview", "")):

        When a customer posts a FRESH comment ('1 giờ trước'):
            'Shop ơi tư vấn set quà kỷ niệm 1 năm ngày cưới giúp mình với'
        The innerPreview string contains '1 năm'.
        Passing innerPreview as the 2nd argument (aria) causes is_old_comment_timestamp
        to evaluate to True, erroneously dropping the customer's fresh comment!
        """
        fresh_time_str = "1 giờ trước"
        customer_comment = "Shop ơi tư vấn set quà kỷ niệm 1 năm ngày cưới giúp mình với"
        inner_preview = f"Nguyễn Thị Hoa\n{fresh_time_str}\n{customer_comment}"

        # 1. When checked solely with time_str (correct behavior):
        is_old_pure = is_old_comment_timestamp(fresh_time_str)
        self.assertFalse(
            is_old_pure,
            "1 giờ trước is a fresh comment and must NOT be marked old!",
        )

        # 2. When passed innerPreview (current line 1307 behavior):
        is_old_polluted = is_old_comment_timestamp(fresh_time_str, inner_preview)
        # EMPIRICAL PROOF: This evaluates to True because '1 năm' matches the regex inside innerPreview!
        self.assertTrue(
            is_old_polluted,
            "Confirmed: line 1307 bug reproduces! innerPreview pollutes is_old_comment_timestamp.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
