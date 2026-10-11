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
from bot.memory_store import BotMemoryStore, make_comment_key


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
        self.assertEqual(clean_customer_name("Online status indicator"), "bạn")
        self.assertEqual(clean_customer_name("Đang hoạt động"), "bạn")
        self.assertEqual(clean_customer_name("Active now"), "bạn")
        self.assertEqual(clean_customer_name("Ẩn"), "bạn")
        self.assertEqual(clean_customer_name("Trả lời"), "bạn")
        self.assertEqual(clean_customer_name("See Chat"), "bạn")

        # 2. Tên người thật chứa từ 'Ẩn' -> KHÔNG được lọc nhầm sang 'bạn'
        self.assertEqual(clean_customer_name("Nguyễn Văn Ẩn"), "Nguyễn Văn Ẩn")
        self.assertEqual(clean_customer_name("Hoàng Ẩn"), "Hoàng Ẩn")

        # 3. Tên khách kèm nhãn trạng thái hoặc aria-label -> Tách lấy tên khách chuẩn
        self.assertEqual(clean_customer_name("Trí Đức\nChỉ báo trạng thái online"), "Trí Đức")
        self.assertEqual(clean_customer_name("Bình luận dưới tên Trí Đức vào 2 giờ trước"), "Trí Đức")
        self.assertEqual(clean_customer_name("Comment by Trí Đức 2 hours ago"), "Trí Đức")
        self.assertEqual(clean_customer_name("Bình luận dưới tên Lệ Thuyền"), "Lệ Thuyền")

        # 4. Tác giả là nhãn hệ thống thì should_reply_comment phải bỏ qua ngay lập tức
        should_rep, _ = self.memory.should_reply_comment(
            author_name="Chỉ báo trạng thái online",
            comment_text="Đang hoạt động",
            has_page_reply_in_dom=False,
        )
        self.assertFalse(should_rep, "Bot không được phép rep thẻ chỉ báo trạng thái online")

        # 5. Tác giả là người thật tên Ẩn -> Phải cho phép trả lời
        should_rep_an, _ = self.memory.should_reply_comment(
            author_name="Nguyễn Văn Ẩn",
            comment_text="Set quà này giá bao nhiêu vậy shop?",
            has_page_reply_in_dom=False,
        )
        self.assertTrue(should_rep_an, "Người thật tên Ẩn phải được phép trả lời")

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

        # 6. Nhân viên thật vào trả lời khách tại t_staff = t_after_3h + 600s
        t_staff = t_after_3h + 600
        self.memory.touch_staff_interaction("Anh Minh", thread_id="thread_999", now_ts=t_staff)

        # 7. Khách nhắn tiếp sau 20 phút kể từ lúc nhân viên trả lời -> Bot phải giữ im lặng (NONE)
        action7, _, _ = self.memory.decide_inbox_action(
            customer_name="Anh Minh",
            last_message_text="Em cảm ơn anh chị",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=True,
            thread_id="thread_999",
            now_ts=t_staff + 1200,
        )
        self.assertEqual(action7, "NONE", "Nhân viên vừa chat nên trong vòng 3 tiếng bot không được can thiệp")

        # 8. Sau 3 tiếng 5 phút im lặng kể từ lúc nhân viên chat -> Khách nhắn lại -> Bot rep WAIT_STAFF_REPLY
        t_staff_after_3h = t_staff + (180 * 60) + 300
        action8, reply8, _ = self.memory.decide_inbox_action(
            customer_name="Anh Minh",
            last_message_text="Shop cho em xin số tài khoản chuyển tiền nhé",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=True,
            thread_id="thread_999",
            now_ts=t_staff_after_3h,
        )
        self.assertEqual(action8, "WAIT_STAFF_REPLY", "Sau 3 tiếng im lặng kể từ lúc nhân viên chat, khách nhắn lại phải rep WAIT_STAFF_REPLY")
        self.assertIn("Anh Minh", reply8)

    def test_05_multiple_comments_on_same_post_no_collision(self) -> None:
        """
        Kiểm tra sửa triệt để lỗi Miss bình luận trên cùng 1 bài viết:
        - Trên cùng post_id='857984003420300', có nhiều bình luận từ các khách khác nhau.
        - Sau khi rep bình luận #1 (Diễm Myy: '.'), bình luận #2 (Abegail Sarto: 'How much')
          và bình luận #3 (Đức Trí: '1 năm Ib') KHÔNG được bị bỏ qua!
        """
        post_id = "857984003420300"
        
        # 1. Bình luận 1: Diễm Myy
        should_rep1, key1 = self.memory.should_reply_comment(
            author_name="Diễm Myy",
            comment_text=".",
            has_page_reply_in_dom=False,
            post_id=post_id,
            dom_index=0,
        )
        self.assertTrue(should_rep1, "Bình luận 1 của Diễm Myy phải được trả lời")
        self.assertTrue(key1.startswith(f"cmt:{post_id}:0:"), f"Key 1 phải chứa post_id và dom_index 0: {key1}")
        
        # Bot trả lời bình luận 1
        self.memory.mark_comment_replied(
            comment_key=key1,
            author_name="Diễm Myy",
            comment_text=".",
            public_reply="Dạ chào Diễm Myy...",
            private_inbox_sent=True,
            private_reply_text="Dạ shop chào Diễm Myy ạ...",
        )
        
        # 2. Bình luận 2: Abegail Sarto trên CÙNG BÀI VIẾT (post_id) nhưng dom_index khác
        should_rep2, key2 = self.memory.should_reply_comment(
            author_name="Abegail Sarto",
            comment_text="How much",
            has_page_reply_in_dom=False,
            post_id=post_id,
            dom_index=2,
        )
        self.assertTrue(should_rep2, "Bình luận 2 của Abegail Sarto trên cùng bài viết KHÔNG ĐƯỢC BỊ BỎ QUA!")
        self.assertNotEqual(key1, key2, "Hai bình luận trên cùng bài viết phải có key khác nhau!")
        self.assertTrue(key2.startswith(f"cmt:{post_id}:2:"), f"Key 2 phải chứa post_id và dom_index 2: {key2}")

        # 3. Cùng 1 khách bình luận nhiều lần ở các vị trí khác nhau trên bài viết
        should_rep3, key3 = self.memory.should_reply_comment(
            author_name="Diễm Myy",
            comment_text="Shop còn hàng không?",
            has_page_reply_in_dom=False,
            post_id=post_id,
            dom_index=4,
        )
        self.assertTrue(should_rep3, "Cùng 1 khách bình luận câu khác ở vị trí khác vẫn phải được trả lời nếu chưa có rep bên dưới!")
        self.assertNotEqual(key1, key3)

    def test_06_short_and_sticker_comments_handled(self) -> None:
        """
        Kiểm tra hỗ trợ đầy đủ mọi bình luận kể cả 1 ký tự, icon, sticker, số, chữ ngắn:
        - Bình luận dấu chấm '.'
        - Bình luận sticker '[Sticker / GIPHY]'
        - Bình luận số '1'
        - Bình luận 'Ib'
        """
        post_id = "1164344392784258"
        for idx, (author, text) in enumerate([
            ("Lệ Thuyền", "[Sticker / GIPHY]"),
            ("Diễm Myy", "."),
            ("Khách A", "1"),
            ("Khách B", "Ib"),
            ("Khách C", "❤️"),
        ]):
            should_rep, key = self.memory.should_reply_comment(
                author_name=author,
                comment_text=text,
                has_page_reply_in_dom=False,
                post_id=post_id,
                dom_index=idx,
            )
            self.assertTrue(should_rep, f"Bình luận '{text}' của '{author}' không được bị bỏ qua!")
            self.assertTrue(key.startswith(f"cmt:{post_id}:{idx}:"))

    def test_07_multiple_candidates_scan_does_not_abort_on_skipped_comment(self) -> None:
        """
        Kiểm tra xử lý danh sách unreplied_candidates trên cùng 1 bài viết:
        - Candidate 0: Đã được rep trước đó (hoặc dính label hệ thống).
        - Candidate 1: Khách B mới bình luận.
        - Candidate 2: Khách C mới bình luận.
        Vòng lặp bot PHẢI bỏ qua Candidate 0 và tiếp tục chọn Candidate 1 và 2 để trả lời,
        tuyệt đối không được break sớm làm bỏ sót (miss) các bình luận còn lại!
        """
        post_id = "999888777666"
        
        # Đánh dấu Candidate 0 đã rep trong memory
        key0 = make_comment_key("Khách A", "Báo giá em với", post_id=post_id, dom_index=0)
        self.memory.mark_comment_replied(
            comment_key=key0,
            author_name="Khách A",
            comment_text="Báo giá em với",
            public_reply="Dạ chào bạn...",
            private_inbox_sent=True,
            private_reply_text="Dạ inbox...",
        )
        
        unreplied_candidates = [
            {"dom_index": 0, "author_name": "Khách A", "comment_text": "Báo giá em với"},
            {"dom_index": 2, "author_name": "Khách B", "comment_text": "Hộp mây tre còn không?"},
            {"dom_index": 3, "author_name": "Khách C", "comment_text": "Ib giá sỉ nha shop"},
        ]
        
        # Vòng 1: Candidate 0 bị skip, Candidate 1 phải được chọn
        selected_cand = None
        selected_key = None
        for cand in unreplied_candidates:
            s_rep, c_key = self.memory.should_reply_comment(
                author_name=cand["author_name"],
                comment_text=cand["comment_text"],
                has_page_reply_in_dom=False,
                post_id=post_id,
                dom_index=cand["dom_index"],
            )
            if s_rep:
                selected_cand = cand
                selected_key = c_key
                break
                
        self.assertIsNotNone(selected_cand, "Phải tìm thấy candidate tiếp theo cần trả lời!")
        self.assertEqual(selected_cand["author_name"], "Khách B", "Candidate 1 (Khách B) phải được chọn thay vì bị break sớm!")
        
        # Bot trả lời Candidate 1
        self.memory.mark_comment_replied(
            comment_key=selected_key,
            author_name="Khách B",
            comment_text="Hộp mây tre còn không?",
            public_reply="Dạ chào Khách B...",
            private_inbox_sent=True,
            private_reply_text="Dạ shop gửi ảnh...",
        )
        
        # Vòng 2: Cả Candidate 0 và 1 đều đã rep, Candidate 2 phải được chọn
        selected_cand_2 = None
        selected_key_2 = None
        for cand in unreplied_candidates:
            s_rep, c_key = self.memory.should_reply_comment(
                author_name=cand["author_name"],
                comment_text=cand["comment_text"],
                has_page_reply_in_dom=False,
                post_id=post_id,
                dom_index=cand["dom_index"],
            )
            if s_rep:
                selected_cand_2 = cand
                selected_key_2 = c_key
                break
                
        self.assertIsNotNone(selected_cand_2)
        self.assertEqual(selected_cand_2["author_name"], "Khách C", "Candidate 2 (Khách C) phải được chọn tiếp tục!")

    def test_08_old_comment_filtering_and_clean_text(self) -> None:
        """Kiểm tra nhận diện bình luận cũ (tuần, tháng, năm, > 3 ngày) và làm sạch tiền tố thời gian."""
        from bot.page_bot_engine import clean_comment_text, is_old_comment_timestamp

        # 1. Kiểm tra làm sạch tiền tố thời gian
        self.assertEqual(clean_comment_text("1 năm Ib"), "Ib")
        self.assertEqual(clean_comment_text("4 tuần Cho em xin giá ạ"), "Cho em xin giá ạ")
        self.assertEqual(clean_comment_text("2 giờ Giá bao nhiêu"), "Giá bao nhiêu")
        self.assertEqual(clean_comment_text("vừa xong Ib shop"), "Ib shop")
        self.assertEqual(clean_comment_text("1 ngày Giá sao"), "Giá sao")

        # 2. Kiểm tra nhận diện bình luận cũ
        self.assertTrue(is_old_comment_timestamp("1 năm Ib"))
        self.assertTrue(is_old_comment_timestamp("2 năm trước"))
        self.assertTrue(is_old_comment_timestamp("4 năm"))
        self.assertTrue(is_old_comment_timestamp("10 tuần"))
        self.assertTrue(is_old_comment_timestamp("3 tuần trước"))
        self.assertTrue(is_old_comment_timestamp("2 tháng"))
        self.assertTrue(is_old_comment_timestamp("4 ngày"))
        self.assertTrue(is_old_comment_timestamp("5 ngày trước"))

        # 3. Bình luận MỚI hợp lệ (<= 3 ngày) không bị coi là cũ
        self.assertFalse(is_old_comment_timestamp("3 ngày"))
        self.assertFalse(is_old_comment_timestamp("2 ngày"))
        self.assertFalse(is_old_comment_timestamp("1 ngày"))
        self.assertFalse(is_old_comment_timestamp("hôm qua"))
        self.assertFalse(is_old_comment_timestamp("2 giờ"))
        self.assertFalse(is_old_comment_timestamp("15 phút"))
        self.assertFalse(is_old_comment_timestamp("vừa xong"))

    def test_09_repeat_comment_from_previous_user(self) -> None:
        """
        Đảm bảo khách đã từng bình luận trong quá khứ khi có bình luận MỚI
        vẫn được trả lời bình thường (không bị chặn vĩnh viễn bởi lịch sử).
        """
        post_id = "post_100"
        author = "Đức Trí"

        # Lần 1: Khách bình luận và được rep
        should_rep_1, key_1 = self.memory.should_reply_comment(
            author_name=author,
            comment_text="Ib shop",
            has_page_reply_in_dom=False,
            post_id=post_id,
            dom_index=1,
            now_ts=1000.0,
        )
        self.assertTrue(should_rep_1)
        self.memory.mark_comment_replied(
            comment_key=key_1,
            author_name=author,
            comment_text="Ib shop",
            public_reply="Dạ chào bạn...",
            private_inbox_sent=True,
            now_ts=1000.0,
        )

        # Lần 2: Hôm sau (hoặc sau cooldown) khách quay lại bình luận câu MỚI trên cùng bài
        should_rep_2, key_2 = self.memory.should_reply_comment(
            author_name=author,
            comment_text="Có ship Hỏa tốc không shop?",
            has_page_reply_in_dom=False,
            post_id=post_id,
            dom_index=5,
            now_ts=2000.0,
        )
        self.assertTrue(should_rep_2, "Khách cũ bình luận câu mới phải được rep!")

        # Lần 3: Khách bình luận dấu chấm trên bài khác
        should_rep_3, key_3 = self.memory.should_reply_comment(
            author_name=author,
            comment_text=".",
            has_page_reply_in_dom=False,
            post_id="post_200",
            dom_index=2,
            now_ts=3000.0,
        )
        self.assertTrue(should_rep_3, "Khách cũ bình luận trên bài khác phải được rep!")

    def test_10_origins_preservation_and_secret_safety(self) -> None:
        """Đảm bảo origins (business.facebook.com) luôn được bảo toàn, không bị ghi đè làm mất phiên SSO."""
        import json
        from bot.auth_helper import export_github_secret_file, sync_facebook_credentials_from_dan86

        temp_storage = os.path.join(self.temp_dir.name, "fb_storage_state.json")
        temp_secret = os.path.join(self.temp_dir.name, "GITHUB_SECRET_VALUE.txt")
        temp_source = os.path.join(self.temp_dir.name, "source_cookies.json")

        # Giả lập state ban đầu đã có origins chứa business.facebook.com
        biz_origin = {
            "origin": "https://business.facebook.com",
            "localStorage": [{"name": "sso_token", "value": "xyz123"}],
        }
        initial_state = {
            "cookies": [
                {"name": "c_user", "value": "12345", "domain": ".facebook.com", "path": "/"},
                {"name": "xs", "value": "secretxs", "domain": ".facebook.com", "path": "/"},
            ],
            "origins": [biz_origin],
        }
        with open(temp_storage, "w", encoding="utf-8") as f:
            json.dump(initial_state, f)

        # Giả lập file source d:\dan86 chỉ có cookies và origins: []
        source_data = [
            {"name": "c_user", "value": "12345", "domain": ".facebook.com", "path": "/"},
            {"name": "xs", "value": "secretxs", "domain": ".facebook.com", "path": "/"},
        ]
        with open(temp_source, "w", encoding="utf-8") as f:
            json.dump(source_data, f)

        # Chạy sync không có CDP -> Phải bảo toàn origins hiện có, không lấy origins rỗng từ source đè lên
        res = sync_facebook_credentials_from_dan86(
            source_path=temp_source,
            storage_path=temp_storage,
            secret_path=temp_secret,
            use_cdp=False,
        )
        self.assertTrue(res.get("success"))

        with open(temp_storage, "r", encoding="utf-8") as f_res:
            res_state = json.load(f_res)
        has_biz = any("business.facebook.com" in o.get("origin", "") for o in res_state.get("origins", []))
        self.assertTrue(has_biz, "origins của business.facebook.com bắt buộc phải được bảo toàn!")

        # Kiểm tra export_github_secret_file không làm mất origins
        export_github_secret_file(temp_storage, temp_secret)
        import base64
        with open(temp_secret, "r", encoding="utf-8") as f_sec:
            sec_raw = f_sec.read().strip()
        sec_json = json.loads(base64.b64decode(sec_raw).decode("utf-8"))
        sec_has_biz = any("business.facebook.com" in o.get("origin", "") for o in sec_json.get("origins", []))
        self.assertTrue(sec_has_biz, "GITHUB_SECRET_VALUE.txt bắt buộc phải lưu đầy đủ business.facebook.com origins!")

    def test_11_customer_inquiry_with_year_month_not_rejected(self) -> None:
        """Đảm bảo khách hỏi mua set quà kỷ niệm 1 năm / 1 tháng KHÔNG bị lọc nhầm thành cmt cũ."""
        from bot.page_bot_engine import is_old_comment_timestamp

        # Khách hỏi set quà kỷ niệm 1 năm, nhưng timestamp đăng là "1 giờ trước"
        customer_text = "Shop ơi tư vấn set quà kỷ niệm 1 năm thành lập công ty với"
        time_str_new = "1 giờ trước"
        time_str_old = "3 tuần trước"

        # Nếu dùng time_str để lọc:
        self.assertFalse(is_old_comment_timestamp(time_str_new))
        self.assertTrue(is_old_comment_timestamp(time_str_old))

        # Tiền tố thời gian được cắt bỏ sạch, nhưng nội dung khách hỏi "1 năm" ở giữa câu vẫn giữ nguyên
        from bot.page_bot_engine import clean_comment_text
        self.assertEqual(clean_comment_text("1 giờ " + customer_text), customer_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)


