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
    Bộ kiểm thử Production Live và Chuẩn hóa Link Website (Bỏ SĐT, Messenger giữ https://dan86.vn, Comment loại bỏ link chống Meta ẩn cmt):
    R1: Mở khóa tương tác cho tất cả khách hàng (TEST_ONLY_AUTHOR_WHITELIST = []).
    R2: Anti-Spam Meta: COMMENT_REPLIES 100% KHÔNG chứa link web/URL. 3 nhóm Messenger giữ 100% https://dan86.vn.
    R3: Xác minh cơ chế pick_template chống lặp 2 câu liên tiếp và phân bố ngẫu nhiên.
    """

    def test_r1_whitelist_is_empty_in_production(self):
        """R1: Đảm bảo TEST_ONLY_AUTHOR_WHITELIST là rỗng [] để tiếp nhận toàn bộ khách hàng."""
        self.assertEqual(TEST_ONLY_AUTHOR_WHITELIST, [], "TEST_ONLY_AUTHOR_WHITELIST phải là list rỗng trong Production Live.")

    def test_r2_templates_contain_website_and_no_phone_or_hotline(self):
        """
        R2: 
        - COMMENT_REPLIES (Bình luận công khai): Tuyệt đối KHÔNG chứa bất kỳ link web/URL nào để tránh Meta ẩn comment.
        - 3 nhóm tin nhắn riêng Messenger: Bảo toàn 100% link website https://dan86.vn.
        - Toàn bộ template không chứa SĐT/Hotline/Zalo.
        """
        messenger_groups = {
            "PRIVATE_REPLIES_FROM_COMMENT": PRIVATE_REPLIES_FROM_COMMENT,
            "FIRST_INBOX_REPLIES": FIRST_INBOX_REPLIES,
            "WAIT_STAFF_REPLIES": WAIT_STAFF_REPLIES,
        }

        forbidden_keywords = ["0933", "133 516", "133516", "hotline", "zalo", "sđt", "số điện thoại"]
        forbidden_link_patterns = ["http://", "https://", "dan86.vn", "www.", ".vn", ".com"]

        # 1. Kiểm tra nhóm COMMENT_REPLIES (Anti-Spam Meta Comment)
        self.assertGreater(len(COMMENT_REPLIES), 0, "Nhóm COMMENT_REPLIES không được rỗng.")
        for idx, tmpl in enumerate(COMMENT_REPLIES):
            lower_tmpl = tmpl.lower()
            # Cấm SĐT và Hotline/Zalo
            for kw in forbidden_keywords:
                self.assertNotIn(
                    kw,
                    lower_tmpl,
                    f"COMMENT_REPLIES[{idx}] vẫn chứa từ khóa cấm '{kw}': {tmpl}",
                )
            # CẤM tuyệt đối mọi dạng link website trong bình luận công khai
            for link_pat in forbidden_link_patterns:
                self.assertNotIn(
                    link_pat,
                    lower_tmpl,
                    f"COMMENT_REPLIES[{idx}] vi phạm Anti-Spam (chứa link '{link_pat}'): {tmpl}",
                )
            # Phải có placeholder {name}
            self.assertIn("{name}", tmpl, f"COMMENT_REPLIES[{idx}] thiếu placeholder {{name}}: {tmpl}")
            formatted = tmpl.format(name="Đức Trí")
            self.assertIn("Đức Trí", formatted)
            self.assertNotIn("{name}", formatted)

        # 2. Kiểm tra 3 nhóm tin nhắn riêng Messenger (Bảo toàn 100% link https://dan86.vn)
        for group_name, templates in messenger_groups.items():
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
                if cat_key == "cmt":
                    self.assertNotIn("http", chosen.lower(), "Bình luận công khai KHÔNG ĐƯỢC CHỨA link!")
                    self.assertNotIn("dan86.vn", chosen.lower())
                else:
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
        """R4: Kiểm tra BotMemoryStore sinh tin nhắn phản hồi chuẩn (cmt không link, inbox có link)."""
        memory = BotMemoryStore()

        pub_rep, priv_rep = memory.prepare_comment_and_inbox_replies("Khách Hàng Mới")
        self.assertIn("Khách Hàng Mới", pub_rep)
        self.assertNotIn("http", pub_rep.lower(), "Bình luận công khai không chứa URL")
        self.assertNotIn("dan86.vn", pub_rep.lower(), "Bình luận công khai không chứa domain")
        self.assertIn("https://dan86.vn", priv_rep, "Inbox riêng phải chứa link website")
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

    def test_r6_clean_customer_name_emojis_and_whitelist_case_insensitivity(self):
        """
        R6: Đảm bảo clean_customer_name fallback về 'bạn' khi tên chỉ gồm emoji/ký tự đặc biệt,
        và thuật toán lọc whitelist hoạt động chuẩn xác không phân biệt hoa thường khi whitelist có cấu hình.
        """
        from bot.bot_config import clean_customer_name
        from bot.memory_store import normalize_text

        # 1. Tên chỉ toàn emoji hoặc ký tự đặc biệt
        self.assertEqual(clean_customer_name("🌸🌸"), "bạn")
        self.assertEqual(clean_customer_name("✨🌸🎋"), "bạn")
        self.assertEqual(clean_customer_name(":)))"), "bạn")
        self.assertEqual(clean_customer_name("---"), "bạn")
        self.assertEqual(clean_customer_name("???"), "bạn")

        # 2. Tên người thật hợp lệ có chữ
        self.assertEqual(clean_customer_name("Đức Trí"), "Đức Trí")
        self.assertEqual(clean_customer_name("Nguyễn Văn Ẩn"), "Nguyễn Văn Ẩn")

        # 3. Whitelist case-insensitivity với normalize_text
        whitelist_uppercase = ["Đức Trí", "DẦN86"]
        c_norm = normalize_text("nguyễn đức trí")
        self.assertTrue(any(normalize_text(w) in c_norm for w in whitelist_uppercase))

        c_norm_other = normalize_text("khách hàng lạ")
        self.assertFalse(any(normalize_text(w) in c_norm_other for w in whitelist_uppercase))
