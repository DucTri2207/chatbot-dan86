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
    clean_customer_name,
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

    def test_02_clean_customer_name_and_system_blacklist(self) -> None:
        """Kiểm tra xử lý lọc sạch tên hệ thống (Lỗi 1: Chỉ báo trạng thái online)."""
        # 1. Nhãn hệ thống đứng một mình -> Trả về danh xưng mặc định 'bạn'
        self.assertEqual(clean_customer_name("Chỉ báo trạng thái online"), "bạn")
        self.assertEqual(clean_customer_name("Đang hoạt động"), "bạn")
        self.assertEqual(clean_customer_name("Hoạt động 5 phút trước"), "bạn")

        # 2. Tên khách kèm nhãn trạng thái -> Tách lấy tên khách chuẩn
        self.assertEqual(clean_customer_name("Trí Đức\nChỉ báo trạng thái online"), "Trí Đức")
        self.assertEqual(clean_customer_name("Bình luận dưới tên Trí Đức vào 2 giờ trước"), "Trí Đức")

        # 3. Tác giả là nhãn hệ thống thì should_reply_comment phải bỏ qua ngay lập tức
        should_rep, _ = self.memory.should_reply_comment(
            author_name="Chỉ báo trạng thái online",
            comment_text="Đang hoạt động",
            has_page_reply_in_dom=False,
        )
        self.assertFalse(should_rep, "Bot không được phép rep thẻ chỉ báo trạng thái online")

    def test_03_comment_reply_once_and_auto_inbox(self) -> None:
        """Đảm bảo bình luận chỉ được rep 1 lần duy nhất + gửi kèm inbox riêng."""
        t0 = 1000.0
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
            now_ts=t0,
        )

        # Quét lại bình luận đó lần 2 -> Phải bỏ qua (False)
        should_rep_again, _ = self.memory.should_reply_comment(
            author_name="Nguyễn Văn A",
            comment_text="Shop báo giá set quà 20/10 giúp mình nhé",
            has_page_reply_in_dom=False,
        )
        self.assertFalse(should_rep_again)

        # Khách vừa nhận inbox từ comment, 1 phút sau nhắn lại trong Messenger:
        # Bot phải GIỮ IM LẶNG (NONE) để nhường nhân viên tư vấn chốt đơn!
        action_soon, _, _ = self.memory.decide_inbox_action(
            customer_name="Nguyễn Văn A",
            last_message_text="Mình muốn đặt 50 phần quà cho công ty",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=True,
            now_ts=t0 + 60.0,
        )
        self.assertEqual(action_soon, "NONE")

        # Chỉ khi cả 2 bên im lặng >= 180 phút (3 tiếng) mà khách nhắn lại tin mới:
        # Bot mới gửi câu WAIT_STAFF_REPLY duy nhất 1 lần!
        t_after_3h = t0 + (SILENCE_REMINDER_MINUTES * 60) + 10.0
        action_3h, reply_text, _ = self.memory.decide_inbox_action(
            customer_name="Nguyễn Văn A",
            last_message_text="Alo shop còn hàng không ạ?",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=True,
            now_ts=t_after_3h,
        )
        self.assertEqual(action_3h, "WAIT_STAFF_REPLY")
        self.assertIn("0933 133 516", reply_text)

    def test_04_inbox_exact_three_hour_silence_logic(self) -> None:
        """
        Kiểm tra Logic Lỗi 4 Messenger Inbox:
        - Khách nhắn lần đầu -> rep DUY NHẤT 1 tin chào/tư vấn rồi dừng hẳn nhường nhân viên.
        - Khách nhắn thêm tin thứ 2, thứ 3 trong 3 tiếng -> Bot vẫn im lặng tuyệt đối (NONE).
        - Chỉ khi cả 2 bên im lặng >= 3 tiếng (180 phút) khách nhắn lại -> rep DUY NHẤT 1 tin chờ nhân viên.
        - Sau đó lại dừng hẳn nhường nhân viên.
        """
        t0 = 10000.0

        # 1. Khách nhắn lần đầu tiên -> FIRST_REPLY
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

        # 2. Khách nhắn câu 2 sau 5 phút (t0 + 300s) -> Bot phải DỪNG HẲN (NONE) nhường nhân viên
        action2, _, _ = self.memory.decide_inbox_action(
            customer_name="Anh Minh",
            last_message_text="Shop có xuất hóa đơn VAT không ạ?",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=True,
            thread_id="thread_999",
            now_ts=t0 + 300,
        )
        self.assertEqual(action2, "NONE", "Khách nhắn câu 2 sau 5 phút phải trả về NONE nhường nhân viên")

        # 3. Khách nhắn câu 3 sau 1 tiếng (t0 + 3600s) -> Vẫn trong khoảng < 3 tiếng -> NONE
        action3, _, _ = self.memory.decide_inbox_action(
            customer_name="Anh Minh",
            last_message_text="Alo shop ơi check giúp mình với nha",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=True,
            thread_id="thread_999",
            now_ts=t0 + 3600,
        )
        self.assertEqual(action3, "NONE", "Khách nhắn sau 1 tiếng vẫn phải giữ im lặng nhường nhân viên")

        # 4. Khi cả 2 bên im lặng >= 180 phút (3 tiếng = 10,800s) khách nhắn lại câu mới -> WAIT_STAFF_REPLY
        t_after_3h = t0 + (180 * 60) + 1.0
        action4, reply4, _ = self.memory.decide_inbox_action(
            customer_name="Anh Minh",
            last_message_text="Có ai trực không shop ơi?",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=True,
            thread_id="thread_999",
            now_ts=t_after_3h,
        )
        self.assertEqual(action4, "WAIT_STAFF_REPLY", "Sau >= 3 tiếng im lặng, khách nhắn lại phải rep WAIT_STAFF_REPLY")
        self.assertIn("Anh Minh", reply4)

        # Ghi nhận bot đã rep WAIT_STAFF_REPLY
        self.memory.record_inbox_reply(
            thread_key=t_key,
            customer_name="Anh Minh",
            customer_message_text="Có ai trực không shop ơi?",
            action_type=action4,
            reply_text=reply4,
            now_ts=t_after_3h,
        )

        # 5. Ngay sau đó khách nhắn tiếp câu nữa (sau 2 phút) -> Lại dừng hẳn nhường nhân viên (NONE)
        action5, _, _ = self.memory.decide_inbox_action(
            customer_name="Anh Minh",
            last_message_text="Ok mình đợi nha",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=True,
            thread_id="thread_999",
            now_ts=t_after_3h + 120,
        )
        self.assertEqual(action5, "NONE", "Sau khi rep WAIT_STAFF_REPLY, bot phải dừng hẳn nhường nhân viên")


if __name__ == "__main__":
    unittest.main(verbosity=2)

