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

    def test_r5_messenger_conversation_customer_mentioning_website_not_misclassified(self):
        """
        R5: Đảm bảo khách hàng nhắn tin chứa từ khóa 'dan86.vn' hoặc 'nhân viên tư vấn'
        KHÔNG bao giờ bị nhận diện nhầm là tin nhắn của Page (isPage=False, last_sender_is_page=False).
        """
        import asyncio
        from playwright.async_api import async_playwright
        from bot.page_bot_engine import inspect_messenger_conversation

        async def run_async():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": 1280, "height": 800})

                # Test A: Khách gửi câu hỏi chứa link dan86.vn ở lề trái (x: 390px)
                html_customer_inquiry = """
                <!DOCTYPE html>
                <html>
                <body>
                  <div role="complementary" style="position: absolute; left: 1150px; top: 100px;">
                    <h2>Trần Gia Linh</h2>
                  </div>
                  <div style="position: absolute; left: 390px; top: 200px; width: 300px; height: 50px;" dir="auto">
                    Shop ơi em xem trên web dan86.vn có set quà này không ạ?
                  </div>
                </body>
                </html>
                """
                await page.set_content(html_customer_inquiry)
                conv_info = await inspect_messenger_conversation(page)
                self.assertEqual(conv_info["customer_name"], "Trần Gia Linh")
                self.assertFalse(conv_info["last_sender_is_page"], "Tin nhắn hỏi về dan86.vn ở lề trái KHÔNG ĐƯỢC coi là của Page!")
                self.assertFalse(conv_info["has_prior_page_messages"])
                self.assertIn("dan86.vn", conv_info["last_message_text"])

                # Test B: Khách hỏi 'Cho em gặp nhân viên tư vấn' ở lề trái
                html_customer_staff = """
                <!DOCTYPE html>
                <html>
                <body>
                  <div role="complementary" style="position: absolute; left: 1150px; top: 100px;">
                    <h2>Huỳnh Chí Đông Hải</h2>
                  </div>
                  <div style="position: absolute; left: 390px; top: 200px; width: 300px; height: 50px;" dir="auto">
                    Cho em gặp nhân viên tư vấn về đơn quà sỉ nhé
                  </div>
                </body>
                </html>
                """
                await page.set_content(html_customer_staff)
                conv_info_staff = await inspect_messenger_conversation(page)
                self.assertEqual(conv_info_staff["customer_name"], "Huỳnh Chí Đông Hải")
                self.assertFalse(conv_info_staff["last_sender_is_page"], "Khách hỏi nhân viên tư vấn ở lề trái KHÔNG ĐƯỢC coi là của Page!")

                # Test C: Tin nhắn của Fanpage ở lề phải (x: 650px)
                html_page_reply = """
                <!DOCTYPE html>
                <html>
                <body>
                  <div role="complementary" style="position: absolute; left: 1150px; top: 100px;">
                    <h2>Vy Vy</h2>
                  </div>
                  <!-- Tin 1: Khách gửi -->
                  <div style="position: absolute; left: 390px; top: 200px; width: 250px; height: 40px;" dir="auto">
                    Chào shop
                  </div>
                  <!-- Tin 2: Page rep ở lề phải -->
                  <div style="position: absolute; left: 650px; top: 260px; width: 400px; height: 60px;" dir="auto">
                    Dạ DAN86 xin chào Vy Vy! Mời bạn xem tại https://dan86.vn nha!
                  </div>
                </body>
                </html>
                """
                await page.set_content(html_page_reply)
                conv_page = await inspect_messenger_conversation(page)
                self.assertTrue(conv_page["last_sender_is_page"], "Tin nhắn của shop ở lề phải PHẢI được nhận diện là Page!")

                # Test D: Fanpage đã gửi tin nhắn trước đó, khách nhắn lại ở lề trái
                html_customer_followup = """
                <!DOCTYPE html>
                <html>
                <body>
                  <div role="complementary" style="position: absolute; left: 1150px; top: 100px;">
                    <h2>Vy Vy</h2>
                  </div>
                  <!-- Tin 1: Page chào -->
                  <div style="position: absolute; left: 650px; top: 200px; width: 400px; height: 60px;" dir="auto">
                    Dạ DAN86 xin chào Vy Vy!
                  </div>
                  <!-- Tin 2: Khách nhắn lại -->
                  <div style="position: absolute; left: 390px; top: 280px; width: 250px; height: 40px;" dir="auto">
                    Mình muốn đặt 10 set
                  </div>
                </body>
                </html>
                """
                await page.set_content(html_customer_followup)
                conv_followup = await inspect_messenger_conversation(page)
                self.assertFalse(conv_followup["last_sender_is_page"], "Khách nhắn lại thì người gửi cuối PHẢI là khách (False)!")
                self.assertTrue(conv_followup["has_prior_page_messages"], "Trước đó shop đã gửi tin nên has_prior_page_messages PHẢI là True!")

                await browser.close()

        asyncio.run(run_async())
