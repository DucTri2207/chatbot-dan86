import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bot_config import (
    COMMENT_REPLIES,
    PRIVATE_REPLIES_FROM_COMMENT,
    FIRST_INBOX_REPLIES,
    WAIT_STAFF_REPLIES,
    TEST_ONLY_AUTHOR_WHITELIST,
    pick_template,
)
from bot.memory_store import BotMemoryStore


class TestProductionLiveAndWebsiteLinks(unittest.TestCase):
    """
    Bộ kiểm thử Production Live và Chuẩn hóa Link Website (Bỏ SĐT, chỉ để https://dan86.vn):
    R1: Mở khóa tương tác cho tất cả khách hàng (TEST_ONLY_AUTHOR_WHITELIST = []).
    R2: 100% template loại bỏ SĐT, Hotline, Zalo; tích hợp https://dan86.vn.
    R3: Xác minh cơ chế pick_template chống lặp 2 câu liên tiếp và phân bố ngẫu nhiên.
    """

    def test_r1_whitelist_is_empty_in_production(self):
        """R1: Đảm bảo TEST_ONLY_AUTHOR_WHITELIST là rỗng [] để tiếp nhận toàn bộ khách hàng."""
        self.assertEqual(TEST_ONLY_AUTHOR_WHITELIST, [], "TEST_ONLY_AUTHOR_WHITELIST phải là list rỗng trong Production Live.")

    def test_r2_templates_contain_website_and_no_phone_or_hotline(self):
        """R2: 100% template trong cả 4 nhóm đều chứa https://dan86.vn và KHÔNG chứa SĐT/Hotline/Zalo."""
        all_groups = {
            "COMMENT_REPLIES": COMMENT_REPLIES,
            "PRIVATE_REPLIES_FROM_COMMENT": PRIVATE_REPLIES_FROM_COMMENT,
            "FIRST_INBOX_REPLIES": FIRST_INBOX_REPLIES,
            "WAIT_STAFF_REPLIES": WAIT_STAFF_REPLIES,
        }

        forbidden_keywords = ["0933", "133 516", "133516", "hotline", "zalo", "sđt", "số điện thoại"]

        for group_name, templates in all_groups.items():
            self.assertGreater(len(templates), 0, f"Nhóm {group_name} không được rỗng.")
            for idx, tmpl in enumerate(templates):
                lower_tmpl = tmpl.lower()

                # Kiểm tra cấm SĐT và Hotline/Zalo
                for kw in forbidden_keywords:
                    self.assertNotIn(
                        kw,
                        lower_tmpl,
                        f"Nhóm {group_name}[{idx}] vẫn chứa từ khóa cấm '{kw}': {tmpl}",
                    )

                # Kiểm tra phải chứa link https://dan86.vn
                self.assertIn(
                    "https://dan86.vn",
                    tmpl,
                    f"Nhóm {group_name}[{idx}] thiếu link website https://dan86.vn: {tmpl}",
                )

                # Kiểm tra placeholder {name}
                self.assertIn(
                    "{name}",
                    tmpl,
                    f"Nhóm {group_name}[{idx}] thiếu placeholder {{name}}: {tmpl}",
                )

                # Kiểm tra format không bị lỗi cú pháp
                formatted = tmpl.format(name="Đức Trí")
                self.assertIn("Đức Trí", formatted)
                self.assertNotIn("{name}", formatted)

    def test_r3_pick_template_randomization_and_anti_repeat(self):
        """R3: pick_template không lặp 2 câu liên tiếp và chọn được nhiều mẫu câu khác nhau."""
        all_groups = {
            "cmt": COMMENT_REPLIES,
            "priv": PRIVATE_REPLIES_FROM_COMMENT,
            "first": FIRST_INBOX_REPLIES,
            "wait": WAIT_STAFF_REPLIES,
        }

        for cat_key, templates in all_groups.items():
            prev = None
            seen = set()
            iterations = 40

            for _ in range(iterations):
                chosen = pick_template(templates, customer_name="Anh Tuấn", category_key=cat_key)
                self.assertIn("Anh Tuấn", chosen)
                self.assertIn("https://dan86.vn", chosen)

                # Không lặp 2 câu liên tiếp
                if prev is not None and len(templates) > 1:
                    self.assertNotEqual(
                        chosen,
                        prev,
                        f"Nhóm {cat_key} bị trùng lặp mẫu câu 2 lượt liên tiếp!",
                    )
                prev = chosen
                seen.add(chosen)

            # Đảm bảo có tính ngẫu nhiên (chọn được ít nhất 2 mẫu khác nhau trong nhiều lượt)
            self.assertGreaterEqual(
                len(seen),
                min(2, len(templates)),
                f"Nhóm {cat_key} không có tính ngẫu nhiên phong phú qua {iterations} lượt.",
            )

    def test_r4_memory_store_integration(self):
        """R4: Kiểm tra BotMemoryStore sinh tin nhắn phản hồi với link website chuẩn."""
        memory = BotMemoryStore()

        pub_rep, priv_rep = memory.prepare_comment_and_inbox_replies("Khách Hàng Mới")
        self.assertIn("Khách Hàng Mới", pub_rep)
        self.assertIn("https://dan86.vn", pub_rep)
        self.assertIn("https://dan86.vn", priv_rep)
        self.assertNotIn("0933", pub_rep)
        self.assertNotIn("0933", priv_rep)

        action, first_rep, _ = memory.decide_inbox_action(
            customer_name="Khách Hàng Mới",
            last_message_text="Chào bạn",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=False,
        )
        self.assertEqual(action, "FIRST_REPLY")
        self.assertIn("https://dan86.vn", first_rep)
        self.assertNotIn("0933", first_rep)
