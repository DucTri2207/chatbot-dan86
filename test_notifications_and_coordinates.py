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
    inspect_comment_panel,
    inspect_notifications_list,
    locate_nested_reply_box,
    parse_notification_text,
    physical_mouse_click,
    process_facebook_notifications_tab,
    process_post_comments_by_coordinates,
    send_private_inbox_to_commenter,
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
        sample_whitelist = ["đức trí", "duc tri", "trí đức", "tri duc"]
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
            matches = any(w in c_norm for w in sample_whitelist)
            self.assertEqual(matches, expected, f"Tác giả '{name}' kiểm tra whitelist thất bại!")

    def test_parse_da_tra_loi_notification(self):
        text = "Đức Trí đã trả lời một bình luận: 'Báo giá em với' · 2 phút"
        res = parse_notification_text(text)
        self.assertTrue(res["is_comment_notif"])
        self.assertEqual(res["author_name"], "Đức Trí")
        self.assertEqual(res["comment_snippet"], "Báo giá em với")
        self.assertEqual(res["time_str"], "2 phút")
        self.assertFalse(res["is_old"])

        text2 = "Trí Đức đã trả lời bình luận của bạn · 10 giây"
        res2 = parse_notification_text(text2)
        self.assertTrue(res2["is_comment_notif"])
        self.assertEqual(res2["author_name"], "Trí Đức")

    def test_parse_da_nhac_den_notification(self):
        text = "Đức Trí đã nhắc đến bạn trong một bình luận: 'Shop tư vấn giúp mình' · 1 phút"
        res = parse_notification_text(text)
        self.assertTrue(res["is_comment_notif"])
        self.assertEqual(res["author_name"], "Đức Trí")
        self.assertEqual(res["comment_snippet"], "Shop tư vấn giúp mình")

        text_en = "Duc Tri mentioned you in a comment: 'Great product' · 5m ago"
        res_en = parse_notification_text(text_en)
        self.assertTrue(res_en["is_comment_notif"])
        self.assertEqual(res_en["author_name"], "Duc Tri")
        self.assertEqual(res_en["comment_snippet"], "Great product")

    def test_parse_grouped_multi_author_notification(self):
        text = "Đức Trí và 1 người khác đã bình luận về bài viết của bạn: 'Báo giá' · 5 phút"
        res = parse_notification_text(text)
        self.assertTrue(res["is_comment_notif"])
        self.assertEqual(res["author_name"], "Đức Trí")

        text_en = "Duc Tri and 2 others commented on your post · 3m"
        res_en = parse_notification_text(text_en)
        self.assertTrue(res_en["is_comment_notif"])
        self.assertEqual(res_en["author_name"], "Duc Tri")

    def test_parse_comment_with_years_in_snippet_not_marked_old(self):
        # Snippet contains '2 years' / '2 năm' but relative time is fresh ('3m' / '5 phút')
        text_en = "Duc Tri commented: 'Warranty 2 years right?' 3m ago"
        res_en = parse_notification_text(text_en)
        self.assertTrue(res_en["is_comment_notif"])
        self.assertEqual(res_en["author_name"], "Duc Tri")
        self.assertEqual(res_en["comment_snippet"], "Warranty 2 years right?")
        self.assertIn("3m", res_en["time_str"])
        self.assertFalse(res_en["is_old"])

        text_vi = "Đức Trí đã bình luận về bài viết của bạn: 'Cái này dùng 1 năm hả shop' · 5 phút"
        res_vi = parse_notification_text(text_vi)
        self.assertTrue(res_vi["is_comment_notif"])
        self.assertEqual(res_vi["author_name"], "Đức Trí")
        self.assertEqual(res_vi["comment_snippet"], "Cái này dùng 1 năm hả shop")
        self.assertEqual(res_vi["time_str"], "5 phút")
        self.assertFalse(res_vi["is_old"])

    def test_parse_da_gan_the_tagged_notification(self):
        text = "Đức Trí đã gắn thẻ bạn trong một bình luận: 'Xem bài này' · 2 phút"
        res = parse_notification_text(text)
        self.assertTrue(res["is_comment_notif"])
        self.assertEqual(res["author_name"], "Đức Trí")
        self.assertEqual(res["comment_snippet"], "Xem bài này")
        self.assertFalse(res["is_old"])

        text_en = "Duc Tri tagged you in a comment: 'Check this out' · 5m"
        res_en = parse_notification_text(text_en)
        self.assertTrue(res_en["is_comment_notif"])
        self.assertEqual(res_en["author_name"], "Duc Tri")
        self.assertEqual(res_en["comment_snippet"], "Check this out")
        self.assertFalse(res_en["is_old"])

    def test_parse_da_them_binh_luan_notification(self):
        text = "Đức Trí đã thêm một bình luận: 'Báo giá em set quà tết' · vừa xong"
        res = parse_notification_text(text)
        self.assertTrue(res["is_comment_notif"])
        self.assertEqual(res["author_name"], "Đức Trí")
        self.assertEqual(res["comment_snippet"], "Báo giá em set quà tết")
        self.assertFalse(res["is_old"])


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

    def test_target_author_filter_enforcement_in_post_comments(self):
        async def run_test():
            page = MagicMock()
            page.url = "https://business.facebook.com/latest/posts/12345"

            # Post info has 2 comments: Comment 0 from 'Khách Khác', Comment 1 from 'Đức Trí'
            panel_info = {
                "post_id": "12345",
                "unreplied_comments": [
                    {
                        "author_name": "Khách Khác",
                        "comment_text": "Bình luận trước",
                        "dom_index": 0,
                        "has_page_reply": False,
                    },
                    {
                        "author_name": "Đức Trí",
                        "comment_text": "Cần tư vấn quà tặng",
                        "dom_index": 1,
                        "has_page_reply": False,
                    },
                ],
            }

            memory = MagicMock()
            memory.is_customer_in_cooldown = MagicMock(return_value=False)
            memory.should_reply_comment = MagicMock(return_value=(True, "cmt:12345:1"))
            memory.prepare_comment_and_inbox_replies = MagicMock(return_value=("Chào Đức Trí", "Inbox Đức Trí"))
            memory.mark_comment_replied = MagicMock()

            with patch("bot.page_bot_engine.ensure_newest_comments_filter", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.expand_all_comment_replies", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.inspect_comment_panel", new_callable=AsyncMock, return_value=panel_info), \
                 patch("bot.page_bot_engine.tag_comment_target_in_dom", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.locate_nested_reply_box", new_callable=AsyncMock, return_value=make_coord_mock_locator(rect_val={"x": 350.0, "y": 250.0, "width": 500.0, "height": 40.0})), \
                 patch("bot.page_bot_engine.type_human_like", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.physical_mouse_click", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.click_element_at_physical_coordinates", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.send_private_inbox_to_commenter", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock):

                page.keyboard = MagicMock()
                page.keyboard.press = AsyncMock()
                page.locator = MagicMock(return_value=make_coord_mock_locator())

                # Target filter specifies 'Đức Trí'
                res = await process_post_comments_by_coordinates(
                    page=page,
                    memory=memory,
                    target_author_filter="Đức Trí",
                    max_comments=1,
                )

                self.assertEqual(res, 1)
                # Verify that Đức Trí was targeted and prepared
                memory.prepare_comment_and_inbox_replies.assert_called_with("Đức Trí")

        asyncio.run(run_test())

    def test_send_private_inbox_uses_physical_mouse_click_fallback(self):
        async def run_test():
            page = MagicMock()
            page.url = "https://business.facebook.com/latest/inbox/facebook"
            page.mouse = MagicMock()
            page.mouse.click = AsyncMock()

            # marked_msg_btn does not exist initially (count=0)
            empty_loc = make_coord_mock_locator(count_val=0, visible_val=False)
            re_marked_loc = make_coord_mock_locator(rect_val={"x": 500.0, "y": 300.0, "width": 80.0, "height": 30.0})

            def locator_side_effect(sel):
                if '[data-dan86-msg-btn="true"]' in sel:
                    return re_marked_loc
                if 'dialog' in sel:
                    return dialog_loc
                return empty_loc

            page.locator = MagicMock(side_effect=locator_side_effect)

            js_ret = {
                "clicked": False,
                "tagged": True,
                "text": "Gửi tin nhắn",
                "coords": {"x": 500.0, "y": 300.0, "width": 80.0, "height": 30.0},
            }
            page.evaluate = AsyncMock(return_value=js_ret)

            # Dialog appears
            dialog_loc = make_coord_mock_locator(rect_val={"x": 400.0, "y": 200.0, "width": 400.0, "height": 300.0})
            textbox_loc = make_coord_mock_locator(aria_val="Tin nhắn...")
            send_btn = make_coord_mock_locator(aria_val="Gửi", rect_val={"x": 750.0, "y": 480.0, "width": 40.0, "height": 30.0})
            dialog_loc.locator = MagicMock(side_effect=lambda s: send_btn if "Gửi" in s else textbox_loc)

            with patch("bot.page_bot_engine.click_element_at_physical_coordinates", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.type_human_like", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.dismiss_blocking_modals", new_callable=AsyncMock):

                sent = await send_private_inbox_to_commenter(
                    page=page,
                    author_name="Đức Trí",
                    private_reply_text="DAN86 xin gửi báo giá...",
                    dom_index=0,
                )
                self.assertTrue(sent)

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

            with patch("bot.page_bot_engine.TEST_ONLY_AUTHOR_WHITELIST", ["đức trí", "duc tri"]), \
                 patch("bot.page_bot_engine.verify_logged_in", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.dismiss_blocking_modals", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.inspect_notifications_list", new_callable=AsyncMock, return_value=notifs), \
                 patch("bot.page_bot_engine.process_post_comments_by_coordinates", new_callable=AsyncMock, return_value=0) as mock_post_proc, \
                 patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock):

                replied = await process_facebook_notifications_tab(page, self.memory, dry_run=False)

                # Người lạ ngoài Whitelist bị bỏ qua 100% khi Whitelist được kích hoạt
                self.assertEqual(replied, 0)
                self.assertEqual(page.mouse.click.call_count, 0)
                mock_post_proc.assert_not_awaited()

        asyncio.run(run_test())

    def test_notifications_scanner_processes_all_authors_when_whitelist_empty(self):
        """Khi TEST_ONLY_AUTHOR_WHITELIST rỗng [] (Production Live), mọi khách hàng đều được bot tiếp nhận."""
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

            with patch("bot.page_bot_engine.TEST_ONLY_AUTHOR_WHITELIST", []), \
                 patch("bot.page_bot_engine.verify_logged_in", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.dismiss_blocking_modals", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.inspect_notifications_list", new_callable=AsyncMock, return_value=notifs), \
                 patch("bot.page_bot_engine.click_element_at_physical_coordinates", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.process_post_comments_by_coordinates", new_callable=AsyncMock, return_value=1) as mock_post_proc, \
                 patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock):

                replied = await process_facebook_notifications_tab(page, self.memory, dry_run=False)

                # Mọi khách hàng đều được xử lý khi Whitelist là []
                self.assertEqual(replied, 1)
                mock_post_proc.assert_awaited_once()

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

    def test_notifications_scanner_handles_new_page_popup(self):
        async def run_test():
            page = MagicMock()
            page.url = META_NOTIFICATIONS_URL
            page.goto = AsyncMock()
            page.mouse = MagicMock()
            page.mouse.click = AsyncMock()

            new_page = MagicMock()
            new_page.url = "https://business.facebook.com/latest/posts/99999"
            new_page.bring_to_front = AsyncMock()
            new_page.close = AsyncMock()

            context = MagicMock()
            context.pages = [page, new_page]
            page.context = context

            notifs = [
                {
                    "index": 0,
                    "text": "Đức Trí đã bình luận về bài viết của bạn: 'Tư vấn' · 1 phút",
                    "coords": {"x": 300.0, "y": 150.0, "width": 500.0, "height": 60.0},
                }
            ]

            notif_loc = make_coord_mock_locator(rect_val={"x": 300.0, "y": 150.0, "width": 500.0, "height": 60.0})
            page.locator = MagicMock(return_value=notif_loc)

            with patch("bot.page_bot_engine.verify_logged_in", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.dismiss_blocking_modals", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.inspect_notifications_list", new_callable=AsyncMock, return_value=notifs), \
                 patch("bot.page_bot_engine.click_element_at_physical_coordinates", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.process_post_comments_by_coordinates", new_callable=AsyncMock, return_value=1) as mock_post_proc, \
                 patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock):

                replied = await process_facebook_notifications_tab(page, self.memory, dry_run=False)

                self.assertEqual(replied, 1)
                new_page.bring_to_front.assert_awaited()
                mock_post_proc.assert_awaited_once()
                self.assertEqual(mock_post_proc.call_args[1]["page"], new_page)
                self.assertEqual(mock_post_proc.call_args[1]["target_author_filter"], "Đức Trí")
                new_page.close.assert_awaited_once()

        asyncio.run(run_test())

    def test_notifications_cooldown_with_different_comment_text_not_blocked(self):
        """Khách bình luận từ thông báo nhưng nội dung mới khác với bình luận cũ -> Không bị cooldown chặn oan!"""
        t0 = 1000000.0
        self.memory.mark_comment_replied(
            comment_key="cmt:post_1:0:hash1",
            author_name="Đức Trí",
            comment_text="Hỏi giá hộp mây",
            public_reply="DAN86 chào bạn",
            private_inbox_sent=True,
            now_ts=t0,
            post_id="post_1",
            dom_index=0,
        )

        in_cd = self.memory.is_customer_in_cooldown(
            customer_name="Đức Trí",
            cooldown_seconds=300.0,
            now_ts=t0 + 10.0,
            post_id="",
            comment_text="Hỏi giá túi cỏ bàng",
        )
        self.assertFalse(in_cd, "Bình luận câu mới từ thông báo bài khác không được bị chặn bởi cooldown!")

    def test_notifications_cooldown_not_blocked_by_messenger_inbox_chat(self):
        """Khách vừa có tương tác Messenger inbox 5 giây trước, sau đó bình luận trên bài viết -> Không bị chặn cooldown!"""
        t0 = 1000000.0
        self.memory.record_inbox_reply(
            thread_key="inbox:ductri:123",
            customer_name="Đức Trí",
            customer_message_text="Shop còn mở cửa không?",
            action_type="FIRST_HELLO",
            reply_text="DAN86 chào bạn",
            now_ts=t0,
        )

        in_cd = self.memory.is_customer_in_cooldown(
            customer_name="Đức Trí",
            cooldown_seconds=300.0,
            now_ts=t0 + 5.0,
            post_id="",
            comment_text="Cho mình đặt 1 set này",
        )
        self.assertFalse(in_cd, "Tin nhắn chat trong Messenger không được chặn bình luận bài viết của khách!")

    def test_notifications_scanner_re_inspects_when_locator_is_missing_on_reloaded_page(self):
        """Khi trang được điều hướng/tải lại khiến attribute data-dan86-notif-idx bị mất -> Tự động re-inspect để lấy lại locator!"""
        async def run_test():
            page = MagicMock()
            page.url = META_NOTIFICATIONS_URL
            page.goto = AsyncMock()

            # First locator check returns count=0 (missing marker), second returns count=1 after re-inspect
            missing_loc = make_coord_mock_locator(count_val=0, visible_val=False)
            found_loc = make_coord_mock_locator(count_val=1, visible_val=True, rect_val={"x": 300.0, "y": 150.0, "width": 500.0, "height": 60.0})

            call_count = 0
            def locator_side_effect(sel):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return missing_loc
                return found_loc

            page.locator = MagicMock(side_effect=locator_side_effect)

            notifs = [
                {
                    "index": 0,
                    "text": "Đức Trí đã bình luận về bài viết: 'Báo giá' · 1 phút",
                    "coords": {"x": 300.0, "y": 150.0, "width": 500.0, "height": 60.0},
                }
            ]

            re_inspected = False
            async def mock_inspect(p):
                nonlocal re_inspected
                re_inspected = True
                return notifs

            with patch("bot.page_bot_engine.verify_logged_in", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.dismiss_blocking_modals", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.inspect_notifications_list", side_effect=mock_inspect), \
                 patch("bot.page_bot_engine.click_element_at_physical_coordinates", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.process_post_comments_by_coordinates", new_callable=AsyncMock, return_value=1), \
                 patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock):

                replied = await process_facebook_notifications_tab(page, self.memory, dry_run=False)
                self.assertEqual(replied, 1)
                self.assertTrue(re_inspected)

        asyncio.run(run_test())


class TestDomEvaluationRealBrowser(unittest.TestCase):
    """Kiểm tra trực tiếp code JavaScript của inspect_notifications_list và inspect_comment_panel trên DOM thực tế."""

    def test_inspect_notifications_list_preserves_card_with_long_child_link(self):
        import concurrent.futures
        from playwright.async_api import async_playwright

        async def run_async():
            async with async_playwright() as p:
                b = await p.chromium.launch(headless=True)
                p_async = await b.new_page(viewport={"width": 1280, "height": 800})

                # Test 1: Card chứa thẻ a có innerText dài >= 10 ký tự ('Nguyễn Đức Trí' = 14 ký tự)
                # Bắt buộc inspect_notifications_list KHÔNG ĐƯỢC bỏ qua thẻ thông báo này!
                html = """
                <!DOCTYPE html>
                <html>
                <body>
                  <div role="list" style="width: 600px; padding: 20px;">
                    <div role="listitem" style="width: 500px; height: 60px; display: block;">
                      <a role="link" style="display: inline-block;">Nguyễn Đức Trí</a>
                      <span> đã bình luận về bài viết của bạn: 'Báo giá em set này với' · 2 phút</span>
                    </div>
                  </div>
                </body>
                </html>
                """
                await p_async.set_content(html)
                notifs = await inspect_notifications_list(p_async)
                self.assertEqual(len(notifs), 1, "Thẻ thông báo chứa link con dài >= 10 ký tự KHÔNG ĐƯỢC bị nuốt chửng!")
                self.assertIn("Nguyễn Đức Trí", notifs[0]["text"])
                self.assertEqual(notifs[0]["index"], 0)

                # Kiểm tra attribute data-dan86-notif-idx được gán đúng
                attr = await p_async.locator('div[role="listitem"]').get_attribute("data-dan86-notif-idx")
                self.assertEqual(attr, "0")

                # Test 2: Bọc trong container outer, chỉ trả về thẻ con bên trong
                html_wrapper = """
                <!DOCTYPE html>
                <html>
                <body>
                  <div role="article" style="width: 500px; height: 180px; display: block;">
                    <div role="listitem" style="width: 450px; height: 50px; display: block;">
                      <span>Đức Trí đã bình luận về bài viết 1 · 1 phút</span>
                    </div>
                    <div role="listitem" style="width: 450px; height: 50px; display: block;">
                      <span>Đức Trí đã bình luận về bài viết 2 · 3 phút</span>
                    </div>
                  </div>
                </body>
                </html>
                """
                await p_async.set_content(html_wrapper)
                notifs_wrapped = await inspect_notifications_list(p_async)
                self.assertEqual(len(notifs_wrapped), 2, "Chỉ lấy 2 thẻ con độc lập, không lấy wrapper ngoài!")

                # Test 3: inspect_comment_panel loại bỏ article không có nút bấm
                html_comments = """
                <!DOCTYPE html>
                <html>
                <body>
                  <div role="article" style="position: absolute; left: 350px; top: 50px; width: 600px; height: 100px;">
                    <span>Mô tả bài viết quà tặng DAN86 thuần Việt</span>
                  </div>
                  <div role="article" style="position: absolute; left: 350px; top: 200px; width: 600px; height: 80px;">
                    <a role="link">Đức Trí</a>
                    <div dir="auto">Cho em xin giá set này ạ</div>
                    <div role="button"><span>Trả lời</span></div>
                    <div role="button"><span>Gửi tin nhắn</span></div>
                  </div>
                </body>
                </html>
                """
                await p_async.set_content(html_comments)
                c_info = await inspect_comment_panel(p_async)
                self.assertEqual(c_info["unreplied_count"], 1, "Chỉ nhận diện article có nút tương tác, bỏ qua article mô tả bài viết!")
                self.assertEqual(c_info["author_name"], "Đức Trí")

                # Test 4: Multi-level nested replies - khách bình luận cấp 2 lồng dưới phản hồi của Page, và Page đã phản hồi tiếp
                html_multi_nested = """
                <!DOCTYPE html>
                <html>
                <body>
                  <!-- Root comment #1 của khách -->
                  <div role="article" style="position: absolute; left: 350px; top: 100px; width: 600px; height: 80px;">
                    <a role="link">Đức Trí</a>
                    <div dir="auto">Cho em xin giá set này</div>
                    <div role="button"><span>Trả lời</span></div>
                    <div role="button"><span>Gửi tin nhắn</span></div>
                  </div>
                  <!-- Page reply #1 -->
                  <div role="article" style="position: absolute; left: 390px; top: 200px; width: 550px; height: 80px;">
                    <a role="link">Dần86Farm</a>
                    <div dir="auto">Dạ 150k bạn nha</div>
                    <div role="button"><span>Trả lời</span></div>
                  </div>
                  <!-- Khách phản hồi tiếp cấp 2 trong luồng (same indentation: 390px) -->
                  <div role="article" style="position: absolute; left: 390px; top: 300px; width: 550px; height: 80px;">
                    <a role="link">Đức Trí</a>
                    <div dir="auto">Ship về Hà Nội bao nhiêu ạ?</div>
                    <div role="button"><span>Trả lời</span></div>
                    <div role="button"><span>Gửi tin nhắn</span></div>
                  </div>
                  <!-- Page reply #2 cho câu hỏi phụ của khách -->
                  <div role="article" style="position: absolute; left: 390px; top: 400px; width: 550px; height: 80px;">
                    <a role="link">Dần86Farm</a>
                    <div dir="auto">Dạ phí ship 20k ạ</div>
                    <div role="button"><span>Trả lời</span></div>
                  </div>
                </body>
                </html>
                """
                await p_async.set_content(html_multi_nested)
                multi_info = await inspect_comment_panel(p_async)
                self.assertEqual(multi_info["total_comments"], 4)
                # Cả 2 bình luận của khách đều đã có câu trả lời của Page (has_page_reply == True)
                for uc in multi_info["unreplied_comments"]:
                    self.assertTrue(uc["has_page_reply"], f"Bình luận '{uc['comment_text']}' phải nhận diện has_page_reply == True!")
                    self.assertTrue(uc["has_msg_btn"], "has_msg_btn phải là boolean True!")

                # Test 5: Multi-level nested reply CHƯA có phản hồi của Page
                html_nested_unreplied = """
                <!DOCTYPE html>
                <html>
                <body>
                  <div role="article" style="position: absolute; left: 350px; top: 100px; width: 600px; height: 80px;">
                    <a role="link">Đức Trí</a>
                    <div dir="auto">Cho em xin giá set này</div>
                    <div role="button"><span>Trả lời</span></div>
                    <div role="button"><span>Gửi tin nhắn</span></div>
                  </div>
                  <div role="article" style="position: absolute; left: 390px; top: 200px; width: 550px; height: 80px;">
                    <a role="link">Dần86Farm</a>
                    <div dir="auto">Dạ 150k bạn nha</div>
                    <div role="button"><span>Trả lời</span></div>
                  </div>
                  <!-- Khách hỏi tiếp nhưng Page CHƯA trả lời -->
                  <div role="article" style="position: absolute; left: 390px; top: 300px; width: 550px; height: 80px;">
                    <a role="link">Đức Trí</a>
                    <div dir="auto">Còn hàng màu đỏ không shop?</div>
                    <div role="button"><span>Trả lời</span></div>
                    <div role="button"><span>Gửi tin nhắn</span></div>
                  </div>
                  <!-- Bình luận gốc của khách khác -->
                  <div role="article" style="position: absolute; left: 350px; top: 400px; width: 600px; height: 80px;">
                    <a role="link">Khách Hàng Khác</a>
                    <div dir="auto">Sản phẩm đẹp quá</div>
                    <div role="button"><span>Trả lời</span></div>
                  </div>
                </body>
                </html>
                """
                await p_async.set_content(html_nested_unreplied)
                unrep_info = await inspect_comment_panel(p_async)
                target_nested = [c for c in unrep_info["unreplied_comments"] if "màu đỏ" in c["comment_text"]]
                self.assertEqual(len(target_nested), 1)
                self.assertFalse(target_nested[0]["has_page_reply"], "Câu hỏi phụ chưa trả lời phải có has_page_reply == False!")

                await b.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(asyncio.run, run_async()).result()

    def test_dismiss_blocking_modals_handles_various_labels_and_spares_composer(self):
        async def run_test():
            page = MagicMock()
            # Modal 1: Upsell dialog với button "Không phải bây giờ"
            btn_not_now = make_coord_mock_locator(inner_text_val="Không phải bây giờ")
            composer_empty = make_coord_mock_locator(count_val=0, visible_val=False)
            dlg1 = make_coord_mock_locator()
            def dlg1_locator(sel):
                if 'textbox' in sel:
                    return composer_empty
                return btn_not_now
            dlg1.locator = MagicMock(side_effect=dlg1_locator)

            # Modal 2: Private inbox dialog đang soạn tin nhắn -> TUYỆT ĐỐI KHÔNG ĐƯỢC ĐÓNG!
            composer_chat = make_coord_mock_locator(count_val=1, visible_val=True, aria_val="Nhập tin nhắn riêng...")
            btn_close = make_coord_mock_locator(aria_val="Đóng")
            dlg2 = make_coord_mock_locator()
            def dlg2_locator(sel):
                if 'textbox' in sel:
                    return composer_chat
                return btn_close
            dlg2.locator = MagicMock(side_effect=dlg2_locator)

            all_dlgs = [dlg1, dlg2]
            dialogs_mock = MagicMock()
            dialogs_mock.count = AsyncMock(return_value=len(all_dlgs))
            dialogs_mock.nth = MagicMock(side_effect=lambda idx: all_dlgs[idx])
            page.locator = MagicMock(return_value=dialogs_mock)

            from bot.page_bot_engine import dismiss_blocking_modals
            await dismiss_blocking_modals(page)

            # btn_not_now của dlg1 được bấm đóng
            btn_not_now.click.assert_awaited()
            # btn_close của dlg2 TUYỆT ĐỐI KHÔNG bị bấm vì dlg2 là composer chat!
            btn_close.click.assert_not_awaited()

        asyncio.run(run_test())

    def test_notifications_without_snippet_not_blocked_by_cooldown_from_other_post(self):
        async def run_test():
            page = MagicMock()
            page.url = META_NOTIFICATIONS_URL
            page.goto = AsyncMock()
            page.mouse = MagicMock()
            page.mouse.click = AsyncMock()

            # Khách vừa được rep bình luận trên bài viết khác 30 giây trước
            mem = BotMemoryStore(memory_path=tempfile.NamedTemporaryFile().name)
            mem.mark_comment_replied(
                comment_key="cmt:post_old:0",
                author_name="Đức Trí",
                comment_text="Cho mình xem giá",
                public_reply="DAN86 chào bạn",
                private_inbox_sent=True,
                now_ts=100000.0,
                post_id="post_old",
            )

            # Thông báo mới từ bài viết khác KHÔNG có snippet (Facebook không trích dẫn nội dung)
            notifs = [
                {
                    "index": 0,
                    "text": "Đức Trí đã bình luận về một bài viết của bạn · vừa xong",
                    "coords": {"x": 300.0, "y": 150.0, "width": 500.0, "height": 60.0},
                }
            ]

            with patch("bot.page_bot_engine.verify_logged_in", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.dismiss_blocking_modals", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.inspect_notifications_list", new_callable=AsyncMock, return_value=notifs), \
                 patch("bot.page_bot_engine.process_post_comments_by_coordinates", new_callable=AsyncMock, return_value=1) as mock_post_proc, \
                 patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock):

                notif_loc = make_coord_mock_locator(rect_val={"x": 300.0, "y": 150.0, "width": 500.0, "height": 60.0}, inner_text_val="Đức Trí đã bình luận về bài viết")
                page.locator = MagicMock(return_value=notif_loc)

                replied = await process_facebook_notifications_tab(page, mem, dry_run=False)
                # Bắt buộc bot KHÔNG được chặn oan thông báo này vì chưa có snippet
                self.assertEqual(replied, 1)
                mock_post_proc.assert_awaited_once()

        asyncio.run(run_test())

    def test_notifications_scanner_re_locates_by_author_when_card_shifted(self):
        async def run_test():
            page = MagicMock()
            page.url = META_NOTIFICATIONS_URL
            page.goto = AsyncMock()

            # Ban đầu index 0 là card của Khách Khác sau khi reload, card của Đức Trí bị đẩy xuống vị trí khác
            other_card = make_coord_mock_locator(inner_text_val="Khách Khác đã bình luận")
            duc_tri_card = make_coord_mock_locator(inner_text_val="Đức Trí đã bình luận về bài viết")

            def loc_side_effect(sel):
                if 'has-text("Đức Trí")' in sel:
                    return duc_tri_card
                if '[data-dan86-notif-idx="0"]' in sel:
                    return other_card
                return make_coord_mock_locator(count_val=0, visible_val=False)

            page.locator = MagicMock(side_effect=loc_side_effect)

            notifs = [
                {
                    "index": 0,
                    "text": "Đức Trí đã bình luận về bài viết của bạn: 'Tư vấn' · 1 phút",
                    "coords": {"x": 300.0, "y": 150.0, "width": 500.0, "height": 60.0},
                }
            ]

            mem = BotMemoryStore(memory_path=tempfile.NamedTemporaryFile().name)

            with patch("bot.page_bot_engine.verify_logged_in", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.dismiss_blocking_modals", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.inspect_notifications_list", new_callable=AsyncMock, return_value=notifs), \
                 patch("bot.page_bot_engine.click_element_at_physical_coordinates", new_callable=AsyncMock, return_value=True) as mock_click, \
                 patch("bot.page_bot_engine.process_post_comments_by_coordinates", new_callable=AsyncMock, return_value=1), \
                 patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock):

                replied = await process_facebook_notifications_tab(page, mem, dry_run=False)
                self.assertEqual(replied, 1)
                # Đảm bảo phần tử được click là duc_tri_card chứ không phải other_card
                mock_click.assert_awaited_with(page, duc_tri_card, timeout_ms=3000)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
