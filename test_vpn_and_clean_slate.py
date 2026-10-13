import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.page_bot_engine import verify_logged_in
import scripts.connect_vn_vpn as vpn_module


class TestVpnGateModule(unittest.TestCase):

    def test_fetch_vn_vpn_servers_parsing_and_sorting(self):
        """Kiểm tra parser CSV VPN Gate lọc đúng CountryShort VN và sắp xếp theo Ping/Speed."""
        sample_csv = (
            "*vpn_servers\n"
            "#HostName,IP,Score,Ping,Speed,CountryLong,CountryShort,NumVpnSessions,Uptime,TotalUsers,TotalTraffic,LogType,Operator,Message,OpenVPN_ConfigData_Base64\n"
            "us_server,1.2.3.4,100,50,1000000,United States,US,5,100,10,1000,None,Op,Msg,dXNfY29uZmln\n"
            "vn_server_slow,14.161.1.1,500,80,5000000,Vietnam,VN,2,100,10,1000,None,Op,Msg,dm5fc2xvd19jb25maWc=\n"
            "vn_server_fast,14.161.1.2,900,15,20000000,Vietnam,VN,1,100,10,1000,None,Op,Msg,dm5fZmFzdF9jb25maWc=\n"
            "jp_server,5.6.7.8,200,30,10000000,Japan,JP,3,100,10,1000,None,Op,Msg,anBfY29uZmln\n"
            "*\n"
        )

        mock_resp = MagicMock()
        mock_resp.read.return_value = sample_csv.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            servers = vpn_module.fetch_vn_vpn_servers()

        self.assertEqual(len(servers), 2)
        # Server nhanh (ping 15) phải được ưu tiên trước server chậm (ping 80)
        self.assertEqual(servers[0]["ip"], "14.161.1.2")
        self.assertEqual(servers[0]["ping"], 15)
        self.assertEqual(servers[1]["ip"], "14.161.1.1")

    def test_setup_ovpn_file_decodes_base64_and_appends_auth(self):
        """Kiểm tra setup_ovpn_file giải mã cấu hình và thiết lập file auth."""
        import tempfile

        raw_ovpn = "client\ndev tun\nproto udp\nremote 14.161.1.2 1194\n"
        import base64
        b64_str = base64.b64encode(raw_ovpn.encode("utf-8")).decode("utf-8")

        server = {"ovpn_b64": b64_str, "ip": "14.161.1.2"}

        with tempfile.TemporaryDirectory() as tmp_dir:
            conf_path = os.path.join(tmp_dir, "test.ovpn")
            auth_path = os.path.join(tmp_dir, "auth.txt")

            ok = vpn_module.setup_ovpn_file(server, conf_path, auth_path)
            self.assertTrue(ok)
            self.assertTrue(os.path.exists(conf_path))
            self.assertTrue(os.path.exists(auth_path))

            with open(auth_path, "r", encoding="utf-8") as f:
                auth_content = f.read()
            self.assertEqual(auth_content, "vpn\nvpn\n")

            with open(conf_path, "r", encoding="utf-8") as f:
                conf_content = f.read()
            self.assertIn("client", conf_content)
            self.assertIn("auth-user-pass", conf_content)
            self.assertIn("auth-nocache", conf_content)

    def test_normalize_country(self):
        """Kiểm tra chuẩn hóa tên và mã quốc gia sang dạng chuẩn ISO-2 VN."""
        self.assertEqual(vpn_module.normalize_country("VN"), "VN")
        self.assertEqual(vpn_module.normalize_country("Vietnam"), "VN")
        self.assertEqual(vpn_module.normalize_country("Viet Nam"), "VN")
        self.assertEqual(vpn_module.normalize_country("VNM"), "VN")
        self.assertEqual(vpn_module.normalize_country("US"), "US")
        self.assertEqual(vpn_module.normalize_country(None), "")

    def test_get_current_ip_info_with_ipinfo_success(self):
        """Đảm bảo get_current_ip_info trích xuất chuẩn IP và Country từ dịch vụ GeoIP."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "ip": "117.5.142.217",
            "country": "VN",
            "city": "Ho Chi Minh City",
            "org": "Viettel",
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            info = vpn_module.get_current_ip_info()

        self.assertEqual(info["ip"], "117.5.142.217")
        self.assertEqual(info["country"], "VN")
        self.assertEqual(info["city"], "Ho Chi Minh City")

    def test_get_current_ip_info_with_ip_api_normalizes_vietnam(self):
        """Đảm bảo khi dịch vụ trả về country: 'Vietnam', hàm chuẩn hóa thành 'VN'."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "query": "14.161.1.2",
            "country": "Vietnam",
            "city": "Da Nang",
            "isp": "VNPT",
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            info = vpn_module.get_current_ip_info()

        self.assertEqual(info["ip"], "14.161.1.2")
        self.assertEqual(info["country"], "VN")
        self.assertEqual(info["city"], "Da Nang")

    def test_get_current_ip_info_with_freeipapi_format(self):
        """Đảm bảo get_current_ip_info trích xuất chuẩn các trường cityName, asnOrganization từ freeipapi."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "ipAddress": "117.5.142.217",
            "countryCode": "VN",
            "cityName": "Ho Chi Minh City",
            "asnOrganization": "Viettel Group",
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            info = vpn_module.get_current_ip_info()

        self.assertEqual(info["ip"], "117.5.142.217")
        self.assertEqual(info["country"], "VN")
        self.assertEqual(info["city"], "Ho Chi Minh City")
        self.assertEqual(info["org"], "Viettel Group")

    def test_get_current_ip_info_all_fail_returns_unknown(self):
        """Khi tất cả dịch vụ GeoIP gặp sự cố, hàm fallback an toàn không gây sập."""
        with patch("urllib.request.urlopen", side_effect=Exception("Network error")):
            info = vpn_module.get_current_ip_info()

        self.assertEqual(info["ip"], "Unknown")
        self.assertEqual(info["country"], "Unknown")

    @patch("platform.system", return_value="Linux")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", unittest.mock.mock_open(read_data="nameserver 127.0.0.53\noptions edns0"))
    @patch("subprocess.run")
    def test_ensure_public_dns_executes_printf_prepend_on_linux(self, mock_sub, mock_exists, mock_sys):
        """Đảm bảo trên Linux runner, ensure_public_dns gọi printf chèn 8.8.8.8 vào đầu resolv.conf."""
        vpn_module.ensure_public_dns()
        self.assertTrue(mock_sub.called)
        cmd_args = mock_sub.call_args[0][0]
        cmd_str = " ".join(cmd_args)
        self.assertIn("printf 'nameserver 8.8.8.8\\nnameserver 1.1.1.1\\n'", cmd_str)
        self.assertIn("/etc/resolv.conf", cmd_str)

    @patch("platform.system", return_value="Linux")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", unittest.mock.mock_open(read_data="nameserver 8.8.8.8\nnameserver 1.1.1.1"))
    @patch("subprocess.run")
    def test_ensure_public_dns_skips_when_already_configured(self, mock_sub, mock_exists, mock_sys):
        """Khi 8.8.8.8 đã có sẵn ở các dòng đầu, ensure_public_dns bỏ qua không gọi subprocess."""
        vpn_module.ensure_public_dns()
        self.assertFalse(mock_sub.called)

    @patch("shutil.which", return_value=None)
    def test_connect_vpn_missing_openvpn_returns_false(self, mock_which):
        """Khi openvpn chưa được cài đặt, connect_vpn bỏ qua an toàn và trả về False."""
        server = {"ovpn_b64": "Y2xpZW50Cg==", "ip": "1.2.3.4", "ping": 10, "speed": 1000}
        res = vpn_module.connect_vpn(server, timeout_sec=2)
        self.assertFalse(res)

    @patch("shutil.which", return_value="/usr/sbin/openvpn")
    @patch("subprocess.Popen")
    @patch("scripts.connect_vn_vpn.get_current_ip_info")
    @patch("time.sleep", return_value=None)
    def test_connect_vpn_switches_ip_returns_true(self, mock_sleep, mock_ip, mock_popen, mock_which):
        """Khi IP chuyển sang Việt Nam thành công, connect_vpn trả về True."""
        mock_ip.return_value = {"ip": "14.161.1.2", "country": "VN", "city": "Hanoi", "org": "FPT"}
        server = {"ovpn_b64": "Y2xpZW50Cg==", "ip": "14.161.1.2", "ping": 10, "speed": 1000}
        res = vpn_module.connect_vpn(server, timeout_sec=5)
        self.assertTrue(res)

    @patch("scripts.connect_vn_vpn.get_current_ip_info")
    def test_main_already_vn_skips_vpn(self, mock_ip):
        """Khi máy đã có IP Việt Nam, main() hoàn thành ngay lập tức không cần kết nối VPN."""
        mock_ip.return_value = {
            "ip": "117.5.142.217",
            "country": "VN",
            "city": "Ho Chi Minh City",
            "org": "Viettel",
        }
        res = vpn_module.main()
        self.assertEqual(res, 0)

    @patch("scripts.connect_vn_vpn.get_current_ip_info")
    @patch("scripts.connect_vn_vpn.fetch_vn_vpn_servers", return_value=[])
    def test_main_no_vn_servers_fallbacks_safely(self, mock_fetch, mock_ip):
        """Khi VPN Gate không có server VN, main() ghi log cảnh báo và fallback an toàn với mã 0."""
        mock_ip.return_value = {
            "ip": "20.150.10.5",
            "country": "US",
            "city": "Washington",
            "org": "Microsoft",
        }
        res = vpn_module.main()
        self.assertEqual(res, 0)

    @patch("scripts.connect_vn_vpn.get_current_ip_info")
    @patch("scripts.connect_vn_vpn.connect_vpn")
    @patch("scripts.connect_vn_vpn.fetch_vn_vpn_servers")
    def test_main_retries_second_server_if_first_fails(self, mock_fetch, mock_connect, mock_ip):
        """Khi server #1 thất bại, main() thử tiếp server #2 trước khi fallback."""
        mock_ip.return_value = {"ip": "20.150.10.5", "country": "US", "city": "Washington", "org": "MS"}
        mock_fetch.return_value = [
            {"ip": "14.161.1.1", "ping": 10, "speed": 1000},
            {"ip": "14.161.1.2", "ping": 20, "speed": 2000},
        ]
        # Server 1 fail, server 2 success
        mock_connect.side_effect = [False, True]

        res = vpn_module.main()
        self.assertEqual(res, 0)
        self.assertEqual(mock_connect.call_count, 2)


class TestIncognitoCleanSlateReAuth(unittest.IsolatedAsyncioTestCase):

    @patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock)
    @patch("bot.auth_helper.export_github_secret_file")
    @patch("bot.auth_helper.sync_storage_secret_to_github")
    async def test_incognito_clean_slate_executed_on_sso_failure(self, mock_sync, mock_export, mock_sleep):
        """
        R2: Đảm bảo khi phát hiện ở loginpage và SSO thất bại:
        - Tự động gọi page.context.clear_cookies()
        - Tự động xóa localStorage và sessionStorage
        - Mở trang login.php với trạng thái sạch
        - Điền thông tin đăng nhập và điều hướng về MBS Inbox
        """
        test_email = "dan86_owner@dan86.vn"
        test_pass = "SecureCleanSlatePass123!"

        with patch.dict(os.environ, {"FB_EMAIL": test_email, "FB_PASSWORD": test_pass}):
            mock_page = MagicMock()
            mock_page.url = "https://business.facebook.com/business/loginpage/?next=..."
            mock_page.context = MagicMock()
            mock_page.context.clear_cookies = AsyncMock()
            mock_page.context.storage_state = AsyncMock()
            mock_page.evaluate = AsyncMock()
            mock_page.context.cookies = AsyncMock(return_value=[])

            async def fake_submit_click(**kwargs):
                mock_page.url = "https://www.facebook.com/"
                mock_page.context.cookies.return_value = [{"name": "c_user", "value": "100012345678"}]

            submit_btn_mock = AsyncMock(count=AsyncMock(return_value=1), click=AsyncMock(side_effect=fake_submit_click))

            async def fake_goto(url, **kwargs):
                mock_page.url = url

            mock_page.goto = AsyncMock(side_effect=fake_goto)

            email_input_mock = AsyncMock(count=AsyncMock(return_value=1), fill=AsyncMock())
            pass_input_mock = AsyncMock(count=AsyncMock(return_value=1), fill=AsyncMock())

            def page_locator_side_effect(sel):
                mock = AsyncMock()
                if 'Tiếp tục bằng Facebook' in sel:
                    # SSO không xuất hiện hoặc bị lỗi
                    mock.first.count.return_value = 0
                    mock.first.is_visible.return_value = False
                elif 'input[name="email"]' in sel:
                    is_login_php = "/login.php" in mock_page.url
                    mock.count.return_value = 1 if is_login_php else 0
                    mock.first = email_input_mock
                elif 'input[name="pass"]' in sel:
                    is_login_php = "/login.php" in mock_page.url
                    mock.count.return_value = 1 if is_login_php else 0
                    mock.first = pass_input_mock
                elif 'button[name="login"]' in sel or 'button[type="submit"]' in sel:
                    mock.count.return_value = 1
                    mock.first = submit_btn_mock
                elif '[data-pagelet*="ThreadList"]' in sel or 'div._a6ag._a6ah' in sel:
                    is_inbox = "/latest/inbox" in mock_page.url
                    mock.first.count.return_value = 1 if is_inbox else 0
                    mock.first.is_visible.return_value = is_inbox
                else:
                    mock.first.count.return_value = 0
                    mock.first.is_visible.return_value = False
                    mock.count.return_value = 0
                return mock

            mock_page.locator.side_effect = page_locator_side_effect

            res = await verify_logged_in(mock_page)
            self.assertTrue(res)

            # Khẳng định 100%: Clean Slate đã chủ động dọn dẹp cookies và storage!
            mock_page.context.clear_cookies.assert_awaited_once()
            mock_page.evaluate.assert_awaited()
            # Khẳng định điền email và password
            email_input_mock.fill.assert_awaited_with(test_email)
            pass_input_mock.fill.assert_awaited_with(test_pass)
            submit_btn_mock.click.assert_awaited()

    @patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock)
    @patch("bot.auth_helper.export_github_secret_file")
    @patch("bot.auth_helper.sync_storage_secret_to_github")
    async def test_clean_slate_graceful_when_clear_cookies_throws(self, mock_sync, mock_export, mock_sleep):
        """
        Đảm bảo nếu clear_cookies hoặc evaluate ném ngoại lệ, luồng Clean Slate
        không bị crash mà vẫn tiếp tục điều hướng an toàn.
        """
        with patch.dict(os.environ, {"FB_EMAIL": "test@dan86.vn", "FB_PASSWORD": "Pass!"}):
            mock_page = MagicMock()
            mock_page.url = "https://business.facebook.com/business/loginpage/?next=..."
            mock_page.context = MagicMock()
            mock_page.context.clear_cookies = AsyncMock(side_effect=RuntimeError("Browser context closed"))
            mock_page.evaluate = AsyncMock(side_effect=RuntimeError("Execution context destroyed"))
            mock_page.context.storage_state = AsyncMock()
            mock_page.context.cookies = AsyncMock(return_value=[{"name": "c_user", "value": "123"}])

            async def fake_goto(url, **kwargs):
                mock_page.url = url

            mock_page.goto = AsyncMock(side_effect=fake_goto)

            def page_loc(sel):
                mock = AsyncMock()
                if 'input[name="email"]' in sel or 'input[name="pass"]' in sel or 'button[name="login"]' in sel:
                    mock.count.return_value = 1
                    mock.first = AsyncMock(count=AsyncMock(return_value=1))
                elif '[data-pagelet*="ThreadList"]' in sel:
                    mock.first.count.return_value = 1 if "/latest/inbox" in mock_page.url else 0
                    mock.first.is_visible.return_value = True
                else:
                    mock.first.count.return_value = 0
                    mock.first.is_visible.return_value = False
                    mock.count.return_value = 0
                return mock

            mock_page.locator.side_effect = page_loc

            res = await verify_logged_in(mock_page)
            self.assertTrue(res)

    @patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock)
    @patch("bot.auth_helper.export_github_secret_file")
    @patch("bot.auth_helper.sync_storage_secret_to_github")
    async def test_clean_slate_post_reauth_handles_sso_popup_consent(self, mock_sync, mock_export, mock_sleep):
        """
        R3: Đảm bảo sau khi Clean Slate đăng nhập thành công vào facebook.com,
        nếu quay lại Meta Business Suite vẫn hiển thị nút SSO bắc cầu:
        Hệ thống tự động bắt popup SSO, bấm nút consent 'Tiếp tục dưới tên Đức Trí',
        chờ popup đóng và chuyển hướng thành công vào MBS Inbox.
        """
        test_email = "dan86_owner@dan86.vn"
        test_pass = "SecureCleanSlatePass123!"

        with patch.dict(os.environ, {"FB_EMAIL": test_email, "FB_PASSWORD": test_pass}):
            mock_page = MagicMock()
            mock_page.url = "https://business.facebook.com/business/loginpage/?next=..."
            mock_page.context = MagicMock()
            mock_page.context.clear_cookies = AsyncMock()
            mock_page.context.storage_state = AsyncMock()
            mock_page.evaluate = AsyncMock()
            mock_page.context.cookies = AsyncMock(return_value=[])

            # Popup mock
            mock_popup = MagicMock()
            mock_popup.is_closed.return_value = False
            mock_popup.wait_for_load_state = AsyncMock()
            mock_popup.url = "https://www.facebook.com/dialog/oauth"
            mock_popup.close = AsyncMock()
            async def fake_popup_close():
                mock_popup.is_closed.return_value = True
            mock_popup.close.side_effect = fake_popup_close

            consent_clicked = False

            def popup_loc(sel):
                nonlocal consent_clicked
                m = AsyncMock()
                if "Đức Trí" in sel or "Tiếp tục" in sel:
                    m.count = AsyncMock(return_value=1)
                    m.is_visible = AsyncMock(return_value=True)
                    async def fake_consent_click(**kwargs):
                        nonlocal consent_clicked
                        consent_clicked = True
                        mock_popup.is_closed.return_value = True
                    m.click = AsyncMock(side_effect=fake_consent_click)
                    m.first = m
                elif 'input[name="pass"]' in sel or 'input[type="password"]' in sel:
                    m.count = AsyncMock(return_value=0)
                else:
                    m.count = AsyncMock(return_value=0)
                    m.first = m
                return m

            mock_popup.locator.side_effect = popup_loc

            def on_page_listener(event, cb):
                cb(mock_popup)
            mock_page.context.on.side_effect = on_page_listener
            mock_page.context.remove_listener = MagicMock()

            login_count = 0

            async def fake_goto(url, **kwargs):
                mock_page.url = url
                if "/login.php" in url:
                    pass
                elif "/latest/inbox" in url:
                    if not consent_clicked:
                        mock_page.url = "https://business.facebook.com/business/loginpage/?next=..."
                    else:
                        mock_page.url = "https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512"

            mock_page.goto = AsyncMock(side_effect=fake_goto)

            async def fake_submit_click(**kwargs):
                nonlocal login_count
                login_count += 1
                mock_page.url = "https://www.facebook.com/"
                mock_page.context.cookies.return_value = [{"name": "c_user", "value": "100012345678"}]

            submit_btn_mock = AsyncMock(count=AsyncMock(return_value=1), click=AsyncMock(side_effect=fake_submit_click))
            email_input_mock = AsyncMock(count=AsyncMock(return_value=1), fill=AsyncMock())
            pass_input_mock = AsyncMock(count=AsyncMock(return_value=1), fill=AsyncMock())

            def page_locator_side_effect(sel):
                mock = AsyncMock()
                if 'input[name="email"]' in sel:
                    is_login_php = "/login.php" in mock_page.url
                    mock.count.return_value = 1 if is_login_php else 0
                    mock.first = email_input_mock
                elif 'input[name="pass"]' in sel:
                    is_login_php = "/login.php" in mock_page.url
                    mock.count.return_value = 1 if is_login_php else 0
                    mock.first = pass_input_mock
                elif 'button[name="login"]' in sel or 'button[type="submit"]' in sel:
                    mock.count.return_value = 1
                    mock.first = submit_btn_mock
                elif 'Tiếp tục bằng Facebook' in sel or 'Tiếp tục dưới tên' in sel:
                    has_sso = login_count > 0 and "/business/loginpage" in mock_page.url
                    mock.count.return_value = 1 if has_sso else 0
                    mock.first.count.return_value = 1 if has_sso else 0
                    mock.first.is_visible.return_value = has_sso
                    async def fake_sso_click(**kwargs):
                        mock_page.url = "https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512"
                    mock.first.click = AsyncMock(side_effect=fake_sso_click)
                    mock.last = mock.first
                elif '[data-pagelet*="ThreadList"]' in sel or 'div._a6ag._a6ah' in sel:
                    is_inbox = "/latest/inbox" in mock_page.url
                    mock.first.count.return_value = 1 if is_inbox else 0
                    mock.first.is_visible.return_value = is_inbox
                else:
                    mock.first.count.return_value = 0
                    mock.first.is_visible.return_value = False
                    mock.count.return_value = 0
                return mock

            mock_page.locator.side_effect = page_locator_side_effect

            res = await verify_logged_in(mock_page)
            self.assertTrue(res)
            self.assertTrue(consent_clicked)
            self.assertTrue(mock_popup.is_closed())


if __name__ == "__main__":
    unittest.main()
