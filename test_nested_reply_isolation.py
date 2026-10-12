# -*- coding: utf-8 -*-
"""
Unit tests kiểm tra tính cô lập tuyệt đối của phản hồi lồng nhau (Nested Reply Isolation Test Suite)
Mô phỏng đầy đủ các tình huống thực tế của Meta Business Suite:
- Tình huống 1: Có cả ô bình luận bài viết cấp 1 (ở ngoài) và ô reply lồng nhau (ở trong comment article).
  Đảm bảo logic BẮT BUỘC chỉ chọn ô reply lồng nhau, không bao giờ chọn ô bài viết cấp 1.
- Tình huống 2: Nút reply không mở được ô lồng nhau (hoặc chỉ có ô bình luận bài viết).
  Đảm bảo bot từ chối gõ vào ô bài viết, không đăng cmt cấp 1 ra ngoài, bảo toàn quy tắc lồng nhau.
- Tình huống 3: Bounding box filtering: kiểm tra hàm lọc vị trí Y loại bỏ các ô textbox nằm xa comment article (> 250px),
  cùng các điều kiện biên hình học X và chiều cao tối thiểu.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.page_bot_engine import (
    locate_nested_reply_box,
    process_facebook_comments_tab,
)


def make_mock_locator(
    count_val: int = 1,
    visible_val: bool = True,
    bounding_box_val: dict = None,
    aria_val: str = "",
    placeholder_val: str = "",
    is_edit_val: bool = True,
    inner_text_val: str = "",
):
    loc = MagicMock()
    loc.count = AsyncMock(return_value=count_val)
    loc.is_visible = AsyncMock(return_value=visible_val)
    loc.bounding_box = AsyncMock(return_value=bounding_box_val)
    loc.get_attribute = AsyncMock(
        side_effect=lambda a: aria_val if a == "aria-label" else (placeholder_val if a == "placeholder" else "")
    )
    loc.evaluate = AsyncMock(return_value=is_edit_val)
    loc.first = loc
    loc.last = loc
    loc.nth = MagicMock(return_value=loc)
    loc.scroll_into_view_if_needed = AsyncMock()
    loc.click = AsyncMock()
    loc.fill = AsyncMock()
    loc.press_sequentially = AsyncMock()
    loc.inner_text = AsyncMock(return_value=inner_text_val)
    return loc


class TestNestedReplyIsolation(unittest.TestCase):
    """
    Bộ test case chuyên biệt kiểm tra tính cô lập của nested reply
    trên giao diện Meta Business Suite Inbox / Comments.
    """

    def setUp(self):
        # Thiết lập comment article mẫu tại x=350, y=200, width=600, height=80
        self.art_box = {"x": 350.0, "y": 200.0, "width": 600.0, "height": 80.0}
        self.mock_target_art = make_mock_locator(
            count_val=1,
            visible_val=True,
            bounding_box_val=self.art_box,
            inner_text_val="Đức Trí\n.\nTrả lời\nGửi tin nhắn",
        )

    def test_situation_1_selects_nested_reply_box_over_post_level_comment_box(self):
        """
        TÌNH HUỐNG 1:
        Có cả ô bình luận bài viết cấp 1 (ở ngoài/đáy trang) và ô reply lồng nhau (ở trong/sau comment article).
        Đảm bảo logic BẮT BUỘC chỉ chọn ô reply lồng nhau, không bao giờ chọn ô bài viết cấp 1.
        """
        async def run_test():
            page = MagicMock()

            # Ô bình luận bài viết cấp 1 (ở đáy trang, y=850, xa comment article)
            post_level_box = make_mock_locator(
                count_val=1,
                visible_val=True,
                bounding_box_val={"x": 350.0, "y": 850.0, "width": 600.0, "height": 45.0},
                aria_val="Bình luận dưới tên Quà tặng thuần Việt DAN86",
                placeholder_val="Viết bình luận công khai...",
            )

            # Ô phản hồi lồng nhau cấp 2 (nằm ngay sau/trong target_art tại y=250, x=380)
            nested_box = make_mock_locator(
                count_val=1,
                visible_val=True,
                bounding_box_val={"x": 380.0, "y": 250.0, "width": 500.0, "height": 38.0},
                aria_val="Viết câu trả lời dưới tên Quà tặng thuần Việt DAN86...",
                placeholder_val="Trả lời...",
            )

            # Target article trả về nested_box cho XPath following role=textbox
            def art_locator_router(sel):
                if 'xpath=following::div[@role="textbox"][1]' in sel:
                    return nested_box
                if 'xpath=following::div[@contenteditable="true"][1]' in sel:
                    return nested_box
                if 'div[role="textbox"]' in sel:
                    return nested_box
                return make_mock_locator(count_val=0, visible_val=False)

            self.mock_target_art.locator = MagicMock(side_effect=art_locator_router)

            # Page locator trả về post_level_box khi quét các textbox chung
            def page_locator_router(sel):
                if ':focus' in sel:
                    return make_mock_locator(count_val=0, visible_val=False)
                if 'div[role="textbox"]' in sel:
                    loc = MagicMock()
                    loc.count = AsyncMock(return_value=2)
                    loc.nth = MagicMock(side_effect=lambda i: nested_box if i == 0 else post_level_box)
                    return loc
                return make_mock_locator(count_val=0, visible_val=False)

            page.locator = MagicMock(side_effect=page_locator_router)

            result = await locate_nested_reply_box(page, self.mock_target_art, timeout_seconds=0.5)

            # Khẳng định 1: Tìm thấy ô phản hồi
            self.assertIsNotNone(result, "Phải tìm thấy ô nhập phản hồi lồng nhau")
            # Khẳng định 2: Kết quả BẮT BUỘC là nested_box
            self.assertEqual(result, nested_box, "Kết quả trả về phải chính là nested reply box")
            # Khẳng định 3: Tuyệt đối KHÔNG PHẢI là ô bình luận bài viết cấp 1
            self.assertNotEqual(result, post_level_box, "Tuyệt đối không được chọn nhầm ô bình luận bài viết cấp 1")

        asyncio.run(run_test())

    def test_situation_1_e2e_isolation_types_only_to_nested_box_never_post_level_box(self):
        """
        TÌNH HUỐNG 1 (End-to-End Simulation):
        Trong process_facebook_comments_tab, khi có cả ô bài viết cấp 1 và ô nested reply:
        Bot chỉ gõ public_reply vào ô nested reply, call_count của ô bài viết cấp 1 bằng 0.
        """
        async def run_test():
            page = MagicMock()
            page.url = "https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512"
            page.goto = AsyncMock()
            page.keyboard = MagicMock()
            page.keyboard.press = AsyncMock()

            post_level_box = make_mock_locator(
                count_val=1,
                visible_val=True,
                bounding_box_val={"x": 350.0, "y": 850.0, "width": 600.0, "height": 45.0},
                aria_val="Bình luận dưới tên DAN86",
                placeholder_val="Viết bình luận công khai...",
            )

            nested_box = make_mock_locator(
                count_val=1,
                visible_val=True,
                bounding_box_val={"x": 380.0, "y": 250.0, "width": 500.0, "height": 38.0},
                aria_val="Viết câu trả lời...",
                placeholder_val="Trả lời...",
            )

            # Mock memory store
            mock_memory = MagicMock()
            mock_memory.is_customer_in_cooldown.return_value = False
            mock_memory.should_reply_comment.return_value = (True, "mock_comment_key")
            mock_memory.prepare_comment_and_inbox_replies.return_value = (
                "DAN86 cảm ơn bạn đã quan tâm ạ!",
                "DAN86 xin gửi thông tin chi tiết qua tin nhắn...",
            )

            # Inspect comment panel trả về bình luận của Đức Trí chưa rep
            mock_comment_info = {
                "post_id": "post_12345",
                "author_name": "Đức Trí",
                "comment_text": ".",
                "target_article_index": 0,
                "has_page_reply": False,
                "unreplied_count": 1,
                "unreplied_comments": [{
                    "dom_index": 0,
                    "author_name": "Đức Trí",
                    "comment_text": ".",
                    "time_str": "1 giờ trước",
                    "is_old_comment": False,
                    "has_page_reply": False,
                    "has_reply_btn": True,
                    "has_msg_btn": True,
                    "msg_btn_text": "Gửi tin nhắn",
                }],
                "total_comments": 1,
            }

            thread_item = make_mock_locator(count_val=1, visible_val=True, inner_text_val="Đức Trí: .")
            thread_loc = MagicMock()
            thread_loc.count = AsyncMock(return_value=1)
            thread_loc.nth = MagicMock(return_value=thread_item)

            reply_btn_mock = make_mock_locator(count_val=1, visible_val=True, inner_text_val="Trả lời")

            def page_locator_router(sel):
                if 'div._a6ag._a6ah' in sel or '[role="grid"]' in sel:
                    return thread_loc
                if '[data-dan86-reply-btn="true"]' in sel:
                    return reply_btn_mock
                if '[data-dan86-reply-target="true"]' in sel:
                    return self.mock_target_art
                if '[role="article"]' in sel:
                    arts = MagicMock()
                    arts.count = AsyncMock(return_value=1)
                    arts.nth = MagicMock(return_value=self.mock_target_art)
                    return arts
                return make_mock_locator(count_val=0, visible_val=False)

            page.locator = MagicMock(side_effect=page_locator_router)

            def art_locator_router(sel):
                if 'xpath=following::div[@role="textbox"][1]' in sel:
                    return nested_box
                return make_mock_locator(count_val=0, visible_val=False)

            self.mock_target_art.locator = MagicMock(side_effect=art_locator_router)

            with patch("bot.page_bot_engine.verify_logged_in", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.ensure_newest_comments_filter", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.expand_all_comment_replies", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.inspect_comment_panel", new_callable=AsyncMock, side_effect=[mock_comment_info, {"unreplied_comments": []}]), \
                 patch("bot.page_bot_engine.tag_comment_target_in_dom", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.send_private_inbox_to_commenter", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.dismiss_blocking_modals", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.type_human_like", new_callable=AsyncMock) as mock_type:

                await process_facebook_comments_tab(page, mock_memory, dry_run=False)

                # Khẳng định 1: type_human_like được gọi đúng vào nested_box
                mock_type.assert_awaited()
                call_args = mock_type.call_args[0]
                typed_target = call_args[1]
                self.assertEqual(typed_target, nested_box, "type_human_like phải được gọi với nested_box")
                self.assertNotEqual(typed_target, post_level_box, "type_human_like tuyệt đối không được gõ vào post_level_box")

                # Khẳng định 2: post_level_box tuyệt đối không bị nhập dữ liệu
                self.assertEqual(post_level_box.press_sequentially.call_count, 0)
                self.assertEqual(post_level_box.fill.call_count, 0)

        asyncio.run(run_test())

    def test_situation_2_reply_fails_to_open_nested_refuses_to_type_post_box(self):
        """
        TÌNH HUỐNG 2:
        Nút reply không mở được ô lồng nhau (hoặc giao diện chỉ có ô bình luận bài viết cấp 1).
        Đảm bảo bot từ chối gõ vào ô bài viết, không đăng cmt cấp 1 ra ngoài, bảo toàn quy tắc lồng nhau.
        """
        async def run_test():
            page = MagicMock()

            # Chỉ có ô bình luận bài viết cấp 1 ở đáy trang (hoặc aria="Bình luận dưới tên...")
            post_level_box = make_mock_locator(
                count_val=1,
                visible_val=True,
                bounding_box_val={"x": 350.0, "y": 850.0, "width": 600.0, "height": 45.0},
                aria_val="Bình luận dưới tên Quà tặng thuần Việt DAN86",
                placeholder_val="Viết bình luận công khai...",
            )

            # Target article không có ô following hay inside nào
            self.mock_target_art.locator = MagicMock(return_value=make_mock_locator(count_val=0, visible_val=False))

            def page_locator_router(sel):
                if ':focus' in sel:
                    # Focus cũng rơi vào ô post_level_box ở đáy trang
                    return post_level_box
                if 'div[role="textbox"]' in sel:
                    loc = MagicMock()
                    loc.count = AsyncMock(return_value=1)
                    loc.nth = MagicMock(return_value=post_level_box)
                    return loc
                return make_mock_locator(count_val=0, visible_val=False)

            page.locator = MagicMock(side_effect=page_locator_router)

            # locate_nested_reply_box phải trả về None vì không có ô nested reply hợp lệ
            result = await locate_nested_reply_box(page, self.mock_target_art, timeout_seconds=0.2)

            # Khẳng định 1: Bot từ chối chọn ô bài viết cấp 1 -> trả về None
            self.assertIsNone(result, "Khi không mở được ô nested reply, locate_nested_reply_box BẮT BUỘC trả về None")

        asyncio.run(run_test())

    def test_situation_2_e2e_failsafe_guard_cancels_public_comment_and_sends_inbox_only(self):
        """
        TÌNH HUỐNG 2 (End-to-End Fail-safe Guard):
        Khi nút reply không mở được ô lồng nhau (locate_nested_reply_box trả về None):
        Bot HỦY BỎ bước rep cmt công khai, TUYỆT ĐỐI KHÔNG GÕ VÀO Ô BÀI VIẾT,
        và chỉ gửi tin nhắn riêng Messenger, bảo toàn 100% quy tắc lồng nhau.
        """
        async def run_test():
            page = MagicMock()
            page.url = "https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512"
            page.goto = AsyncMock()
            page.keyboard = MagicMock()
            page.keyboard.press = AsyncMock()

            post_level_box = make_mock_locator(
                count_val=1,
                visible_val=True,
                bounding_box_val={"x": 350.0, "y": 850.0, "width": 600.0, "height": 45.0},
                aria_val="Bình luận dưới tên Quà tặng thuần Việt DAN86",
                placeholder_val="Viết bình luận công khai...",
            )

            mock_memory = MagicMock()
            mock_memory.is_customer_in_cooldown.return_value = False
            mock_memory.should_reply_comment.return_value = (True, "mock_comment_key")
            mock_memory.prepare_comment_and_inbox_replies.return_value = (
                "DAN86 cảm ơn bạn đã quan tâm ạ!",
                "DAN86 xin gửi thông tin chi tiết qua tin nhắn...",
            )

            mock_comment_info = {
                "post_id": "post_12345",
                "author_name": "Đức Trí",
                "comment_text": ".",
                "target_article_index": 0,
                "has_page_reply": False,
                "unreplied_count": 1,
                "unreplied_comments": [{
                    "dom_index": 0,
                    "author_name": "Đức Trí",
                    "comment_text": ".",
                    "time_str": "1 giờ trước",
                    "is_old_comment": False,
                    "has_page_reply": False,
                    "has_reply_btn": True,
                    "has_msg_btn": True,
                    "msg_btn_text": "Gửi tin nhắn",
                }],
                "total_comments": 1,
            }

            thread_item = make_mock_locator(count_val=1, visible_val=True, inner_text_val="Đức Trí: .")
            thread_loc = MagicMock()
            thread_loc.count = AsyncMock(return_value=1)
            thread_loc.nth = MagicMock(return_value=thread_item)

            reply_btn_mock = make_mock_locator(count_val=1, visible_val=True, inner_text_val="Trả lời")

            def page_locator_router(sel):
                if 'div._a6ag._a6ah' in sel or '[role="grid"]' in sel:
                    return thread_loc
                if '[data-dan86-reply-btn="true"]' in sel:
                    return reply_btn_mock
                if '[data-dan86-reply-target="true"]' in sel:
                    return self.mock_target_art
                if '[role="article"]' in sel:
                    arts = MagicMock()
                    arts.count = AsyncMock(return_value=1)
                    arts.nth = MagicMock(return_value=self.mock_target_art)
                    return arts
                return make_mock_locator(count_val=0, visible_val=False)

            page.locator = MagicMock(side_effect=page_locator_router)

            # target_art không mở được ô nested nào
            self.mock_target_art.locator = MagicMock(return_value=make_mock_locator(count_val=0, visible_val=False))

            mock_memory.should_reply_comment.side_effect = [(True, "mock_comment_key"), (False, "mock_comment_key")]

            with patch("bot.page_bot_engine.verify_logged_in", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.ensure_newest_comments_filter", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.expand_all_comment_replies", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.inspect_comment_panel", new_callable=AsyncMock, side_effect=[mock_comment_info, {"unreplied_comments": []}]), \
                 patch("bot.page_bot_engine.tag_comment_target_in_dom", new_callable=AsyncMock, return_value=True), \
                 patch("bot.page_bot_engine.send_private_inbox_to_commenter", new_callable=AsyncMock, return_value=True) as mock_send_inbox, \
                 patch("bot.page_bot_engine.dismiss_blocking_modals", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.type_human_like", new_callable=AsyncMock) as mock_type:

                await process_facebook_comments_tab(page, mock_memory, dry_run=False)

                # Khẳng định 1: type_human_like TUYỆT ĐỐI KHÔNG ĐƯỢC GỌI để cmt công khai
                mock_type.assert_not_awaited()
                self.assertEqual(mock_type.call_count, 0, "Không được gõ bình luận công khai khi không có ô lồng nhau")

                # Khẳng định 2: Ô bình luận bài viết cấp 1 không bị đụng tới
                self.assertEqual(post_level_box.press_sequentially.call_count, 0)
                self.assertEqual(post_level_box.fill.call_count, 0)

                # Khẳng định 3: Vẫn bảo toàn việc gửi tin nhắn riêng cho khách
                mock_send_inbox.assert_awaited_once()

                # Khẳng định 4: Memory ghi nhận rõ ràng đã bỏ qua cmt công khai vì không tìm thấy ô lồng nhau
                mock_memory.mark_comment_replied.assert_called_once()
                saved_public_reply = mock_memory.mark_comment_replied.call_args[1].get("public_reply")
                self.assertIn("Không tìm thấy ô lồng nhau", saved_public_reply)

        asyncio.run(run_test())

    def test_situation_3_bounding_box_y_filtering_rejects_distant_textboxes(self):
        """
        TÌNH HUỐNG 3:
        Bounding box filtering: kiểm tra hàm lọc vị trí Y loại bỏ các ô textbox nằm xa comment article (> 250px).
        Target article tại: y = 200, height = 100 -> Đáy target là y = 300.
        Phạm vi Y hợp lệ: y >= 200 - 10 (190) và y <= 200 + 100 + 250 (550).
        """
        async def run_test():
            target_art = make_mock_locator(
                count_val=1,
                visible_val=True,
                bounding_box_val={"x": 350.0, "y": 200.0, "width": 600.0, "height": 100.0},
            )

            # Test các tọa độ Y khác nhau
            cases = [
                # (box_y, should_accept, desc)
                (551.0, False, "Cách 251px dưới đáy target (vượt quá 250px) -> Phải loại bỏ"),
                (600.0, False, "Cách 300px dưới đáy target -> Phải loại bỏ"),
                (800.0, False, "Ô ở đáy trang (cách 500px) -> Phải loại bỏ"),
                (180.0, False, "Nằm phía trên target (y < target_y - 10) -> Phải loại bỏ"),
                (550.0, True, "Đúng ngưỡng biên 250px (y = target_y + target_h + 250) -> Chấp nhận"),
                (350.0, True, "Cách 50px dưới đáy target -> Chấp nhận"),
                (250.0, True, "Nằm bên trong khoảng target -> Chấp nhận"),
                (195.0, True, "Sát mép trên trong dung sai -10px -> Chấp nhận"),
            ]

            for box_y, should_accept, desc in cases:
                page = MagicMock()
                cand_box = make_mock_locator(
                    count_val=1,
                    visible_val=True,
                    bounding_box_val={"x": 380.0, "y": box_y, "width": 500.0, "height": 35.0},
                    aria_val="Viết câu trả lời...",
                    placeholder_val="Trả lời...",
                )

                # Cấu hình following trả về cand_box
                target_art.locator = MagicMock(return_value=cand_box)
                page.locator = MagicMock(return_value=make_mock_locator(count_val=0, visible_val=False))

                result = await locate_nested_reply_box(page, target_art, timeout_seconds=0.1)

                if should_accept:
                    self.assertIsNotNone(result, f"Thất bại tại test case: {desc}")
                    self.assertEqual(result, cand_box, f"Phải chấp nhận textbox tại y={box_y}: {desc}")
                else:
                    self.assertIsNone(result, f"Phải loại bỏ textbox tại y={box_y}: {desc}")

        asyncio.run(run_test())

    def test_situation_3_bounding_box_x_and_height_filtering(self):
        """
        TÌNH HUỐNG 3 (Bổ sung Bounding Box X và Chiều cao):
        - Ô lệch trái cột bài viết (x < target_x - 50, ví dụ nằm ở menu bên trái x=250): Loại bỏ.
        - Ô lệch phải quá xa (abs(box_x - target_x) > 300, ví dụ x=700): Loại bỏ.
        - Ô có chiều cao < 12px (phần tử ẩn / 0px stub): Loại bỏ.
        """
        async def run_test():
            target_art = make_mock_locator(
                count_val=1,
                visible_val=True,
                bounding_box_val={"x": 350.0, "y": 200.0, "width": 600.0, "height": 80.0},
            )

            # 1. Thử nghiệm x lệch trái (x=250 < 350 - 50 = 300)
            page = MagicMock()
            left_box = make_mock_locator(
                count_val=1,
                visible_val=True,
                bounding_box_val={"x": 250.0, "y": 250.0, "width": 100.0, "height": 30.0},
                aria_val="Viết câu trả lời...",
            )
            target_art.locator = MagicMock(return_value=left_box)
            page.locator = MagicMock(return_value=make_mock_locator(count_val=0, visible_val=False))
            res_left = await locate_nested_reply_box(page, target_art, timeout_seconds=0.1)
            self.assertIsNone(res_left, "Textbox lệch sang cột bên trái phải bị loại bỏ")

            # 2. Thử nghiệm x lệch phải quá xa (x=700 > 350 + 300 = 650)
            right_box = make_mock_locator(
                count_val=1,
                visible_val=True,
                bounding_box_val={"x": 700.0, "y": 250.0, "width": 100.0, "height": 30.0},
                aria_val="Viết câu trả lời...",
            )
            target_art.locator = MagicMock(return_value=right_box)
            res_right = await locate_nested_reply_box(page, target_art, timeout_seconds=0.1)
            self.assertIsNone(res_right, "Textbox lệch sang phải quá xa phải bị loại bỏ")

            # 3. Thử nghiệm chiều cao < 12px (height=5px)
            tiny_box = make_mock_locator(
                count_val=1,
                visible_val=True,
                bounding_box_val={"x": 380.0, "y": 250.0, "width": 500.0, "height": 5.0},
                aria_val="Viết câu trả lời...",
            )
            target_art.locator = MagicMock(return_value=tiny_box)
            res_tiny = await locate_nested_reply_box(page, target_art, timeout_seconds=0.1)
            self.assertIsNone(res_tiny, "Textbox có chiều cao < 12px (ẩn/rỗng) phải bị loại bỏ")

        asyncio.run(run_test())

    def test_post_level_keyword_failsafe_guard_rejects_box_even_within_geometric_bounds(self):
        """
        Kiểm tra cơ chế Fail-safe Guard nhận diện nhãn:
        Ngay cả khi một textbox nằm trong phạm vi hình học hợp lệ (y=250),
        nhưng mang nhãn bình luận bài viết cấp 1 ('Viết bình luận công khai...' hoặc 'bình luận dưới tên...')
        mà không có từ khóa 'trả lời' / 'reply' / 'phản hồi',
        hàm locate_nested_reply_box BẮT BUỘC loại bỏ ngay lập tức.
        """
        async def run_test():
            page = MagicMock()
            deceptive_box = make_mock_locator(
                count_val=1,
                visible_val=True,
                bounding_box_val={"x": 380.0, "y": 250.0, "width": 500.0, "height": 40.0},
                aria_val="Bình luận dưới tên Quà tặng thuần Việt DAN86",
                placeholder_val="Viết bình luận công khai...",
            )

            self.mock_target_art.locator = MagicMock(return_value=deceptive_box)
            page.locator = MagicMock(return_value=make_mock_locator(count_val=0, visible_val=False))

            result = await locate_nested_reply_box(page, self.mock_target_art, timeout_seconds=0.1)
            self.assertIsNone(result, "Ô có nhãn bình luận bài viết cấp 1 phải bị loại bỏ ngay cả khi nằm gần comment")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
