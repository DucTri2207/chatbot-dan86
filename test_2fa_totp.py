import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.page_bot_engine import (
    generate_totp_code,
    handle_facebook_2fa_checkpoint,
)


class Test2FATOTP(unittest.TestCase):
    def test_generate_totp_code_valid(self):
        secret = "JBSWY3DPEHPK3PXP"
        code = generate_totp_code(secret, for_time=1700000000)
        self.assertTrue(code.isdigit())
        self.assertEqual(len(code), 6)

    def test_generate_totp_code_with_spaces_and_quotes(self):
        secret = ' "JBSW Y3DP EHPK 3PXP" '
        code = generate_totp_code(secret, for_time=1700000000)
        self.assertTrue(code.isdigit())
        self.assertEqual(len(code), 6)
        expected = generate_totp_code("JBSWY3DPEHPK3PXP", for_time=1700000000)
        self.assertEqual(code, expected)

    def test_generate_totp_code_empty_and_invalid(self):
        self.assertEqual(generate_totp_code(""), "")
        self.assertEqual(generate_totp_code(None), "")
        self.assertEqual(generate_totp_code("!@#$%^&*()"), "")

    def test_handle_facebook_2fa_checkpoint_mock_success(self):
        mock_page = MagicMock()
        mock_page.url = "https://www.facebook.com/checkpoint/?next=https..."
        mock_page.is_closed = MagicMock(return_value=False)

        mock_input = MagicMock()
        mock_input.first = mock_input
        mock_input.count = AsyncMock(return_value=1)
        mock_input.click = AsyncMock()
        mock_input.fill = AsyncMock()
        mock_input.press = AsyncMock()

        mock_btn = MagicMock()
        mock_btn.first = mock_btn
        mock_btn.count = AsyncMock(return_value=1)
        mock_btn.click = AsyncMock()
        mock_btn.is_visible = AsyncMock(return_value=True)

        mock_radio = MagicMock()
        mock_radio.first = mock_radio
        mock_radio.count = AsyncMock(return_value=1)
        mock_radio.check = AsyncMock()

        def mock_locator(sel):
            if "approvals_code" in sel or "maxlength" in sel:
                return mock_input
            if "checkpointSubmitButton" in sel or "submit" in sel:
                return mock_btn
            if "save_device" in sel:
                return mock_radio
            loc = MagicMock()
            loc.count = AsyncMock(return_value=0)
            loc.is_visible = AsyncMock(return_value=False)
            return loc

        mock_page.locator = mock_locator
        mock_page.keyboard = MagicMock()
        mock_page.keyboard.type = AsyncMock()

        async def run():
            # Mock URL changing after submit to non-checkpoint
            async def delayed_url():
                await asyncio.sleep(0.01)
                mock_page.url = "https://www.facebook.com/home.php"

            asyncio.create_task(delayed_url())
            return await handle_facebook_2fa_checkpoint(mock_page, "JBSWY3DPEHPK3PXP")

        res = asyncio.run(run())
        self.assertTrue(res)
        self.assertTrue(mock_input.click.called or mock_input.fill.called)

    def test_handle_facebook_2fa_checkpoint_no_input(self):
        mock_page = MagicMock()
        mock_page.url = "https://www.facebook.com/checkpoint/"
        mock_page.is_closed = MagicMock(return_value=False)

        mock_empty = MagicMock()
        mock_empty.count = AsyncMock(return_value=0)
        mock_page.locator = MagicMock(return_value=mock_empty)

        res = asyncio.run(handle_facebook_2fa_checkpoint(mock_page, "JBSWY3DPEHPK3PXP"))
        self.assertFalse(res)


if __name__ == "__main__":
    unittest.main()
