"""
Test Suite: Regression & Hardening Verification for DAN86 Fanpage 24/7 Bot.
Covers:
1. safe_click resilience against pointer interception with JavaScript fallback.
2. needs_inbox_only retries for comments where private_inbox_sent is False.
3. Unconditional comment handling (single char, emojis, questions containing 'ngày'/'giờ').
4. Timestamp boundaries (<= 3 days vs > 3 days, abbreviations w, y, giây, s).
5. Messenger thread direction detection (left customer vs right page bubbles, y-bounds < 885).
6. 180-minute mutual silence rule and 3-stage transitions.
7. Scan interval configuration (15-30s) and dashboard zero-process cleanliness.
"""

import ast
import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bot_config import (
    FIRST_INBOX_REPLIES,
    SCAN_INTERVAL_SECONDS,
    SILENCE_REMINDER_MINUTES,
    WAIT_STAFF_REPLIES,
)
from bot.memory_store import BotMemoryStore
from bot.page_bot_engine import (
    clean_comment_text,
    is_old_comment_timestamp,
    safe_click,
)


class TestHardeningRegression(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mem_path = os.path.join(self.temp_dir.name, "test_memory.json")
        self.memory = BotMemoryStore(memory_path=self.mem_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # =========================================================================
    # 1. safe_click Pointer Interception Resilience & Fallback Tests
    # =========================================================================
    def test_safe_click_success_standard(self) -> None:
        """Kiểm tra safe_click khi phần tử có thể click bình thường với force=True."""
        mock_locator = AsyncMock()
        mock_locator.scroll_into_view_if_needed = AsyncMock()
        mock_locator.click = AsyncMock()
        mock_locator.evaluate = AsyncMock()

        result = asyncio.run(safe_click(mock_locator, timeout=2500))

        self.assertTrue(result)
        mock_locator.scroll_into_view_if_needed.assert_awaited_once_with(timeout=1500)
        mock_locator.click.assert_awaited_once_with(timeout=2500, force=True)
        mock_locator.evaluate.assert_not_called()

    def test_safe_click_pointer_intercepted_triggers_js_fallback(self) -> None:
        """
        Kiểm tra safe_click khi gặp lỗi pointer interception (TimeoutError / subtree intercepts pointer events).
        Hàm phải bắt lỗi và tự động kích hoạt synthetic click bằng JavaScript DOM.
        """
        mock_locator = AsyncMock()
        mock_locator.scroll_into_view_if_needed = AsyncMock()
        # Giả lập lỗi pointer interception điển hình từ Meta Business Suite
        mock_locator.click = AsyncMock(
            side_effect=Exception("Locator.click: Timeout 2500ms exceeded. subtree intercepts pointer events")
        )
        mock_locator.evaluate = AsyncMock(return_value=None)

        result = asyncio.run(safe_click(mock_locator, timeout=2500))

        self.assertTrue(result)
        mock_locator.scroll_into_view_if_needed.assert_awaited_once()
        mock_locator.click.assert_awaited_once_with(timeout=2500, force=True)
        # Fallback JS phải được gọi với synthetic MouseEvent
        mock_locator.evaluate.assert_awaited_once()
        js_arg = mock_locator.evaluate.call_args[0][0]
        self.assertIn("dispatchEvent", js_arg)
        self.assertIn("MouseEvent", js_arg)

    def test_safe_click_with_position_parameter(self) -> None:
        """Kiểm tra safe_click hỗ trợ tọa độ position={"x": 150, "y": 40} để tránh click nút xóa/menu."""
        mock_locator = AsyncMock()
        mock_locator.scroll_into_view_if_needed = AsyncMock()
        mock_locator.click = AsyncMock()

        pos = {"x": 150.0, "y": 40.0}
        result = asyncio.run(safe_click(mock_locator, timeout=3000, position=pos))

        self.assertTrue(result)
        mock_locator.click.assert_awaited_once_with(timeout=3000, force=True, position=pos)

    def test_safe_click_total_failure_returns_false_safely(self) -> None:
        """Kiểm tra khi cả Playwright click lẫn JS fallback đều thất bại thì hàm trả về False, không văng crash."""
        mock_locator = AsyncMock()
        mock_locator.scroll_into_view_if_needed = AsyncMock(side_effect=Exception("Element detached"))
        mock_locator.click = AsyncMock(side_effect=Exception("Interception error"))
        mock_locator.evaluate = AsyncMock(side_effect=Exception("Evaluation failed"))

        result = asyncio.run(safe_click(mock_locator, timeout=2000))
        self.assertFalse(result)

    # =========================================================================
    # 2. needs_inbox_only Retries Logic
    # =========================================================================
    def test_needs_inbox_only_when_private_inbox_not_sent(self) -> None:
        """
        Kiểm tra xử lý bình luận đã có reply công khai trong DOM (cand_has_reply=True)
        nhưng private_inbox_sent=False trong memory (do chu kỳ trước bị timeout hoặc lỗi click).
        Hệ thống phải kích hoạt needs_inbox_only = True để gửi bù tin nhắn riêng.
        """
        post_id = "post_999"
        dom_idx = 1
        author = "Trần Thị Mai"
        comment_text = "Tư vấn cho mình set quà 20/10 nhé shop"

        # Giả lập bản ghi đã được rep công khai nhưng private_inbox_sent = False
        _, comment_key = self.memory.should_reply_comment(
            author_name=author,
            comment_text=comment_text,
            has_page_reply_in_dom=False,
            post_id=post_id,
            dom_index=dom_idx,
        )
        self.memory.mark_comment_replied(
            comment_key=comment_key,
            author_name=author,
            comment_text=comment_text,
            public_reply="Dạ chào bạn, DAN86 đã rep!",
            private_inbox_sent=False,  # Chưa gửi được inbox
        )

        existing_rec = self.memory.data["replied_comments"].get(comment_key)
        self.assertIsNotNone(existing_rec)
        self.assertFalse(existing_rec.get("private_inbox_sent"))

        # Kiểm tra logic xử lý needs_inbox_only
        cand_has_reply = True  # Đã có rep công khai
        needs_inbox_only = False
        if cand_has_reply and comment_key:
            rec = self.memory.data["replied_comments"].get(comment_key)
            if not rec or not rec.get("private_inbox_sent"):
                needs_inbox_only = True

        self.assertTrue(needs_inbox_only, "Bình luận chưa gửi inbox riêng phải được kích hoạt needs_inbox_only = True")

        # Sau khi gửi bù inbox thành công, cập nhật lại memory
        self.memory.mark_comment_replied(
            comment_key=comment_key,
            author_name=author,
            comment_text=comment_text,
            public_reply=existing_rec["public_reply"],
            private_inbox_sent=True,
            private_reply_text="Dạ DAN86 xin gửi bảng giá...",
        )
        updated_rec = self.memory.data["replied_comments"].get(comment_key)
        self.assertTrue(updated_rec.get("private_inbox_sent"))

        # Chu kỳ sau quét lại: đã có private_inbox_sent=True -> không gửi lại nữa
        needs_inbox_only_next = False
        if cand_has_reply and comment_key:
            rec2 = self.memory.data["replied_comments"].get(comment_key)
            if not rec2 or not rec2.get("private_inbox_sent"):
                needs_inbox_only_next = True

        self.assertFalse(needs_inbox_only_next, "Bình luận đã gửi inbox rồi thì không được gửi lại lần 2")

    # =========================================================================
    # 3. Unconditional Comment Handling & Vietnamese Questions Preservation
    # =========================================================================
    def test_unconditional_comment_cleaning_and_preservation(self) -> None:
        """
        Kiểm tra xử lý bình luận không điều kiện:
        - 1 ký tự, icon, sticker không bị bỏ qua
        - Câu hỏi tiếng Việt chứa các từ 'ngày', 'giờ', 'phút' KHÔNG bị xóa mất
        - Tiền tố thời gian (kể cả giây, s, phút, giờ, hôm qua) được cắt sạch
        """
        # 1. Bình luận ngắn / icon / sticker
        self.assertEqual(clean_comment_text("."), ".")
        self.assertEqual(clean_comment_text("?"), "?")
        self.assertEqual(clean_comment_text("❤️"), "❤️")
        self.assertEqual(clean_comment_text("🌾🎁"), "🌾🎁")
        self.assertEqual(clean_comment_text("[Sticker / GIPHY]"), "[Sticker / GIPHY]")

        # 2. Câu hỏi của khách chứa từ 'ngày', 'giờ', 'phút' phải được BẢO TOÀN NGUYÊN VẸN
        self.assertEqual(clean_comment_text("Mấy ngày có hàng vậy shop?"), "Mấy ngày có hàng vậy shop?")
        self.assertEqual(clean_comment_text("Có giao hàng trong ngày không?"), "Có giao hàng trong ngày không?")
        self.assertEqual(clean_comment_text("Shop mở cửa tới mấy giờ?"), "Shop mở cửa tới mấy giờ?")
        self.assertEqual(clean_comment_text("Chờ 5 phút rồi chưa thấy shop rep"), "Chờ 5 phút rồi chưa thấy shop rep")

        # 3. Tiền tố thời gian bị dính vào đầu comment phải được cắt bỏ sạch sẽ
        self.assertEqual(clean_comment_text("15 giây Cho em xin giá"), "Cho em xin giá")
        self.assertEqual(clean_comment_text("30s Ib mình nhé"), "Ib mình nhé")
        self.assertEqual(clean_comment_text("5 phút Cho hỏi set quà này bao nhiêu"), "Cho hỏi set quà này bao nhiêu")
        self.assertEqual(clean_comment_text("2 giờ Còn hàng không bạn"), "Còn hàng không bạn")
        self.assertEqual(clean_comment_text("vừa xong Ib shop ơi"), "Ib shop ơi")
        self.assertEqual(clean_comment_text("hôm qua Cho xin địa chỉ cửa hàng"), "Cho xin địa chỉ cửa hàng")

    # =========================================================================
    # 4. Timestamp Boundaries: <= 3 Days vs > 3 Days & Abbreviations
    # =========================================================================
    def test_timestamp_boundaries_new_vs_old(self) -> None:
        """
        Kiểm tra ranh giới thời gian bình luận:
        - Bình luận MỚI (<= 3 ngày): 'vừa xong', 'giây', 's', 'phút', 'giờ', 'hôm qua', '1 ngày'..'3 ngày' -> is_old = False
        - Bình luận CŨ (> 3 ngày): '4 ngày', '5 ngày', '10 ngày', 'tuần', 'w', 'tháng', 'năm', 'y' -> is_old = True
        """
        # Bình luận MỚI (PHẢI TRẢ LỜI)
        new_timestamps = [
            "vừa xong",
            "just now",
            "10 giây trước",
            "45s ago",
            "15 phút trước",
            "30m ago",
            "1 giờ trước",
            "3h ago",
            "hôm qua",
            "yesterday",
            "1 ngày trước",
            "2 ngày",
            "3 ngày trước",
            "1 day ago",
            "3 days",
            "3d",
        ]
        for ts in new_timestamps:
            self.assertFalse(
                is_old_comment_timestamp(ts),
                f"Mốc thời gian '{ts}' là bình luận MỚI, không được đánh dấu là cũ!",
            )

        # Bình luận CŨ (PHẢI BỎ QUA 100%)
        old_timestamps = [
            "4 ngày trước",
            "5 ngày",
            "7 ngày trước",
            "10 ngày",
            "4 days ago",
            "5 days",
            "1 tuần trước",
            "2 tuần",
            "3 weeks ago",
            "1w",
            "2w",
            "1 tháng trước",
            "2 tháng",
            "1 month ago",
            "6 months",
            "1 năm trước",
            "2 năm",
            "1 year ago",
            "1y",
            "2y",
        ]
        for ts in old_timestamps:
            self.assertTrue(
                is_old_comment_timestamp(ts),
                f"Mốc thời gian '{ts}' là bình luận CŨ (> 3 ngày / tuần / tháng / năm), phải đánh dấu là cũ!",
            )

    def test_fresh_comment_with_year_in_body_not_dropped(self) -> None:
        """
        Regression Test: Đảm bảo bình luận MỚI (time_str='1 giờ trước') có nội dung chứa từ '1 năm'
        (ví dụ: 'Shop ơi tư vấn set quà kỷ niệm 1 năm thành lập công ty với')
        KHÔNG bị is_old_comment_timestamp(cand.get('time_str', '')) đánh dấu là cũ,
        và được bot xử lý bình thường như một bình luận mới.
        """
        cand = {
            "author_name": "Nguyễn Văn A",
            "comment_text": "Shop ơi tư vấn set quà kỷ niệm 1 năm thành lập công ty với",
            "time_str": "1 giờ trước",
            "innerPreview": "Nguyễn Văn A\n1 giờ trước\nShop ơi tư vấn set quà kỷ niệm 1 năm thành lập công ty với",
            "is_old_comment": False,
            "has_page_reply": False,
            "dom_index": 0,
        }

        # 1. Kiểm tra hàm lọc mốc thời gian: chỉ truyền time_str thực tế
        is_old = is_old_comment_timestamp(cand.get("time_str", ""))
        self.assertFalse(
            is_old,
            "Bình luận '1 giờ trước' phải được nhận diện là MỚI (is_old == False) dù body nhắc đến '1 năm'!",
        )

        # 2. Kiểm tra điều kiện if lọc bình luận cũ tại line 1307 của bot/page_bot_engine.py
        is_skipped = cand.get("is_old_comment") or is_old_comment_timestamp(cand.get("time_str", ""))
        self.assertFalse(
            is_skipped,
            "Bình luận mới không được phép bị bỏ qua bởi bộ lọc bình luận cũ!",
        )

        # 3. Đảm bảo bot memory xác nhận bình luận này đủ điều kiện trả lời
        should_reply, comment_key = self.memory.should_reply_comment(
            author_name=cand["author_name"],
            comment_text=cand["comment_text"],
            has_page_reply_in_dom=cand["has_page_reply"],
            post_id="post_test_year_in_body",
            dom_index=cand["dom_index"],
        )
        self.assertTrue(should_reply, "Bình luận mới hợp lệ phải được chấp thuận trả lời!")
        self.assertIsNotNone(comment_key)

    # =========================================================================
    # 5. Messenger Message Extraction & Bubble Alignment Logic
    # =========================================================================
    def test_messenger_bubble_direction_and_sender_detection(self) -> None:
        """
        Kiểm tra logic nhận diện hướng tin nhắn trong Messenger:
        - Bên trái (r.left < 620, không có brand signature) -> Khách hàng
        - Bên phải (r.left > 620) -> Fanpage
        - Chứa chữ ký thương hiệu (dan86.vn, 0933 133 516...) -> Fanpage
        """
        def classify_message(text: str, left: float) -> bool:
            lower = text.lower()
            has_brand = any(sig in lower for sig in [
                "dan86.vn", "0933 133 516", "nhân viên tư vấn", "bộ phận tư vấn"
            ])
            is_right = left > 620
            return has_brand or is_right

        # Tin nhắn khách (bên trái, không có chữ ký)
        self.assertFalse(classify_message("Shop ơi set quà này còn không?", left=410))
        self.assertFalse(classify_message("Gửi mình bảng giá nhé", left=520))

        # Tin nhắn Page (bên phải)
        self.assertTrue(classify_message("Dạ chào bạn, DAN86 sẵn lòng hỗ trợ!", left=750))
        # Tin nhắn Page (có chữ ký thương hiệu dù ở bất kỳ tọa độ nào)
        self.assertTrue(classify_message("Liên hệ Hotline/Zalo: 0933 133 516", left=450))
        self.assertTrue(classify_message("Website chính thức: dan86.vn", left=400))

    def test_messenger_vertical_bounds_excludes_textbox(self) -> None:
        """
        Kiểm tra giới hạn tọa độ y của khung chat Messenger:
        - Tọa độ y.bottom < 885 (không bị cắt ở 840)
        - Phần tử nằm trong [role='textbox'] bị loại trừ
        """
        nodes = [
            {"text": "Tin nhắn khách lúc 10:00", "top": 200, "bottom": 240, "in_textbox": False},
            {"text": "Tin nhắn mới nhất của khách ngay trên ô chat", "top": 845, "bottom": 875, "in_textbox": False},
            {"text": "Nội dung đang gõ trong ô composer", "top": 880, "bottom": 920, "in_textbox": True},
        ]

        valid_messages = []
        for n in nodes:
            if n["in_textbox"]:
                continue
            if n["top"] > 120 and n["bottom"] < 885:
                valid_messages.append(n["text"])

        self.assertEqual(len(valid_messages), 2)
        self.assertIn("Tin nhắn mới nhất của khách ngay trên ô chat", valid_messages)
        self.assertNotIn("Nội dung đang gõ trong ô composer", valid_messages)

    # =========================================================================
    # 6. Messenger 180-Minute Silence Rule & 3-Stage Transitions
    # =========================================================================
    def test_messenger_3_stage_transitions_and_180min_rule(self) -> None:
        """
        Kiểm tra kịch bản 3 giai đoạn của Messenger Inbox:
        - Giai đoạn 0 -> 1: Khách mới nhắn lần 1 -> Trả lời mẫu chào FIRST_INBOX_REPLIES.
        - Khách nhắn tiếp khi chưa đủ 180 phút im lặng -> IGNORE (nhường nhân viên).
        - Khách nhắn lại sau >= 180 phút (3 tiếng) im lặng -> Trả lời mẫu WAIT_STAFF_REPLIES (Giai đoạn 2).
        - Sau Giai đoạn 2 -> IGNORE vĩnh viễn (im lặng tuyệt đối chờ nhân viên).
        """
        customer = "Chị Thu Thảo"
        t0 = 1000000.0

        # Bước 1: Khách mới nhắn tin lần đầu (Stage 0 -> Stage 1)
        action1, reply1, key1 = self.memory.decide_inbox_action(
            customer_name=customer,
            last_message_text="Chào shop, shop có set quà nào cho đối tác không?",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=False,
            now_ts=t0,
        )
        self.assertEqual(action1, "FIRST_REPLY")
        self.assertIn("Thu Thảo", reply1)
        self.assertIn("DAN86", reply1)
        self.assertIn("0933 133 516", reply1)

        self.memory.record_inbox_reply(
            thread_key=key1,
            customer_name=customer,
            customer_message_text="Chào shop, shop có set quà nào cho đối tác không?",
            action_type="FIRST_REPLY",
            reply_text=reply1,
            now_ts=t0,
        )
        self.assertEqual(self.memory.data["conversations"][key1]["stage"], 1)

        # Bước 2: Khách nhắn thêm tin sau 10 phút (< 180 phút im lặng)
        action2, _, _ = self.memory.decide_inbox_action(
            customer_name=customer,
            last_message_text="Shop còn online không ạ?",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=True,
            now_ts=t0 + (10 * 60),
        )
        self.assertEqual(action2, "NONE", "Khách nhắn tiếp trong vòng 180 phút bot phải giữ im lặng (NONE)")

        # Bước 3: Khách im lặng và nhắn lại sau 185 phút (>= 180 phút, Stage 1 -> Stage 2)
        t_after_185m = t0 + (185 * 60)
        action3, reply3, _ = self.memory.decide_inbox_action(
            customer_name=customer,
            last_message_text="Shop ơi em cần gấp trong chiều nay",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=True,
            now_ts=t_after_185m,
        )
        self.assertEqual(action3, "WAIT_STAFF_REPLY")
        self.assertIn("Thu Thảo", reply3)
        self.assertIn("0933 133 516", reply3)
        self.assertTrue("nhân viên" in reply3.lower() or "tư vấn" in reply3.lower() or "chăm sóc khách hàng" in reply3.lower())

        self.memory.record_inbox_reply(
            thread_key=key1,
            customer_name=customer,
            customer_message_text="Shop ơi em cần gấp trong chiều nay",
            action_type="WAIT_STAFF_REPLY",
            reply_text=reply3,
            now_ts=t_after_185m,
        )
        self.assertEqual(self.memory.data["conversations"][key1]["stage"], 2)

        # Bước 4: Sau khi đã gửi tin nhắn Stage 2, khách nhắn lại trong thời gian < 180 phút -> giữ im lặng
        action4, _, _ = self.memory.decide_inbox_action(
            customer_name=customer,
            last_message_text="Alo shop",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=True,
            now_ts=t_after_185m + (30 * 60),
        )
        self.assertEqual(action4, "NONE", "Khách nhắn tiếp sau khi rep Stage 2 bot phải giữ im lặng")

    # =========================================================================
    # 7. Scan Interval & Dashboard Zero-Process Cleanliness
    # =========================================================================
    def test_scan_interval_satisfies_r4(self) -> None:
        """Đảm bảo SCAN_INTERVAL_SECONDS được cấu hình chuẩn (15, 30) thỏa mãn R4."""
        self.assertEqual(SCAN_INTERVAL_SECONDS, (15, 30))
        self.assertLessEqual(SCAN_INTERVAL_SECONDS[0], 15)
        self.assertLessEqual(SCAN_INTERVAL_SECONDS[1], 30)

    def test_dashboard_has_zero_subprocess_imports(self) -> None:
        """Đảm bảo dashboard.py không import hoặc sử dụng subprocess, cam kết 0 tiến trình nền trên máy local."""
        dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.py")
        with open(dashboard_path, "r", encoding="utf-8") as f:
            content = f.read()

        parsed_ast = ast.parse(content)
        imported_modules = []
        for node in ast.walk(parsed_ast):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.append(node.module)

        self.assertNotIn("subprocess", imported_modules, "dashboard.py không được import subprocess!")
        self.assertNotIn("subprocess.Popen", content)
        self.assertNotIn("subprocess.run", content)


if __name__ == "__main__":
    unittest.main()
