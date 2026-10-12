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


if __name__ == "__main__":
    unittest.main()
