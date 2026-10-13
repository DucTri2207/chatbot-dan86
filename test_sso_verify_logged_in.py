import asyncio
import os
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

    @patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock)
    @patch("bot.auth_helper.export_github_secret_file")
    async def test_sso_popup_success_navigates_to_inbox_and_returns_true(self, mock_export, mock_sleep):
        """
        Khi ở loginpage, click SSO mở popup, bấm Tiếp tục thành công,
        popup tự đóng và trang chính chuyển hướng vào Hộp thư -> Trả về True và export secret.
        """
        mock_page = MagicMock()
        mock_page.url = "https://business.facebook.com/business/loginpage/?next=..."
        mock_page.context = MagicMock()
        mock_page.context.storage_state = AsyncMock()

        def page_locator_side_effect(sel):
            mock = AsyncMock()
            if 'div:has-text("Tiếp tục bằng Facebook")' in sel:
                is_login = "/business/loginpage" in mock_page.url
                mock.first.count.return_value = 1 if is_login else 0
                mock.first.is_visible.return_value = is_login
                mock.first.click = AsyncMock()
            elif '[role="navigation"]' in sel or 'div._a6ag._a6ah' in sel:
                # Ban đầu ở loginpage thì chưa có inbox indicator, nhưng sau chuyển hướng vào inbox thì có
                is_inbox = "/latest/inbox" in mock_page.url
                mock.first.count.return_value = 1 if is_inbox else 0
                mock.first.is_visible.return_value = is_inbox
                mock.count.return_value = 1 if is_inbox else 0
            elif 'input[name="email"]' in sel:
                mock.count.return_value = 0
            else:
                mock.first.count.return_value = 0
                mock.first.is_visible.return_value = False
                mock.count.return_value = 0
            return mock

        mock_page.locator.side_effect = page_locator_side_effect

        # Mock popup
        mock_popup = MagicMock()
        mock_popup.is_closed.return_value = False
        mock_popup.wait_for_load_state = AsyncMock()
        mock_popup.wait_for_event = AsyncMock()
        mock_popup.close = AsyncMock()

        def popup_locator_side_effect(sel):
            mock = AsyncMock()
            if 'Tiếp tục' in sel or 'Continue' in sel or '__CONFIRM__' in sel:
                mock.first.count.return_value = 1
                mock.first.click = AsyncMock()
            elif 'input[name="pass"]' in sel:
                mock.count.return_value = 0
            else:
                mock.first.count.return_value = 0
                mock.count.return_value = 0
            return mock

        mock_popup.locator.side_effect = popup_locator_side_effect

        def on_page_listener(event, cb):
            cb(mock_popup)

        mock_page.context.on.side_effect = on_page_listener

        # Giả lập khi goto hoặc navigation xảy ra, URL chuyển sang inbox
        async def fake_goto(url, **kwargs):
            mock_page.url = url

        mock_page.goto = AsyncMock(side_effect=fake_goto)

        res = await verify_logged_in(mock_page)
        self.assertTrue(res)
        mock_export.assert_called_once()
        mock_page.context.remove_listener.assert_called()

    @patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock)
    @patch("bot.auth_helper.export_github_secret_file")
    async def test_sso_direct_navigation_without_popup_succeeds(self, mock_export, mock_sleep):
        """
        Khi ở loginpage, click SSO nhưng trình duyệt tự chuyển hướng trực tiếp trên tab hiện tại
        (không bắn event popup) vào thẳng inbox -> verify_logged_in vẫn nhận diện thành công và trả về True.
        """
        mock_page = MagicMock()
        mock_page.url = "https://business.facebook.com/business/loginpage/?next=..."
        mock_page.context = MagicMock()
        mock_page.context.storage_state = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()

        async def fake_click(**kwargs):
            # Khi click SSO button, chính tab hiện tại chuyển hướng sang inbox
            mock_page.url = "https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512"

        def page_locator_side_effect(sel):
            mock = AsyncMock()
            if 'div:has-text("Tiếp tục bằng Facebook")' in sel:
                is_login = "/business/loginpage" in mock_page.url
                mock.first.count.return_value = 1 if is_login else 0
                mock.first.is_visible.return_value = is_login
                mock.first.click = AsyncMock(side_effect=fake_click)
            elif '[role="navigation"]' in sel:
                is_inbox = "/latest/inbox" in mock_page.url
                mock.first.count.return_value = 1 if is_inbox else 0
                mock.first.is_visible.return_value = is_inbox
                mock.count.return_value = 1 if is_inbox else 0
            elif 'input[name="email"]' in sel:
                mock.count.return_value = 0
            else:
                mock.first.count.return_value = 0
                mock.first.is_visible.return_value = False
                mock.count.return_value = 0
            return mock

        mock_page.locator.side_effect = page_locator_side_effect
        mock_page.goto = AsyncMock()

        # Không gọi cb trong on_page (không mở popup) -> popup_future times out
        mock_page.context.on = MagicMock()

        res = await verify_logged_in(mock_page)
        self.assertTrue(res)
        mock_export.assert_called_once()
        mock_page.context.remove_listener.assert_called()

    async def test_login_php_path_rejected_after_sso(self):
        """Đảm bảo URL dạng /login.php hoặc /login/device-based/ bị từ chối chính xác."""
        mock_page = MagicMock()
        mock_page.url = "https://www.facebook.com/login.php?login_attempt=1"

        mock_empty = AsyncMock()
        mock_empty.first.count.return_value = 0
        mock_empty.first.is_visible.return_value = False
        mock_empty.count.return_value = 0
        mock_page.locator.return_value = mock_empty

        res = await verify_logged_in(mock_page)
        self.assertFalse(res)

    async def test_unknown_page_without_inbox_indicators_rejected(self):
        """
        Nếu URL không thuộc /latest/inbox và không có bất kỳ chỉ báo Hộp thư nào
        (ví dụ trang lỗi, trang trắng, trang bảo trì), hàm phải trả về False, không được false positive.
        """
        mock_page = MagicMock()
        mock_page.url = "https://business.facebook.com/unexpected_error_view"

        mock_empty = AsyncMock()
        mock_empty.first.count.return_value = 0
        mock_empty.first.is_visible.return_value = False
        mock_empty.count.return_value = 0
        mock_page.locator.return_value = mock_empty

        res = await verify_logged_in(mock_page)
        self.assertFalse(res)

    @patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock)
    @patch("bot.auth_helper.export_github_secret_file")
    @patch("bot.auth_helper.sync_storage_secret_to_github")
    async def test_popup_requires_password_with_fb_password_fills_and_succeeds(
        self, mock_sync, mock_export, mock_sleep
    ):
        """
        Khi SSO popup yêu cầu xác nhận mật khẩu và FB_PASSWORD có trong môi trường:
        - Tự động điền mật khẩu mà KHÔNG log mật khẩu
        - Nhấn xác nhận
        - Popup tự đóng
        - Chuyển hướng vào Inbox thành công và trả về True
        """
        with patch.dict(os.environ, {"FB_PASSWORD": "SecretPassword123!"}):
            mock_page = MagicMock()
            mock_page.url = "https://business.facebook.com/business/loginpage/?next=..."
            mock_page.context = MagicMock()
            mock_page.context.storage_state = AsyncMock()

            def page_locator_side_effect(sel):
                mock = AsyncMock()
                if 'div:has-text("Tiếp tục bằng Facebook")' in sel:
                    is_login = "/business/loginpage" in mock_page.url
                    mock.first.count.return_value = 1 if is_login else 0
                    mock.first.is_visible.return_value = is_login
                    mock.first.click = AsyncMock()
                elif '[role="navigation"]' in sel or 'div._a6ag._a6ah' in sel:
                    is_inbox = "/latest/inbox" in mock_page.url
                    mock.first.count.return_value = 1 if is_inbox else 0
                    mock.first.is_visible.return_value = is_inbox
                    mock.count.return_value = 1 if is_inbox else 0
                elif 'input[name="email"]' in sel:
                    mock.count.return_value = 0
                else:
                    mock.first.count.return_value = 0
                    mock.first.is_visible.return_value = False
                    mock.count.return_value = 0
                return mock

            mock_page.locator.side_effect = page_locator_side_effect

            # Mock popup
            mock_popup = MagicMock()
            mock_popup.is_closed.return_value = False
            mock_popup.wait_for_load_state = AsyncMock()
            mock_popup.wait_for_event = AsyncMock()
            mock_popup.close = AsyncMock()

            pass_input_mock = AsyncMock()
            confirm_btn_mock = AsyncMock()

            def popup_locator_side_effect(sel):
                mock = AsyncMock()
                if 'button[type="submit"]' in sel or 'button[name="login"]' in sel or '__CONFIRM__' in sel:
                    mock.count.return_value = 1
                    mock.first = confirm_btn_mock
                    confirm_btn_mock.count = AsyncMock(return_value=1)
                elif 'Tiếp tục' in sel:
                    mock.first.count.return_value = 1
                    mock.first.click = AsyncMock()
                elif 'input[name="pass"]' in sel:
                    mock.count.return_value = 1
                    mock.first = pass_input_mock
                else:
                    mock.first.count.return_value = 0
                    mock.count.return_value = 0
                return mock

            mock_popup.locator.side_effect = popup_locator_side_effect

            def on_page_listener(event, cb):
                cb(mock_popup)

            mock_page.context.on.side_effect = on_page_listener

            async def fake_goto(url, **kwargs):
                mock_page.url = url

            mock_page.goto = AsyncMock(side_effect=fake_goto)

            with self.assertLogs("dan86_page_bot", level="INFO") as log_capture:
                res = await verify_logged_in(mock_page)

            self.assertTrue(res)
            pass_input_mock.fill.assert_awaited_with("SecretPassword123!")
            confirm_btn_mock.click.assert_awaited()
            mock_export.assert_called_once()
            mock_sync.assert_called_once()

            # BẢO MẬT 100%: Tuyệt đối không log chuỗi mật khẩu
            all_logs = " ".join(log_capture.output)
            self.assertNotIn("SecretPassword123!", all_logs)

    @patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock)
    async def test_popup_password_fill_exception_handles_gracefully(self, mock_sleep):
        """Khi quá trình điền mật khẩu gặp ngoại lệ, bot không bị crash và đóng popup an toàn."""
        with patch.dict(os.environ, {"FB_PASSWORD": "SecretPassword123!"}):
            mock_page = MagicMock()
            mock_page.url = "https://business.facebook.com/business/loginpage/?next=..."
            mock_page.context = MagicMock()

            def page_locator_side_effect(sel):
                mock = AsyncMock()
                if 'div:has-text("Tiếp tục bằng Facebook")' in sel:
                    mock.first.count.return_value = 1
                    mock.first.is_visible.return_value = True
                    mock.first.click = AsyncMock()
                else:
                    mock.first.count.return_value = 0
                    mock.first.is_visible.return_value = False
                    mock.count.return_value = 0
                return mock

            mock_page.locator.side_effect = page_locator_side_effect

            mock_popup = MagicMock()
            mock_popup.is_closed.return_value = False
            mock_popup.wait_for_load_state = AsyncMock()
            mock_popup.close = AsyncMock()

            pass_input_mock = AsyncMock()
            pass_input_mock.fill.side_effect = RuntimeError("Element detached from DOM")

            def popup_locator_side_effect(sel):
                mock = AsyncMock()
                if 'input[name="pass"]' in sel:
                    mock.count.return_value = 1
                    mock.first = pass_input_mock
                else:
                    mock.first.count.return_value = 0
                    mock.count.return_value = 0
                return mock

            mock_popup.locator.side_effect = popup_locator_side_effect

            def on_page_listener(event, cb):
                cb(mock_popup)

            mock_page.context.on.side_effect = on_page_listener

            res = await verify_logged_in(mock_page)
            self.assertFalse(res)
            mock_popup.close.assert_awaited()


class TestSyncStorageSecretToGithub(unittest.TestCase):

    @patch("os.path.exists", return_value=False)
    def test_sync_file_not_found_returns_false(self, mock_exists):
        from bot.auth_helper import sync_storage_secret_to_github
        res = sync_storage_secret_to_github("nonexistent_file.txt")
        self.assertFalse(res)

    @patch("os.path.exists", return_value=True)
    @patch("shutil.which", return_value=None)
    def test_sync_gh_not_installed_returns_false(self, mock_which, mock_exists):
        from bot.auth_helper import sync_storage_secret_to_github
        res = sync_storage_secret_to_github("state/GITHUB_SECRET_VALUE.txt")
        self.assertFalse(res)

    @patch("os.path.exists", return_value=True)
    @patch("shutil.which", return_value="/usr/bin/gh")
    @patch("builtins.open")
    @patch("subprocess.run")
    def test_sync_success(self, mock_run, mock_open_file, mock_which, mock_exists):
        from bot.auth_helper import sync_storage_secret_to_github
        mock_file = MagicMock()
        mock_file.__enter__.return_value.read.return_value = "eyJjb29raWVzIjpbXX0="
        mock_open_file.return_value = mock_file

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        res = sync_storage_secret_to_github("state/GITHUB_SECRET_VALUE.txt")
        self.assertTrue(res)
        mock_run.assert_called_once()
        cmd_called = mock_run.call_args[0][0]
        self.assertEqual(cmd_called[:4], ["gh", "secret", "set", "FB_STORAGE_STATE"])
        # Verify secret content was passed via input and not logged in cmd
        self.assertEqual(mock_run.call_args[1]["input"], "eyJjb29raWVzIjpbXX0=")


class TestRestoreStorageStateAndEdgeCases(unittest.IsolatedAsyncioTestCase):

    @patch("os.path.exists")
    @patch("builtins.open")
    def test_restore_storage_state_preserves_valid_cached_disk_state(self, mock_open_file, mock_exists):
        from bot.page_bot_engine import restore_storage_state_from_env
        import json

        # Mock: file storage_state.json và GITHUB_SECRET_VALUE.txt đều tồn tại
        def exists_side_effect(path):
            return True

        mock_exists.side_effect = exists_side_effect

        cached_data = {
            "cookies": [{"name": "c_user", "value": "123"}, {"name": "xs", "value": "456"}],
            "origins": [{"origin": "https://business.facebook.com", "localStorage": [{"name": "key", "value": "val"}]}]
        }
        b64_val = "eyJjb29raWVzIjpbXX0="

        def fake_open(path, mode="r", **kwargs):
            m = MagicMock()
            if "fb_storage_state.json" in str(path) and "r" in mode:
                m.__enter__.return_value.read.return_value = json.dumps(cached_data)
            elif "GITHUB_SECRET_VALUE.txt" in str(path) and "r" in mode:
                m.__enter__.return_value.read.return_value = b64_val
            return m

        mock_open_file.side_effect = fake_open

        # Khi FB_STORAGE_STATE trùng với cached b64_val
        with patch.dict(os.environ, {"FB_STORAGE_STATE": b64_val}):
            with patch("json.load", return_value=cached_data):
                res = restore_storage_state_from_env()
                self.assertTrue(res)

    @patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock)
    async def test_popup_button_with_user_name_duc_tri_clicked(self, mock_sleep):
        """Khi popup hiển thị thẻ profile có tên người dùng 'Đức Trí', bot nhận diện và click chính xác."""
        with patch.dict(os.environ, {"FB_PASSWORD": "SecretPassword123!"}):
            mock_page = MagicMock()
            mock_page.url = "https://business.facebook.com/business/loginpage/?next=..."
            mock_page.context = MagicMock()
            mock_page.context.storage_state = AsyncMock()

            def page_locator_side_effect(sel):
                mock = AsyncMock()
                if 'div:has-text("Tiếp tục bằng Facebook")' in sel:
                    mock.first.count.return_value = 1
                    mock.first.is_visible.return_value = True
                    mock.first.click = AsyncMock()
                elif '[role="navigation"]' in sel:
                    mock.first.count.return_value = 1
                    mock.first.is_visible.return_value = True
                    mock.count.return_value = 1
                else:
                    mock.first.count.return_value = 0
                    mock.first.is_visible.return_value = False
                    mock.count.return_value = 0
                return mock

            mock_page.locator.side_effect = page_locator_side_effect

            mock_popup = MagicMock()
            mock_popup.is_closed.return_value = False
            mock_popup.wait_for_load_state = AsyncMock()
            mock_popup.wait_for_event = AsyncMock()
            mock_popup.close = AsyncMock()

            duc_tri_btn_mock = AsyncMock()
            pass_input_mock = AsyncMock()
            submit_btn_mock = AsyncMock()
            pass_prompt_visible = False

            async def on_duc_tri_click(**kwargs):
                nonlocal pass_prompt_visible
                pass_prompt_visible = True

            duc_tri_btn_mock.click = AsyncMock(side_effect=on_duc_tri_click)

            def popup_locator_side_effect(sel):
                mock = AsyncMock()
                if 'Đức Trí' in sel:
                    mock.first = duc_tri_btn_mock
                    duc_tri_btn_mock.count = AsyncMock(return_value=1)
                elif 'button[type="submit"]' in sel or '__CONFIRM__' in sel:
                    mock.count.return_value = 1
                    mock.first = submit_btn_mock
                    submit_btn_mock.count = AsyncMock(return_value=1)
                elif 'input[name="pass"]' in sel:
                    mock.count.return_value = 1 if pass_prompt_visible else 0
                    mock.first = pass_input_mock
                else:
                    mock.first.count.return_value = 0
                    mock.count.return_value = 0
                return mock

            mock_popup.locator.side_effect = popup_locator_side_effect

            def on_page_listener(event, cb):
                cb(mock_popup)

            mock_page.context.on.side_effect = on_page_listener

            async def fake_goto(url, **kwargs):
                mock_page.url = url

            mock_page.goto = AsyncMock(side_effect=fake_goto)

            with patch("bot.auth_helper.export_github_secret_file"):
                with patch("bot.auth_helper.sync_storage_secret_to_github"):
                    res = await verify_logged_in(mock_page)

            self.assertTrue(res)
            duc_tri_btn_mock.click.assert_awaited()
            pass_input_mock.fill.assert_awaited_with("SecretPassword123!")

    @patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock)
    async def test_popup_checkpoint_2fa_after_password_fails_safely(self, mock_sleep):
        """Khi gửi mật khẩu xong mà Facebook chuyển sang màn hình 2FA/checkpoint, bot đóng popup và trả về False an toàn."""
        with patch.dict(os.environ, {"FB_PASSWORD": "SecretPassword123!"}):
            mock_page = MagicMock()
            mock_page.url = "https://business.facebook.com/business/loginpage/?next=..."
            mock_page.context = MagicMock()

            def page_locator_side_effect(sel):
                mock = AsyncMock()
                if 'div:has-text("Tiếp tục bằng Facebook")' in sel:
                    mock.first.count.return_value = 1
                    mock.first.is_visible.return_value = True
                    mock.first.click = AsyncMock()
                else:
                    mock.first.count.return_value = 0
                    mock.first.is_visible.return_value = False
                    mock.count.return_value = 0
                return mock

            mock_page.locator.side_effect = page_locator_side_effect

            mock_popup = MagicMock()
            mock_popup.is_closed.return_value = False
            mock_popup.wait_for_load_state = AsyncMock()
            # Giả lập timeout wait_for_event("close") vì popup không tự đóng
            mock_popup.wait_for_event = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_popup.close = AsyncMock()
            mock_popup.url = "https://www.facebook.com/checkpoint/15000"

            pass_input_mock = AsyncMock()
            submit_btn_mock = AsyncMock()

            def popup_locator_side_effect(sel):
                mock = AsyncMock()
                if 'button[type="submit"]' in sel or '__CONFIRM__' in sel:
                    mock.count.return_value = 1
                    mock.first = submit_btn_mock
                    submit_btn_mock.count = AsyncMock(return_value=1)
                elif 'input[name="pass"]' in sel:
                    mock.count.return_value = 0
                elif 'approvals_code' in sel:
                    # 2FA input
                    mock.count.return_value = 1
                else:
                    mock.first.count.return_value = 0
                    mock.count.return_value = 0
                return mock

            mock_popup.locator.side_effect = popup_locator_side_effect

            def on_page_listener(event, cb):
                cb(mock_popup)

            mock_page.context.on.side_effect = on_page_listener

            res = await verify_logged_in(mock_page)
            self.assertFalse(res)
            mock_popup.close.assert_awaited()

    @patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock)
    async def test_handle_sso_password_exception_redacts_password_in_logs(self, mock_sleep):
        """BẢO MẬT 100%: Khi exception xảy ra mang theo mật khẩu, chuỗi mật khẩu tuyệt đối bị redact khỏi logs."""
        super_secret = "SuperSecretP@ss999"
        with patch.dict(os.environ, {"FB_PASSWORD": super_secret}):
            mock_page = MagicMock()
            mock_page.url = "https://business.facebook.com/business/loginpage/?next=..."
            mock_page.context = MagicMock()

            def page_locator_side_effect(sel):
                mock = AsyncMock()
                if 'div:has-text("Tiếp tục bằng Facebook")' in sel:
                    mock.first.count.return_value = 1
                    mock.first.is_visible.return_value = True
                    mock.first.click = AsyncMock()
                else:
                    mock.first.count.return_value = 0
                    mock.first.is_visible.return_value = False
                    mock.count.return_value = 0
                return mock

            mock_page.locator.side_effect = page_locator_side_effect

            mock_popup = MagicMock()
            mock_popup.is_closed.return_value = False
            mock_popup.wait_for_load_state = AsyncMock()
            mock_popup.close = AsyncMock()

            pass_input_mock = AsyncMock()
            # Giả lập exception từ Playwright vô tình chứa mật khẩu
            pass_input_mock.fill.side_effect = RuntimeError(f"Failed to fill field with value '{super_secret}'")

            def popup_locator_side_effect(sel):
                mock = AsyncMock()
                if 'input[name="pass"]' in sel:
                    mock.count.return_value = 1
                    mock.first = pass_input_mock
                else:
                    mock.first.count.return_value = 0
                    mock.count.return_value = 0
                return mock

            mock_popup.locator.side_effect = popup_locator_side_effect

            def on_page_listener(event, cb):
                cb(mock_popup)

            mock_page.context.on.side_effect = on_page_listener

            with self.assertLogs("dan86_page_bot", level="WARNING") as log_capture:
                res = await verify_logged_in(mock_page)

            self.assertFalse(res)
            mock_popup.close.assert_awaited()
            all_logs = " ".join(log_capture.output)
            # Khẳng định tuyệt đối mật khẩu KHÔNG xuất hiện trong log
            self.assertNotIn(super_secret, all_logs)
            self.assertIn("[REDACTED_PASSWORD]", all_logs)


if __name__ == "__main__":
    unittest.main()
