import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.page_bot_engine import verify_logged_in


class TestVerifyLoggedIn(unittest.IsolatedAsyncioTestCase):

    async def test_inbox_indicators_present_returns_true_immediately(self):
        """Khi các chỉ báo giao diện Hộp thư MBS đã xuất hiện, trả về True ngay lập tức."""
        mock_page = MagicMock()
        mock_page.url = "https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512"

        # Mock locator cho inbox_indicators
        mock_loc = AsyncMock()
        mock_loc.count.return_value = 1
        mock_loc.is_visible.return_value = True

        mock_page.locator.return_value.first = mock_loc

        res = await verify_logged_in(mock_page)
        self.assertTrue(res)

    async def test_url_with_login_in_query_param_does_not_falsely_reject(self):
        """
        Đảm bảo khi URL đã ở /latest/inbox/facebook nhưng query param có 'nav_ref=biz_unified_f3_login_page_to_mbs',
        verify_logged_in KHÔNG bị đánh giá nhầm thành đang ở trang login.
        """
        mock_page = MagicMock()
        mock_page.url = (
            "https://business.facebook.com/latest/inbox/facebook?"
            "asset_id=104011958817512&nav_ref=biz_unified_f3_login_page_to_mbs"
        )

        mock_first = AsyncMock()
        mock_first.count.return_value = 1
        mock_first.is_visible.return_value = True
        mock_page.locator.return_value.first = mock_first

        res = await verify_logged_in(mock_page)
        self.assertTrue(res)

    async def test_login_form_present_returns_false(self):
        """Khi trang chứa form nhập email/pass thông thường, trả về False."""
        mock_page = MagicMock()
        mock_page.url = "https://www.facebook.com/login/"

        # Mock indicator returns 0
        def locator_side_effect(sel):
            mock = AsyncMock()
            if 'input[name="email"]' in sel:
                mock.count.return_value = 1
            else:
                mock.first.count.return_value = 0
                mock.first.is_visible.return_value = False
                mock.count.return_value = 0
            return mock

        mock_page.locator.side_effect = locator_side_effect

        res = await verify_logged_in(mock_page)
        self.assertFalse(res)

    async def test_checkpoint_path_returns_false(self):
        """Khi trang rơi vào /checkpoint/, trả về False an toàn."""
        mock_page = MagicMock()
        mock_page.url = "https://www.facebook.com/checkpoint/12345/"

        mock_empty = AsyncMock()
        mock_empty.first.count.return_value = 0
        mock_empty.first.is_visible.return_value = False
        mock_empty.count.return_value = 0
        mock_page.locator.return_value = mock_empty

        res = await verify_logged_in(mock_page)
        self.assertFalse(res)

    async def test_popup_requires_password_closes_popup_and_no_deadlock(self):
        """
        Khi ở loginpage, click SSO mở popup và popup đòi mật khẩu:
        Đảm bảo đóng popup ngay lập tức, không chờ timeout 10s, không deadlock.
        """
        mock_page = MagicMock()
        mock_page.url = "https://business.facebook.com/business/loginpage/?next=..."
        mock_page.context = MagicMock()

        # Mock locator
        def page_locator_side_effect(sel):
            mock = AsyncMock()
            if 'div:has-text("Tiếp tục bằng Facebook")' in sel:
                mock.first.count.return_value = 1
                mock.first.is_visible.return_value = True
                mock.first.click = AsyncMock()
            elif 'input[name="email"]' in sel:
                mock.count.return_value = 0
            else:
                mock.first.count.return_value = 0
                mock.first.is_visible.return_value = False
                mock.count.return_value = 0
            return mock

        mock_page.locator.side_effect = page_locator_side_effect
        mock_page.goto = AsyncMock()

        # Mock popup
        mock_popup = MagicMock()
        mock_popup.is_closed.return_value = False
        mock_popup.wait_for_load_state = AsyncMock()
        mock_popup.close = AsyncMock()

        def popup_locator_side_effect(sel):
            mock = AsyncMock()
            if 'div[role="button"]:has-text("Tiếp tục")' in sel:
                mock.first.count.return_value = 1
                mock.first.click = AsyncMock()
            elif 'input[name="pass"]' in sel:
                # Pop up đòi pass!
                mock.count.return_value = 1
            else:
                mock.first.count.return_value = 0
                mock.count.return_value = 0
            return mock

        mock_popup.locator.side_effect = popup_locator_side_effect

        # Mock context.on("page", cb)
        def on_page_listener(event, cb):
            # Gọi cb ngay khi loc.click được gọi
            cb(mock_popup)

        mock_page.context.on.side_effect = on_page_listener

        start_time = asyncio.get_event_loop().time()
        res = await verify_logged_in(mock_page)
        elapsed = asyncio.get_event_loop().time() - start_time

        # Phải kết thúc nhanh (< 4s), không bị treo 10s
        self.assertLess(elapsed, 4.0)
        self.assertFalse(res)
        # Popup phải được đóng chủ động
        mock_popup.close.assert_awaited()
        # Listener phải được gỡ bỏ khỏi context
        mock_page.context.remove_listener.assert_called()


if __name__ == "__main__":
    unittest.main()
