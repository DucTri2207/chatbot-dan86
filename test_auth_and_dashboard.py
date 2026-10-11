"""
Kiểm thử tự động cho Auth Helper và Dashboard Monitor DAN86.
"""

import json
import os
import tempfile
import unittest

from bot.auth_helper import (
    extract_facebook_cookies,
    get_storage_state_status,
    sanitize_cookie,
    sync_facebook_credentials_from_dan86,
)
from dashboard import collect_dashboard_data, format_time_ago, format_timestamp


class TestAuthAndDashboard(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sample_cookies = [
            {
                "name": "c_user",
                "value": "100012345678",
                "domain": ".facebook.com",
                "path": "/",
                "secure": True,
                "httpOnly": False,
                "sameSite": "None",
                "expires": 1822665923.0,
            },
            {
                "name": "xs",
                "value": "abcdef123456",
                "domain": ".facebook.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "sameSite": "None",
                "expires": 1822665923.0,
            },
            {
                "name": "other_token",
                "value": "random",
                "domain": ".google.com",
                "path": "/",
            },
        ]
        self.source_json = os.path.join(self.temp_dir.name, "source_cookies.json")
        with open(self.source_json, "w", encoding="utf-8") as f:
            json.dump(self.sample_cookies, f)

        self.storage_file = os.path.join(self.temp_dir.name, "test_storage.json")
        self.secret_file = os.path.join(self.temp_dir.name, "test_secret.txt")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_sanitize_cookie(self) -> None:
        valid = {"name": "test", "value": "123", "domain": ".facebook.com"}
        res = sanitize_cookie(valid)
        self.assertIsNotNone(res)
        self.assertEqual(res["name"], "test")
        self.assertEqual(res["value"], "123")

        invalid = {"name": "", "value": "123"}
        self.assertIsNone(sanitize_cookie(invalid))

    def test_extract_and_sync(self) -> None:
        matched, meta = extract_facebook_cookies(self.source_json)
        self.assertEqual(len(matched), 2)
        self.assertTrue(meta["has_c_user"])
        self.assertTrue(meta["has_xs"])
        self.assertTrue(meta["is_authenticated"])

        res = sync_facebook_credentials_from_dan86(
            source_path=self.source_json,
            storage_path=self.storage_file,
            secret_path=self.secret_file,
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["cookies_count"], 2)
        self.assertTrue(os.path.exists(self.storage_file))
        self.assertTrue(os.path.exists(self.secret_file))

    def test_dashboard_formatting(self) -> None:
        self.assertEqual(format_time_ago(0), "Chưa xác định")
        self.assertEqual(format_timestamp(0), "--:--:--")

    def test_dashboard_data_collector(self) -> None:
        data = collect_dashboard_data()
        self.assertIn("stats", data)
        self.assertIn("counts", data)
        self.assertIn("conversations", data)
        self.assertIn("bot_status", data)
        self.assertIn("storage_state", data)
        self.assertIn("dan86_source", data)
        self.assertIn("vps_live", data)
        self.assertIn("is_running", data["vps_live"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
