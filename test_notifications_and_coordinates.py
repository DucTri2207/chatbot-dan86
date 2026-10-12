# -*- coding: utf-8 -*-
"""
Bộ kiểm thử tự động (Unit Tests) cho:
1. Facebook Notifications Scanner (parse_notification_text, inspect_notifications_list, process_facebook_notifications_tab).
2. Coordinate-based DOM Engine (get_element_coordinates, physical_mouse_click, click_element_at_physical_coordinates).
3. Coordinate-based Nested Reply Isolation & Fail-safe Guard (locate_nested_reply_box, process_post_comments_by_coordinates).
"""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bot_config import (
    META_NOTIFICATIONS_URL,
    TEST_ONLY_AUTHOR_WHITELIST,
)
from bot.memory_store import BotMemoryStore, normalize_text
from bot.page_bot_engine import (
    click_element_at_physical_coordinates,
    get_element_coordinates,
    locate_nested_reply_box,
    parse_notification_text,
    physical_mouse_click,
    process_facebook_notifications_tab,
    process_post_comments_by_coordinates,
)


def make_coord_mock_locator(
    count_val: int = 1,
    visible_val: bool = True,
    rect_val: dict = None,
    aria_val: str = "",
    placeholder_val: str = "",
    inner_text_val: str = "",
    is_edit_val: bool = True,
):
    loc = MagicMock()
    loc.count = AsyncMock(return_value=count_val)
    loc.is_visible = AsyncMock(return_value=visible_val)
    loc.bounding_box = AsyncMock(return_value=rect_val)
    loc.get_attribute = AsyncMock(
        side_effect=lambda a: aria_val if a == "aria-label" else (placeholder_val if a == "placeholder" else "")
    )
    loc.evaluate = AsyncMock(side_effect=lambda script, *args: rect_val if "getBoundingClientRect" in script else is_edit_val)
    loc.first = loc
    loc.last = loc
    loc.nth = MagicMock(return_value=loc)
    loc.scroll_into_view_if_needed = AsyncMock()
    loc.click = AsyncMock()
    loc.press_sequentially = AsyncMock()
    loc.inner_text = AsyncMock(return_value=inner_text_val)
    return loc


class TestNotificationsParser(unittest.TestCase):
    """Kiểm tra logic phân tích và bóc tách thông báo Facebook Notifications."""

    def test_parse_vietnamese_comment_notification(self):
        text = "Đức Trí đã bình luận về một bài viết của bạn: 'Shop tư vấn giúp mình set này nhé' · 3 phút"
        res = parse_notification_text(text)
        self.assertTrue(res["is_comment_notif"])
        self.assertEqual(res["author_name"], "Đức Trí")
        self.assertEqual(res["comment_snippet"], "Shop tư vấn giúp mình set này nhé")
        self.assertEqual(res["time_str"], "3 phút")
        self.assertFalse(res["is_old"])

    def test_parse_vietnamese_short_time_just_now(self):
        text = "Trí Đức đã bình luận về bài viết của bạn. Vừa xong"
        res = parse_notification_text(text)
        self.assertTrue(res["is_comment_notif"])
        self.assertEqual(res["author_name"], "Trí Đức")
        self.assertEqual(res["time_str"], "Vừa xong")
        self.assertFalse(res["is_old"])

    def test_parse_english_comment_notification(self):
        text = "Duc Tri commented on your post: 'Best gift sets ever!'. 1h ago"
        res = parse_notification_text(text)
        self.assertTrue(res["is_comment_notif"])
        self.assertEqual(res["author_name"], "Duc Tri")
        self.assertEqual(res["comment_snippet"], "Best gift sets ever!")
        self.assertIn("1h", res["time_str"])
        self.assertFalse(res["is_old"])

    def test_parse_reply_notification(self):
        text = "Đức Trí đã phản hồi một bình luận trên bài viết của bạn · 15 giây"
        res = parse_notification_text(text)
        self.assertTrue(res["is_comment_notif"])
        self.assertEqual(res["author_name"], "Đức Trí")
        self.assertFalse(res["is_old"])

    def test_parse_old_notification_rejected(self):
        # Thông báo 2 tuần trước -> Phải nhận diện is_old == True
        text_old_week = "Đức Trí đã bình luận về bài viết của bạn · 2 tuần trước"
        res_week = parse_notification_text(text_old_week)
        self.assertTrue(res_week["is_comment_notif"])
        self.assertTrue(res_week["is_old"])

        # Thông báo 1 tháng trước
        text_old_month = "Đức Trí đã bình luận về bài viết của bạn · 1 tháng trước"
        res_month = parse_notification_text(text_old_month)
        self.assertTrue(res_month["is_old"])

        # Thông báo 5 ngày trước (> 3 ngày)
        text_old_days = "Đức Trí đã bình luận về bài viết của bạn · 5 ngày trước"
        res_days = parse_notification_text(text_old_days)
        self.assertTrue(res_days["is_old"])

    def test_parse_ignores_non_comment_notifications(self):
        # Thông báo thích bài viết
        text_like = "Nguyễn Văn B đã thích bài viết của bạn."
        res_like = parse_notification_text(text_like)
        self.assertFalse(res_like["is_comment_notif"])

        # Thông báo theo dõi trang
        text_follow = "Trần C đã theo dõi trang của bạn."
        res_follow = parse_notification_text(text_follow)
        self.assertFalse(res_follow["is_comment_notif"])

        # Thông báo quảng cáo / hệ thống
        text_ad = "Quảng cáo của bạn đã được phê duyệt."
        res_ad = parse_notification_text(text_ad)
        self.assertFalse(res_ad["is_comment_notif"])

    def test_parse_cleans_system_label_author(self):
        text = "Chỉ báo trạng thái online đã bình luận về bài viết của bạn."
        res = parse_notification_text(text)
        self.assertEqual(res["author_name"], "bạn")

    def test_whitelist_matching_for_notifications(self):
        candidates = [
            ("Đức Trí", True),
            ("Trí Đức", True),
            ("duc tri", True),
            ("TRI DUC", True),
            ("Nguyễn Văn Lạ", False),
            ("Khách Vãng Lai", False),
            ("bạn", False),
        ]
        for name, expected in candidates:
            c_norm = normalize_text(name)
            matches = any(w in c_norm for w in TEST_ONLY_AUTHOR_WHITELIST)
            self.assertEqual(matches, expected, f"Tác giả '{name}' kiểm tra whitelist thất bại!")


class TestCoordinateEngine(unittest.TestCase):
    """Kiểm tra Động cơ Tọa độ DOM F12 Vật lý (Coordinate-based DOM Engine)."""

    def test_get_element_coordinates_evaluates_bounding_client_rect(self):
        async def run_test():
            rect = {"x": 120.0, "y": 340.0, "width": 80.0, "height": 30.0}
            loc = make_coord_mock_locator(rect_val=rect)
            coords = await get_element_coordinates(loc)
            self.assertIsNotNone(coords)
            self.assertEqual(coords["x"], 120.0)
            self.assertEqual(coords["y"], 340.0)
            self.assertEqual(coords["width"], 80.0)
            self.assertEqual(coords["height"], 30.0)
            self.assertEqual(coords["right"], 200.0)
            self.assertEqual(coords["bottom"], 370.0)

        asyncio.run(run_test())

    def test_get_element_coordinates_handles_none_or_empty(self):
        async def run_test():
            self.assertIsNone(await get_element_coordinates(None))

            loc_empty = make_coord_mock_locator(count_val=0, visible_val=False)
            self.assertIsNone(await get_element_coordinates(loc_empty))

        asyncio.run(run_test())

    def test_physical_mouse_click_calls_mouse_click_with_exact_coords(self):
        async def run_test():
            page = MagicMock()
            page.mouse = MagicMock()
            page.mouse.click = AsyncMock()

            success = await physical_mouse_click(page, 250.5, 480.0)
            self.assertTrue(success)
            page.mouse.click.assert_awaited_once_with(250.5, 480.0)

        asyncio.run(run_test())

    def test_click_element_at_physical_coordinates_calculates_center(self):
        async def run_test():
            page = MagicMock()
            page.mouse = MagicMock()
            page.mouse.click = AsyncMock()

            # Phần tử tại x=100, y=200, width=50, height=40 -> Tâm tại cx=125, cy=220
            rect = {"x": 100.0, "y": 200.0, "width": 50.0, "height": 40.0}
            loc = make_coord_mock_locator(rect_val=rect)

            success = await click_element_at_physical_coordinates(page, loc)
            self.assertTrue(success)
            page.mouse.click.assert_awaited_once_with(125.0, 220.0)

        asyncio.run(run_test())


class TestCoordinateNestedReplyIsolation(unittest.TestCase):
    """Kiểm tra ràng buộc hình học lọc ô nested reply và Fail-safe Guard."""

    def test_locate_nested_reply_box_enforces_y_constraint(self):
        async def run_test():
            # Comment article tại y=200, height=100 -> comment_bottom = 300
            target_art = make_coord_mock_locator(
                rect_val={"x": 350.0, "y": 200.0, "width": 600.0, "height": 100.0}
            )

            # 1. Textbox hợp lệ nằm ngay dưới comment (y=260 <= 300 + 250 = 550)
            valid_nested = make_coord_mock_locator(
                rect_val={"x": 380.0, "y": 260.0, "width": 500.0, "height": 38.0},
                aria_val="Viết câu trả lời...",
            )
            target_art.locator = MagicMock(return_value=valid_nested)

            page = MagicMock()
            page.locator = MagicMock(return_value=make_coord_mock_locator(count_val=0, visible_val=False))

            res_valid = await locate_nested_reply_box(page, target_art, timeout_seconds=0.1)
            self.assertEqual(res_valid, valid_nested)

            # 2. Textbox quá xa (> 250px dưới đáy comment, y=600 > 550) -> BỊ LOẠI
            distant_box = make_coord_mock_locator(
                rect_val={"x": 380.0, "y": 600.0, "width": 500.0, "height": 38.0},
                aria_val="Viết câu trả lời...",
            )
            target_art.locator = MagicMock(return_value=distant_box)
            res_distant = await locate_nested_reply_box(page, target_art, timeout_seconds=0.1)
            self.assertIsNone(res_distant)

            # 3. Ô bình luận bài viết cấp 1 ở đáy trang (y=850, aria='Viết bình luận công khai...') -> BỊ LOẠI
            post_level = make_coord_mock_locator(
                rect_val={"x": 350.0, "y": 850.0, "width": 600.0, "height": 45.0},
                aria_val="Viết bình luận công khai...",
            )
            target_art.locator = MagicMock(return_value=post_level)
            res_post_level = await locate_nested_reply_box(page, target_art, timeout_seconds=0.1)
            self.assertIsNone(res_post_level)

        asyncio.run(run_test())


class TestNotificationsTabWorkflow(unittest.TestCase):
    """Kiểm tra quy trình quét thông báo Facebook Notifications end-to-end."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mem_path = os.path.join(self.temp_dir.name, "test_notif_memory.json")
        self.memory = BotMemoryStore(memory_path=self.mem_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_notifications_scanner_processes_whitelisted_author_and_replies(self):
        async def run_test():
            page = MagicMock()
            page.url = META_NOTIFICATIONS_URL
            page.goto = AsyncMock()
            page.keyboard = MagicMock()
            page.keyboard.press = AsyncMock()
            page.mouse = MagicMock()
            page.mouse.click = AsyncMock()

            # Mock danh sách thông báo trả về từ JS inspect_notifications_list
            notifs = [
                {
                    "index": 0,
                    "text": "Đức Trí đã bình luận về một bài viết của bạn: 'Báo giá em set này với' · 2 phút",
                    "coords": {"x": 300.0, "y": 150.0, "width": 500.0, "height": 60.0},
                }
            ]

            with patch("bot.page_bot_engine.verify_logged_in", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.dismiss_blocking_modals", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.inspect_notifications_list", new_callable=AsyncMock, return_value=notifs), \
                 patch("bot.page_bot_engine.process_post_comments_by_coordinates", new_callable=AsyncMock, return_value=1) as mock_post_proc, \
                 patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock):

                replied = await process_facebook_notifications_tab(page, self.memory, dry_run=False)

                # Khẳng định 1: Bot xử lý thành công 1 thông báo
                self.assertEqual(replied, 1)

                # Khẳng định 2: Click vật lý vào tọa độ thông báo (cx = 300 + 250 = 550, cy = 150 + 30 = 180)
                page.mouse.click.assert_awaited_with(550.0, 180.0)

                # Khẳng định 3: Gọi process_post_comments_by_coordinates với target_author_filter="Đức Trí"
                mock_post_proc.assert_awaited_once()
                self.assertEqual(mock_post_proc.call_args[1]["target_author_filter"], "Đức Trí")

        asyncio.run(run_test())

    def test_notifications_scanner_ignores_non_whitelisted_author(self):
        async def run_test():
            page = MagicMock()
            page.url = META_NOTIFICATIONS_URL
            page.goto = AsyncMock()
            page.mouse = MagicMock()
            page.mouse.click = AsyncMock()

            notifs = [
                {
                    "index": 0,
                    "text": "Nguyễn Văn Lạ đã bình luận về bài viết của bạn · 2 phút",
                    "coords": {"x": 300.0, "y": 150.0, "width": 500.0, "height": 60.0},
                }
            ]

            with patch("bot.page_bot_engine.verify_logged_in", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.dismiss_blocking_modals", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.inspect_notifications_list", new_callable=AsyncMock, return_value=notifs), \
                 patch("bot.page_bot_engine.process_post_comments_by_coordinates", new_callable=AsyncMock, return_value=0) as mock_post_proc, \
                 patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock):

                replied = await process_facebook_notifications_tab(page, self.memory, dry_run=False)

                # Người lạ ngoài Whitelist bị bỏ qua 100% -> không click và không xử lý
                self.assertEqual(replied, 0)
                self.assertEqual(page.mouse.click.call_count, 0)
                mock_post_proc.assert_not_awaited()

        asyncio.run(run_test())

    def test_notifications_scanner_ignores_already_replied_comment(self):
        async def run_test():
            page = MagicMock()
            page.url = META_NOTIFICATIONS_URL
            page.goto = AsyncMock()
            page.mouse = MagicMock()
            page.mouse.click = AsyncMock()

            # Ghi nhận bình luận này đã được xử lý trong memory
            self.memory.mark_comment_replied(
                comment_key="cmt:test_post:0:12345",
                author_name="Đức Trí",
                comment_text="Báo giá em set này với",
                public_reply="DAN86 cảm ơn bạn!",
                private_inbox_sent=True,
                private_reply_text="DAN86 xin gửi báo giá...",
            )

            notifs = [
                {
                    "index": 0,
                    "text": "Đức Trí đã bình luận về một bài viết của bạn: 'Báo giá em set này với' · 2 phút",
                    "coords": {"x": 300.0, "y": 150.0, "width": 500.0, "height": 60.0},
                }
            ]

            with patch("bot.page_bot_engine.verify_logged_in", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.dismiss_blocking_modals", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.inspect_notifications_list", new_callable=AsyncMock, return_value=notifs), \
                 patch("bot.page_bot_engine.process_post_comments_by_coordinates", new_callable=AsyncMock) as mock_post_proc, \
                 patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock):

                replied = await process_facebook_notifications_tab(page, self.memory, dry_run=False)

                # Đã được rep hoàn tất -> Bỏ qua, không gọi post processor
                self.assertEqual(replied, 0)
                mock_post_proc.assert_not_awaited()

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
