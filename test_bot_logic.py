"""
Bộ kiểm thử tự động (Unit Tests) cho Logic Bot Trực Fanpage DAN86 24/24:
1. Kiểm tra Random không trùng lặp liên tiếp (Anti-Repeat Randomizer).
2. Kiểm tra trả lời Comment đúng 1 lần duy nhất + Tự động Inbox người Comment.
3. Kiểm tra Liên thông từ Comment sang Inbox (Khách được inbox từ comment khi nhắn lại sẽ nhận câu "Đợi nhân viên").
4. Kiểm tra Kịch bản 3 Giai đoạn trong Messenger Inbox (Chào lần 1 -> Báo đợi nhân viên -> Im lặng chờ nhân viên).
"""

import os
import tempfile
import unittest

from bot.bot_config import (
    COMMENT_REPLIES,
    FIRST_INBOX_REPLIES,
    PRIVATE_REPLIES_FROM_COMMENT,
    SILENCE_REMINDER_MINUTES,
    WAIT_STAFF_REPLIES,
    pick_template,
)
from bot.memory_store import BotMemoryStore


class TestDan86BotLogic(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mem_path = os.path.join(self.temp_dir.name, "test_memory.json")
        self.memory = BotMemoryStore(memory_path=self.mem_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_01_non_repeating_random_templates(self) -> None:
        """Đảm bảo 2 lượt liên tiếp không bao giờ chọn trùng cùng 1 câu trả lời."""
        for category, pool in [
            ("cmt", COMMENT_REPLIES),
            ("priv", PRIVATE_REPLIES_FROM_COMMENT),
            ("first", FIRST_INBOX_REPLIES),
            ("wait", WAIT_STAFF_REPLIES),
        ]:
            prev = None
            for _ in range(25):
                curr = pick_template(pool, customer_name="Chị Lan", category_key=category)
                self.assertIn("Chị Lan", curr)
                self.assertNotEqual(curr, prev, f"Bị trùng mẫu câu liên tiếp ở nhóm {category}")
                prev = curr

    def test_02_comment_reply_once_and_auto_inbox(self) -> None:
        """Đảm bảo bình luận chỉ được rep 1 lần duy nhất + gửi kèm inbox riêng."""
        should_rep, key = self.memory.should_reply_comment(
            author_name="Nguyễn Văn A",
            comment_text="Shop báo giá set quà 20/10 giúp mình nhé",
            has_page_reply_in_dom=False,
        )
        self.assertTrue(should_rep)

        pub_reply, priv_reply = self.memory.prepare_comment_and_inbox_replies("Nguyễn Văn A")
        self.assertIn("Nguyễn Văn A", pub_reply)
        self.assertIn("dan86.vn", priv_reply)

        self.memory.mark_comment_replied(
            comment_key=key,
            author_name="Nguyễn Văn A",
            comment_text="Shop báo giá set quà 20/10 giúp mình nhé",
            public_reply=pub_reply,
            private_inbox_sent=True,
            private_reply_text=priv_reply,
            now_ts=1000.0,
        )

        # Quét lại bình luận đó lần 2 -> Phải bỏ qua (False)
        should_rep_again, _ = self.memory.should_reply_comment(
            author_name="Nguyễn Văn A",
            comment_text="Shop báo giá set quà 20/10 giúp mình nhé",
            has_page_reply_in_dom=False,
        )
        self.assertFalse(should_rep_again)

        # Khi khách "Nguyễn Văn A" (đã nhận inbox tự động từ comment) nhắn lại trong Messenger
        # -> Bot phải gửi câu "Đợi nhân viên sẽ liên hệ lại ngay" (WAIT_STAFF_REPLY), không chào lặp lại lần 1!
        action, reply_text, _ = self.memory.decide_inbox_action(
            customer_name="Nguyễn Văn A",
            last_message_text="Mình muốn đặt 50 phần quà cho công ty",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=True,
            now_ts=1060.0,
        )
        self.assertEqual(action, "WAIT_STAFF_REPLY")
        self.assertIn("0933 133 516", reply_text)

    def test_03_inbox_three_stage_conversation_flow(self) -> None:
        """Kiểm tra luồng 3 giai đoạn: Nhắn lần 1 -> Nhắn lại báo đợi nhân viên -> Im lặng chờ nhân viên."""
        t0 = 10000.0

        # Giai đoạn 1: Khách nhắn lần đầu tiên
        action1, reply1, t_key = self.memory.decide_inbox_action(
            customer_name="Anh Minh",
            last_message_text="Chào shop, tư vấn giúp mình set quà mây tre",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=False,
            thread_id="thread_999",
            now_ts=t0,
        )
        self.assertEqual(action1, "FIRST_REPLY")
        self.memory.record_inbox_reply(
            thread_key=t_key,
            customer_name="Anh Minh",
            customer_message_text="Chào shop, tư vấn giúp mình set quà mây tre",
            action_type=action1,
            reply_text=reply1,
            now_ts=t0,
        )

        # Ngay sau đó nếu tin nhắn cuối vẫn là của Page (hoặc khách chưa nhắn câu mới) -> NONE
        action_same, _, _ = self.memory.decide_inbox_action(
            customer_name="Anh Minh",
            last_message_text="Chào shop, tư vấn giúp mình set quà mây tre",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=True,
            thread_id="thread_999",
            now_ts=t0 + 30,
        )
        self.assertEqual(action_same, "NONE")

        # Giai đoạn 2: Khách im một lúc (ví dụ 5 phút) rồi nhắn lại câu mới -> Gửi mẫu "Đợi nhân viên sẽ liên hệ lại ngay"
        t1 = t0 + 300
        action2, reply2, _ = self.memory.decide_inbox_action(
            customer_name="Anh Minh",
            last_message_text="Shop có xuất hóa đơn VAT không ạ?",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=True,
            thread_id="thread_999",
            now_ts=t1,
        )
        self.assertEqual(action2, "WAIT_STAFF_REPLY")
        self.memory.record_inbox_reply(
            thread_key=t_key,
            customer_name="Anh Minh",
            customer_message_text="Shop có xuất hóa đơn VAT không ạ?",
            action_type=action2,
            reply_text=reply2,
            now_ts=t1,
        )

        # Giai đoạn 3: Khách nhắn tiếp câu nữa khi đang chờ nhân viên (sau 2 phút) -> Bot phải giữ im lặng (NONE)
        action3, _, _ = self.memory.decide_inbox_action(
            customer_name="Anh Minh",
            last_message_text="Gửi mẫu qua Zalo số 0909123456 giúp mình nha",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=True,
            thread_id="thread_999",
            now_ts=t1 + 120,
        )
        self.assertEqual(action3, "NONE")

        # Nhưng nếu khách im lặng rất lâu (> 120 phút) rồi mới nhắn lại hỏi thăm -> Nhắc lại câu đợi nhân viên 1 lần
        t_long = t1 + (SILENCE_REMINDER_MINUTES * 60) + 60
        action4, reply4, _ = self.memory.decide_inbox_action(
            customer_name="Anh Minh",
            last_message_text="Alo shop ơi có ai trực không ạ?",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=True,
            thread_id="thread_999",
            now_ts=t_long,
        )
        self.assertEqual(action4, "WAIT_STAFF_REPLY")
        self.assertIn("Anh Minh", reply4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
