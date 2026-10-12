import subprocess
import unittest
from bot.bot_config import TEST_ONLY_AUTHOR_WHITELIST
from bot.memory_store import normalize_text


class TestWhitelistAndNestedReply(unittest.TestCase):

    def test_whitelist_contains_duc_tri(self):
        """Đảm bảo danh sách TEST_ONLY_AUTHOR_WHITELIST chứa đầy đủ các biến thể của Đức Trí."""
        self.assertTrue(len(TEST_ONLY_AUTHOR_WHITELIST) > 0)
        self.assertIn("đức trí", TEST_ONLY_AUTHOR_WHITELIST)
        self.assertIn("duc tri", TEST_ONLY_AUTHOR_WHITELIST)

    def test_whitelist_matching_logic(self):
        """Đảm bảo chỉ có Đức Trí và các biến thể vượt qua bộ lọc."""
        allowed_authors = ["Đức Trí", "duc tri", "Trí Đức", "TRI DUC", "Nguyễn Đức Trí"]
        blocked_authors = ["Hoa Muongbien", "Lệ Thuyền", "Bach Mai", "Ba Loc Tran", "Khách Hàng Lạ"]

        for author in allowed_authors:
            norm = normalize_text(author)
            matches = any(w in norm for w in TEST_ONLY_AUTHOR_WHITELIST)
            self.assertTrue(matches, f"Tác giả hợp lệ '{author}' phải được cho phép.")

        for author in blocked_authors:
            norm = normalize_text(author)
            matches = any(w in norm for w in TEST_ONLY_AUTHOR_WHITELIST)
            self.assertFalse(matches, f"Tác giả lạ '{author}' phải bị chặn 100% trong phiên sửa lỗi.")

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


if __name__ == "__main__":
    unittest.main()
