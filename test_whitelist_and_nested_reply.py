import subprocess
import unittest
from bot.bot_config import TEST_ONLY_AUTHOR_WHITELIST
from bot.memory_store import normalize_text


class TestWhitelistAndNestedReply(unittest.TestCase):

    def test_whitelist_empty_in_production_live(self):
        """Đảm bảo danh sách TEST_ONLY_AUTHOR_WHITELIST rỗng [] để phục vụ mọi khách hàng trong Production Live."""
        self.assertEqual(TEST_ONLY_AUTHOR_WHITELIST, [])

    def test_whitelist_matching_logic(self):
        """Đảm bảo thuật toán lọc whitelist hoạt động chính xác khi có danh sách whitelist."""
        sample_whitelist = ["đức trí", "duc tri", "trí đức", "tri duc"]
        allowed_authors = ["Đức Trí", "duc tri", "Trí Đức", "TRI DUC", "Nguyễn Đức Trí"]
        blocked_authors = ["Hoa Muongbien", "Lệ Thuyền", "Bach Mai", "Ba Loc Tran", "Khách Hàng Lạ"]

        for author in allowed_authors:
            norm = normalize_text(author)
            matches = any(w in norm for w in sample_whitelist)
            self.assertTrue(matches, f"Tác giả hợp lệ '{author}' phải được cho phép.")

        for author in blocked_authors:
            norm = normalize_text(author)
            matches = any(w in norm for w in sample_whitelist)
            self.assertFalse(matches, f"Tác giả lạ '{author}' phải bị chặn khi whitelist kích hoạt.")

    def test_inspect_comment_panel_js_execution_no_reference_error(self):
        """
        Đảm bảo đoạn mã JS trong inspect_comment_panel hoàn toàn không bị ReferenceError (như mBtn undefined),
        và logic phân loại has_page_reply / unreplied_comments chạy chính xác.
        """
        with open('bot/page_bot_engine.py', 'r', encoding='utf-8') as f:
            content = f.read()

        part = content.split('async def inspect_comment_panel')[1]
        js = part.split('js_code = r"""')[1].split('"""')[0]

        node_script = f"""
        const fn = {js};
        const makeEl = (aria, text, left = 350) => ({{
          getAttribute: (a) => a === "aria-label" ? aria : "",
          setAttribute: () => {{}},
          removeAttribute: () => {{}},
          innerText: text,
          children: [],
          querySelectorAll: () => [],
          querySelector: () => null,
          closest: () => null,
          getBoundingClientRect: () => ({{ left: left, top: 100, height: 50 }})
        }});
        const document = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Bình luận dưới tên Đức Trí vào 1 giờ trước", "Đức Trí\\n1 giờ\\n.\\nTrả lời\\nGửi tin nhắn\\nẨn", 350)
              ];
            }}
            return [];
          }}
        }};
        const window = {{ location: {{ search: "?comment_id=123" }} }};
        const URLSearchParams = class {{ get() {{ return "123"; }} }};
        const res = fn(["dan86"]);
        if (!res || typeof res !== 'object') {{
          throw new Error('Result invalid');
        }}
        if (res.unreplied_count !== 1) {{
          throw new Error('Expected unreplied_count == 1, got ' + res.unreplied_count);
        }}
        if (res.author_name !== 'Đức Trí') {{
          throw new Error('Expected author_name == Đức Trí, got ' + res.author_name);
        }}
        console.log("OK");
        """
        res = subprocess.run(["node", "-e", node_script], capture_output=True, text=True, check=True)
        self.assertIn("OK", res.stdout)

    def test_tag_comment_target_in_dom_excludes_view_replies(self):
        """
        Đảm bảo tag_comment_target_in_dom trong JS tuyệt đối KHÔNG gắn data-dan86-reply-btn
        vào các nút 'Xem phản hồi', 'Ẩn phản hồi' mà gắn chính xác vào nút 'Trả lời'.
        """
        with open('bot/page_bot_engine.py', 'r', encoding='utf-8') as f:
            content = f.read()

        part = content.split('async def tag_comment_target_in_dom')[1]
        js = part.split('js_tag = """')[1].split('"""')[0]

        node_script = f"""
        const fn = {js};
        const makeBtn = (text, aria = "") => {{
          const myAttrs = new Map();
          return {{
            innerText: text,
            getAttribute: (a) => a === "aria-label" ? aria : (myAttrs.get(a) || ""),
            setAttribute: (k, v) => myAttrs.set(k, v),
            removeAttribute: (k) => myAttrs.delete(k),
            closest: () => null,
            children: []
          }};
        }};

        const btnViewReplies = makeBtn("Xem 2 phản hồi", "Xem 2 phản hồi");
        const btnHideReplies = makeBtn("Ẩn phản hồi", "Ẩn phản hồi");
        const btnRealReply = makeBtn("Trả lời", "Trả lời");

        const targetAttrs = new Map();
        const targetArt = {{
          getAttribute: (k) => targetAttrs.get(k) || "",
          setAttribute: (k, v) => targetAttrs.set(k, v),
          removeAttribute: (k) => targetAttrs.delete(k),
          querySelectorAll: (sel) => [btnViewReplies, btnHideReplies, btnRealReply],
          scrollIntoView: () => {{}},
          getBoundingClientRect: () => ({{ left: 350, top: 100, height: 60 }})
        }};

        const document = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') return [targetArt];
            return [];
          }}
        }};

        const res = fn(0);
        if (!res) throw new Error("fn(0) should return true");
        if (btnViewReplies.getAttribute('data-dan86-reply-btn') === 'true') {{
          throw new Error("FAIL: btnViewReplies was tagged with data-dan86-reply-btn!");
        }}
        if (btnHideReplies.getAttribute('data-dan86-reply-btn') === 'true') {{
          throw new Error("FAIL: btnHideReplies was tagged with data-dan86-reply-btn!");
        }}
        if (btnRealReply.getAttribute('data-dan86-reply-btn') !== 'true') {{
          throw new Error("FAIL: btnRealReply was NOT tagged!");
        }}
        console.log("REPLY_BTN_OK");
        """
        res = subprocess.run(["node", "-e", node_script], capture_output=True, text=True, check=True)
        self.assertIn("REPLY_BTN_OK", res.stdout)

    async def _async_test_locate_nested_reply_box(self):
        from unittest.mock import AsyncMock, MagicMock
        from bot.page_bot_engine import locate_nested_reply_box

        page = MagicMock()
        target_art = MagicMock()
        target_art.count = AsyncMock(return_value=1)
        target_art.scroll_into_view_if_needed = AsyncMock()
        target_art.bounding_box = AsyncMock(return_value={"x": 350, "y": 200, "width": 400, "height": 60})

        # Test 1: Bottom post comment box (y = 850, far below target_art y = 200) -> MUST BE REJECTED
        bottom_box = MagicMock()
        bottom_box.count = AsyncMock(return_value=1)
        bottom_box.is_visible = AsyncMock(return_value=True)
        bottom_box.bounding_box = AsyncMock(return_value={"x": 350, "y": 850, "width": 400, "height": 45})
        bottom_box.get_attribute = AsyncMock(return_value="Viết câu trả lời...")
        bottom_box.evaluate = AsyncMock(return_value=True)

        target_art.locator = MagicMock(return_value=bottom_box)
        bottom_box.first = bottom_box
        page.locator = MagicMock(return_value=bottom_box)

        res_rejected = await locate_nested_reply_box(page, target_art, timeout_seconds=0.2)
        self.assertIsNone(res_rejected, "Ô bình luận bài viết ở đáy trang (Y=850) phải bị loại bỏ 100%!")

        # Test 2: Post-level box (aria = "Viết bình luận công khai...") -> MUST BE REJECTED
        post_level_box = MagicMock()
        post_level_box.count = AsyncMock(return_value=1)
        post_level_box.is_visible = AsyncMock(return_value=True)
        post_level_box.bounding_box = AsyncMock(return_value={"x": 350, "y": 270, "width": 400, "height": 45})
        post_level_box.get_attribute = AsyncMock(side_effect=lambda a: "Viết bình luận công khai..." if a == "aria-label" else "")
        post_level_box.evaluate = AsyncMock(return_value=True)
        target_art.locator = MagicMock(return_value=post_level_box)
        post_level_box.first = post_level_box
        page.locator = MagicMock(return_value=post_level_box)

        res_post_rejected = await locate_nested_reply_box(page, target_art, timeout_seconds=0.2)
        self.assertIsNone(res_post_rejected, "Ô có aria 'Viết bình luận công khai' phải bị loại bỏ 100%!")

        # Test 3: Genuine nested reply box (y = 275, directly below target_art y = 200) -> MUST BE ACCEPTED
        nested_box = MagicMock()
        nested_box.count = AsyncMock(return_value=1)
        nested_box.is_visible = AsyncMock(return_value=True)
        nested_box.bounding_box = AsyncMock(return_value={"x": 380, "y": 275, "width": 370, "height": 45})
        nested_box.get_attribute = AsyncMock(side_effect=lambda a: "Viết câu trả lời..." if a == "aria-label" else "")
        nested_box.evaluate = AsyncMock(return_value=True)
        target_art.locator = MagicMock(return_value=nested_box)
        nested_box.first = nested_box
        page.locator = MagicMock(return_value=nested_box)

        res_accepted = await locate_nested_reply_box(page, target_art, timeout_seconds=0.5)
        self.assertIsNotNone(res_accepted, "Ô nested reply lồng nhau sát dưới target_art (Y=275) phải được định vị thành công!")

    def test_locate_nested_reply_box_geometric_and_failsafe(self):
        import asyncio
        asyncio.run(self._async_test_locate_nested_reply_box())

    def test_r1_page_names_contain_full_display_aliases(self):
        """R1: Đảm bảo PAGE_NAMES chứa đầy đủ các tên hiển thị của Fanpage."""
        from bot.bot_config import PAGE_NAMES
        required_names = [
            "quà tặng thuần việt dan86",
            "quà tặng thuần việt",
            "dan86 - quà tặng thuần việt",
            "dan86 quà tặng thuần việt",
            "bá lộc green",
        ]
        for name in required_names:
            self.assertIn(name, PAGE_NAMES, f"PAGE_NAMES phải chứa '{name}'")

    def test_r2_retry_loop_locked_in_memory_store(self):
        """
        R2: Đảm bảo vòng lặp retry bị khóa vĩnh viễn:
        Khi bình luận đã có bản ghi trong replied_comments (kể cả Bỏ qua cmt công khai hay Đã phản hồi),
        should_reply_comment BẮT BUỘC trả về False, key ngay lập tức dù has_page_reply_in_dom là False.
        """
        import tempfile
        from bot.memory_store import BotMemoryStore

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            temp_path = tf.name

        mem = BotMemoryStore(memory_path=temp_path)
        post_id = "test_post_lock"
        author = "Nguyễn Văn Test"
        comment_text = "Tư vấn sản phẩm nhé shop"

        # Lần 1: Bình luận mới -> Được phép trả lời
        should_rep1, key1 = mem.should_reply_comment(
            author_name=author,
            comment_text=comment_text,
            has_page_reply_in_dom=False,
            post_id=post_id,
            dom_index=0,
        )
        self.assertTrue(should_rep1)

        # Giả lập bot đánh dấu bỏ qua cmt công khai (vì không tìm thấy ô lồng nhau)
        mem.mark_comment_replied(
            comment_key=key1,
            author_name=author,
            comment_text=comment_text,
            public_reply="(Bỏ qua cmt công khai - Không tìm thấy ô lồng nhau)",
            private_inbox_sent=True,
            private_reply_text="Inbox test",
            post_id=post_id,
            dom_index=0,
        )

        # Lần 2: Quét lại cùng bình luận khi DOM không có page reply -> KHÔNG ĐƯỢC RETRY (phải trả về False)
        should_rep2, key2 = mem.should_reply_comment(
            author_name=author,
            comment_text=comment_text,
            has_page_reply_in_dom=False,
            post_id=post_id,
            dom_index=0,
        )
        self.assertFalse(should_rep2, "Bình luận đã ghi nhận (Bỏ qua...) TUYỆT ĐỐI không được retry lặp lại!")
        self.assertEqual(key1, key2)

        # Thử lại với một bình luận khác đánh dấu (Đã phản hồi bình luận công khai)
        author_b = "Trần Thị Test"
        should_rep_b1, key_b1 = mem.should_reply_comment(
            author_name=author_b,
            comment_text="Hỏi giá",
            has_page_reply_in_dom=False,
            post_id=post_id,
            dom_index=1,
        )
        self.assertTrue(should_rep_b1)

        mem.mark_comment_replied(
            comment_key=key_b1,
            author_name=author_b,
            comment_text="Hỏi giá",
            public_reply="(Đã phản hồi bình luận công khai)",
            private_inbox_sent=True,
            private_reply_text="Inbox test b",
            post_id=post_id,
            dom_index=1,
        )

        should_rep_b2, _ = mem.should_reply_comment(
            author_name=author_b,
            comment_text="Hỏi giá",
            has_page_reply_in_dom=False,
            post_id=post_id,
            dom_index=1,
        )
        self.assertFalse(should_rep_b2, "Bình luận đã ghi nhận (Đã phản hồi...) TUYỆT ĐỐI không được retry!")

    def test_r1_inspect_comment_panel_author_badge_and_no_generic_reply_override(self):
        """
        R1: Kiểm tra JS inspect_comment_panel:
        1. Xóa bỏ 100% isGenericSystemReply: Page trả lời có chứa 'đã gửi tin nhắn cho bạn'
           vẫn BẮT BUỘC được tính là isPageReply = true -> unreplied_count = 0 (Chống trả lời đè).
        2. Nhận diện Fanpage theo tên đầy đủ 'Quà tặng thuần Việt DAN86'.
        3. Nhận diện huy hiệu Tác giả / Author.
        """
        with open('bot/page_bot_engine.py', 'r', encoding='utf-8') as f:
            content = f.read()

        part = content.split('async def inspect_comment_panel')[1]
        js = part.split('js_code = r"""')[1].split('"""')[0]

        from bot.bot_config import PAGE_NAMES
        import json
        page_names_json = json.dumps(PAGE_NAMES)

        node_script = f"""
        const fn = {js};
        const pageNames = {page_names_json};

        const makeEl = (aria, text, left = 350, querySelectorResult = null, querySelectorAllResult = null) => ({{
          getAttribute: (a) => a === "aria-label" ? aria : "",
          setAttribute: () => {{}},
          removeAttribute: () => {{}},
          innerText: text,
          children: [],
          querySelectorAll: (sel) => querySelectorAllResult ? querySelectorAllResult(sel) : [],
          querySelector: (sel) => querySelectorResult ? querySelectorResult(sel) : null,
          closest: () => null,
          getBoundingClientRect: () => ({{ left: left, top: 100, height: 50 }})
        }});

        // Scenario 1: Page trả lời chứa 'đã gửi tin nhắn cho bạn' -> BẮT BUỘC nhận diện isPageReply = true
        // Comment 1: Khách hàng (left=350)
        // Comment 2: Page reply lồng nhau (left=380) có tên 'Quà tặng thuần Việt DAN86' và câu 'Đã gửi tin nhắn cho bạn!'
        const doc1 = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Bình luận dưới tên Khách Hàng vào 2 giờ trước", "Khách Hàng\\n2 giờ\\nSet quà bao nhiêu\\nTrả lời\\nGửi tin nhắn\\nẨn", 350),
                makeEl("Bình luận dưới tên Quà tặng thuần Việt DAN86 vào 1 giờ trước", "Quà tặng thuần Việt DAN86\\n1 giờ\\nĐã gửi tin nhắn cho bạn!\\nTrả lời\\nẨn", 380)
              ];
            }}
            return [];
          }}
        }};
        global.document = doc1;
        global.window = {{ location: {{ search: "?selected_item_id=post_1" }} }};
        global.URLSearchParams = class {{ get() {{ return "post_1"; }} }};

        const res1 = fn(pageNames);
        if (res1.unreplied_count !== 0) {{
          throw new Error("Scenario 1 failed: Expected unreplied_count == 0, got " + res1.unreplied_count);
        }}

        // Scenario 2: Reply có huy hiệu 'Tác giả' -> BẮT BUỘC nhận diện isPageReply = true
        const doc2 = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Bình luận dưới tên Khách B vào 2 giờ trước", "Khách B\\n2 giờ\\nCho hỏi giá\\nTrả lời\\nGửi tin nhắn\\nẨn", 350),
                makeEl("Bình luận dưới tên Shop vào 1 giờ trước", "Shop\\nTác giả\\n1 giờ\\nDạ shop đã phản hồi nhé!\\nTrả lời\\nẨn", 380)
              ];
            }}
            return [];
          }}
        }};
        global.document = doc2;
        const res2 = fn(pageNames);
        if (res2.unreplied_count !== 0) {{
          throw new Error("Scenario 2 failed (Author badge in text): Expected unreplied_count == 0, got " + res2.unreplied_count);
        }}

        // Scenario 3: Article có DOM element badge tác giả (aria-label="Tác giả") -> BẮT BUỘC nhận diện isPageReply = true
        const doc3 = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Bình luận dưới tên Khách C vào 2 giờ trước", "Khách C\\n2 giờ\\nCho hỏi quà tết\\nTrả lời\\nGửi tin nhắn\\nẨn", 350),
                makeEl("Bình luận của Nick vào 1 giờ trước", "Nick\\n1 giờ\\nDạ chào bạn\\nTrả lời\\nẨn", 380, (sel) => {{
                  if (sel.includes('tác giả')) return {{ ariaLabel: 'Tác giả' }};
                  return null;
                }})
              ];
            }}
            return [];
          }}
        }};
        global.document = doc3;
        const res3 = fn(pageNames);
        if (res3.unreplied_count !== 0) {{
          throw new Error("Scenario 3 failed (Author badge in DOM querySelector): Expected unreplied_count == 0, got " + res3.unreplied_count);
        }}

        // Scenario 4 (Chống nhận nhầm): Khách hàng hỏi có nhắc chữ 'tác giả' trong câu hỏi
        const doc4 = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Bình luận dưới tên Khách Hàng vào 2 giờ trước", "Khách Hàng\\n2 giờ\\nChào shop\\ntác giả cho mình hỏi sản phẩm này\\nTrả lời\\nGửi tin nhắn\\nẨn", 350)
              ];
            }}
            return [];
          }}
        }};
        global.document = doc4;
        const res4 = fn(pageNames);
        if (res4.unreplied_count !== 1) {{
          throw new Error("Scenario 4 failed (Customer mentions tác giả in question): Expected unreplied_count == 1, got " + res4.unreplied_count);
        }}

        // Scenario 5 (Chống nhận nhầm): Khách hỏi về 'quà tặng thuần việt' xuống dòng
        const doc5 = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Bình luận dưới tên Nguyễn Thị Mai vào 2 giờ trước", "Nguyễn Thị Mai\\n2 giờ\\nShop ơi\\nquà tặng thuần việt\\ngiá bao nhiêu ạ\\nTrả lời\\nGửi tin nhắn\\nẨn", 350)
              ];
            }}
            return [];
          }}
        }};
        global.document = doc5;
        const res5 = fn(pageNames);
        if (res5.unreplied_count !== 1) {{
          throw new Error("Scenario 5 failed (Customer asks about quà tặng thuần việt on newline): Expected unreplied_count == 1, got " + res5.unreplied_count);
        }}

        // Scenario 6 (Chống nhận nhầm): Khách có tên Facebook là 'Author John'
        const doc6 = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Comment by Author John 2 hours ago", "Author John\\n2 hours ago\\nHow much is this set?\\nReply\\nSend message\\nHide", 350)
              ];
            }}
            return [];
          }}
        }};
        global.document = doc6;
        const res6 = fn(pageNames);
        if (res6.unreplied_count !== 1) {{
          throw new Error("Scenario 6 failed (Customer named Author John): Expected unreplied_count == 1, got " + res6.unreplied_count);
        }}

        // Scenario 7 (Chống nhận nhầm): Khách có tên Facebook là 'Tác Giả Nguyễn'
        const doc7 = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Bình luận dưới tên Tác Giả Nguyễn vào 2 giờ trước", "Tác Giả Nguyễn\\n2 giờ\\nSet này bao nhiêu tiền?\\nTrả lời\\nGửi tin nhắn\\nẨn", 350)
              ];
            }}
            return [];
          }}
        }};
        global.document = doc7;
        const res7 = fn(pageNames);
        if (res7.unreplied_count !== 1) {{
          throw new Error("Scenario 7 failed (Customer named Tác Giả Nguyễn): Expected unreplied_count == 1, got " + res7.unreplied_count);
        }}

        // Scenario 8 (Chống nhận nhầm): Khách hỏi câu 1 dòng bắt đầu bằng tên sản phẩm 'quà tặng thuần việt'
        const doc8 = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Bình luận dưới tên Lan Hương vào 5 phút trước", "Lan Hương\\n5 phút\\nquà tặng thuần việt giá bao nhiêu vậy shop?\\nTrả lời\\nGửi tin nhắn\\nẨn", 350)
              ];
            }}
            return [];
          }}
        }};
        global.document = doc8;
        const res8 = fn(pageNames);
        if (res8.unreplied_count !== 1 || res8.author_name !== "Lan Hương") {{
          throw new Error("Scenario 8 failed (Customer asks question starting with quà tặng thuần việt): Expected unreplied_count == 1, got " + res8.unreplied_count);
        }}

        // Scenario 9 (Chống nhận nhầm): Khách hỏi câu bắt đầu bằng thương hiệu 'Dan86'
        const doc9 = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Bình luận dưới tên Hoàng Nam vào 5 phút trước", "Hoàng Nam\\n5 phút\\nDan86 có set nào dưới 500k không?\\nTrả lời\\nGửi tin nhắn\\nẨn", 350)
              ];
            }}
            return [];
          }}
        }};
        global.document = doc9;
        const res9 = fn(pageNames);
        if (res9.unreplied_count !== 1 || res9.author_name !== "Hoàng Nam") {{
          throw new Error("Scenario 9 failed (Customer asks starting with Dan86): Expected unreplied_count == 1, got " + res9.unreplied_count);
        }}

        // Scenario 10 (Chống nhận nhầm): Khách hỏi câu kết thúc bằng từ khóa 'quà tặng thuần việt'
        const doc10 = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Bình luận dưới tên Bảo Anh vào 5 phút trước", "Bảo Anh\\n5 phút\\nTư vấn quà tặng thuần việt\\nTrả lời\\nGửi tin nhắn\\nẨn", 350)
              ];
            }}
            return [];
          }}
        }};
        global.document = doc10;
        const res10 = fn(pageNames);
        if (res10.unreplied_count !== 1 || res10.author_name !== "Bảo Anh") {{
          throw new Error("Scenario 10 failed (Customer asks ending with quà tặng thuần việt): Expected unreplied_count == 1, got " + res10.unreplied_count);
        }}

        // Scenario 11 (Chống nhận nhầm): Khách chỉ bình luận đúng 1 cụm từ 'Quà tặng thuần việt'
        const doc11 = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Bình luận dưới tên Quốc Huy vào 5 phút trước", "Quốc Huy\\n5 phút\\nQuà tặng thuần việt\\nTrả lời\\nGửi tin nhắn\\nẨn", 350)
              ];
            }}
            return [];
          }}
        }};
        global.document = doc11;
        const res11 = fn(pageNames);
        if (res11.unreplied_count !== 1 || res11.author_name !== "Quốc Huy") {{
          throw new Error("Scenario 11 failed (Customer comments only Quà tặng thuần việt): Expected unreplied_count == 1, got " + res11.unreplied_count);
        }}

        // Scenario 12 (Chống nhận nhầm): Khách chào 'Chào Dần 86'
        const doc12 = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Bình luận dưới tên Ngọc Mai vào 5 phút trước", "Ngọc Mai\\n5 phút\\nChào Dần 86\\nTrả lời\\nGửi tin nhắn\\nẨn", 350)
              ];
            }}
            return [];
          }}
        }};
        global.document = doc12;
        const res12 = fn(pageNames);
        if (res12.unreplied_count !== 1 || res12.author_name !== "Ngọc Mai") {{
          throw new Error("Scenario 12 failed (Customer says Chào Dần 86): Expected unreplied_count == 1, got " + res12.unreplied_count);
        }}

        // Scenario 13 (Huy hiệu tác giả dòng đầu): Page reply có chữ 'Tác giả' ở dòng 0 trước tên người quản lý/Shop
        const doc13 = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Bình luận dưới tên Khách Hàng vào 2 giờ trước", "Khách Hàng\\n2 giờ\\nCho mình hỏi giá\\nTrả lời\\nGửi tin nhắn\\nẨn", 350),
                makeEl("", "Tác giả\\nShop\\n1 giờ\\nDạ em đã nhắn tin ạ\\nTrả lời\\nẨn", 380)
              ];
            }}
            return [];
          }}
        }};
        global.document = doc13;
        const res13 = fn(pageNames);
        if (res13.unreplied_count !== 0) {{
          throw new Error("Scenario 13 failed (Tác giả badge on line 0): Expected unreplied_count == 0, got " + res13.unreplied_count);
        }}

        // Scenario 14 (Chống nhận nhầm): Khách hỏi câu bắt đầu bằng 'quà tặng thuần việt' nhưng innerText chỉ chứa câu hỏi, tên khách ở aria-label
        const doc14 = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Bình luận dưới tên Lan Hương vào 5 phút trước", "quà tặng thuần việt giá bao nhiêu vậy shop?\\nTrả lời\\nGửi tin nhắn\\nẨn", 350)
              ];
            }}
            return [];
          }}
        }};
        global.document = doc14;
        const res14 = fn(pageNames);
        if (res14.unreplied_count !== 1 || res14.author_name !== "Lan Hương") {{
          throw new Error("Scenario 14 failed (Customer question without author header in innerText): Expected unreplied_count == 1, got " + res14.unreplied_count);
        }}

        // Scenario 15 (Huy hiệu tác giả trong span): Page reply có span[dir=auto] chứa 'Tác giả' trước tên người quản lý
        const doc15 = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Bình luận dưới tên Khách Hàng vào 2 giờ trước", "Khách Hàng\\n2 giờ\\nCho mình hỏi giá\\nTrả lời\\nGửi tin nhắn\\nẨn", 350),
                makeEl("", "Người Quản Lý\\n1 giờ\\nDạ em đã nhắn tin ạ\\nTrả lời\\nẨn", 380, null, (sel) => sel.includes('span[dir="auto"]') ? [{{ innerText: 'Tác giả' }}] : [])
              ];
            }}
            return [];
          }}
        }};
        global.document = doc15;
        const res15 = fn(pageNames);
        if (res15.unreplied_count !== 0) {{
          throw new Error("Scenario 15 failed (span[dir=auto] Tác giả badge): Expected unreplied_count == 0, got " + res15.unreplied_count);
        }}

        // Scenario 16 (Chống nhận nhầm): Khách hỏi có nhắc chữ 'tác giả' trong aria-label có chứa cả nội dung bình luận
        const doc16 = {{
          querySelectorAll: (sel) => {{
            if (sel === '[role="article"]') {{
              return [
                makeEl("Bình luận dưới tên Lan Hương vào 2 phút trước: Tác giả cho em hỏi giá bao nhiêu", "Lan Hương\\n2 phút\\nTác giả cho em hỏi giá bao nhiêu\\nTrả lời\\nGửi tin nhắn\\nẨn", 350)
              ];
            }}
            return [];
          }}
        }};
        global.document = doc16;
        const res16 = fn(pageNames);
        if (res16.unreplied_count !== 1 || res16.author_name !== "Lan Hương") {{
          throw new Error("Scenario 16 failed (Customer mentions tác giả in aria-label with text): Expected unreplied_count == 1, got " + res16.unreplied_count);
        }}

        console.log("ALL_SCENARIOS_OK");
        """
        res = subprocess.run(["node"], input=node_script, capture_output=True, text=True, check=True, encoding="utf-8")
        self.assertIn("ALL_SCENARIOS_OK", res.stdout)


if __name__ == "__main__":
    unittest.main()
