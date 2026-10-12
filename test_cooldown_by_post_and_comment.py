import os
import shutil
import tempfile
import time
import unittest

from bot.memory_store import BotMemoryStore


class TestCooldownByPostAndComment(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.memory_file = os.path.join(self.test_dir, "test_memory.json")
        self.memory = BotMemoryStore(memory_path=self.memory_file)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_reply_immediately_on_different_posts(self):
        """Khách bình luận ở bài A, sau đó bình luận ngay ở bài B -> Không bị cooldown, rep ngay!"""
        t0 = 1000000.0
        author = "Đức Trí"
        post_a = "post_101"
        post_b = "post_202"

        # Ghi nhận phản hồi ở bài A
        self.memory.mark_comment_replied(
            comment_key="cmt:post_101:0:hash1",
            author_name=author,
            comment_text="Có set quà trà hoa cúc không?",
            public_reply="Dạ chào Đức Trí...",
            private_inbox_sent=True,
            now_ts=t0,
            post_id=post_a,
            dom_index=0,
        )

        # 5 giây sau: Khách bình luận ở bài B
        in_cd_b = self.memory.is_customer_in_cooldown(
            customer_name=author,
            cooldown_seconds=60.0,
            now_ts=t0 + 5.0,
            post_id=post_b,
            comment_text="Bộ quà tết này giá sao shop?",
        )
        self.assertFalse(in_cd_b, "Khách bình luận ở bài viết khác PHẢI được rep ngay lập tức!")

    def test_reply_immediately_on_different_comment_same_post(self):
        """Trên cùng một bài, nếu khách bình luận nội dung mới -> Không bị cooldown!"""
        t0 = 1000000.0
        author = "Đức Trí"
        post_id = "post_101"

        self.memory.mark_comment_replied(
            comment_key="cmt:post_101:0:hash1",
            author_name=author,
            comment_text="Bao nhiêu một set ạ?",
            public_reply="Dạ chào Đức Trí...",
            private_inbox_sent=True,
            now_ts=t0,
            post_id=post_id,
            dom_index=0,
        )

        # 10 giây sau: Khách hỏi tiếp câu mới trên cùng bài viết
        in_cd_new_cmt = self.memory.is_customer_in_cooldown(
            customer_name=author,
            cooldown_seconds=60.0,
            now_ts=t0 + 10.0,
            post_id=post_id,
            comment_text="Có freeship Sài Gòn không bạn?",
        )
        self.assertFalse(in_cd_new_cmt, "Bình luận câu mới trên cùng bài viết PHẢI được rep ngay!")

    def test_prevent_spam_on_identical_comment_same_post_within_cooldown(self):
        """Bình luận y hệt trên cùng bài viết trong vòng 60s -> Cooldown chống spam lặp!"""
        t0 = 1000000.0
        author = "Đức Trí"
        post_id = "post_101"
        same_text = "Có set quà trà hoa cúc không?"

        self.memory.mark_comment_replied(
            comment_key="cmt:post_101:0:hash1",
            author_name=author,
            comment_text=same_text,
            public_reply="Dạ chào Đức Trí...",
            private_inbox_sent=True,
            now_ts=t0,
            post_id=post_id,
            dom_index=0,
        )

        in_cd_same = self.memory.is_customer_in_cooldown(
            customer_name=author,
            cooldown_seconds=60.0,
            now_ts=t0 + 20.0,
            post_id=post_id,
            comment_text=same_text,
        )
        self.assertTrue(in_cd_same, "Bình luận trùng nội dung trên cùng bài viết trong 60s phải kích hoạt cooldown chống spam!")


if __name__ == "__main__":
    unittest.main()
