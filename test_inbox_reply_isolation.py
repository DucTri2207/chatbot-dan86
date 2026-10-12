"""
Kiểm tra tính cô lập tuyệt đối của tin nhắn riêng (Private Inbox Isolation Test):
Đảm bảo nội dung tin nhắn riêng (private_reply_text) TUYỆT ĐỐI KHÔNG BAO GIỜ bị gõ
vào ô bình luận hay ô trả lời công khai của bài viết trên trang inbox/facebook.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.page_bot_engine import send_private_inbox_to_commenter


def make_async_locator(count_val=0, visible_val=False, aria_val="", placeholder_val=""):
    loc = MagicMock()
    loc.count = AsyncMock(return_value=count_val)
    loc.is_visible = AsyncMock(return_value=visible_val)
    loc.get_attribute = AsyncMock(side_effect=lambda a: aria_val if a == "aria-label" else (placeholder_val if a == "placeholder" else ""))
    loc.first = loc
    loc.last = loc
    loc.nth = MagicMock(return_value=loc)
    loc.press_sequentially = AsyncMock()
    loc.click = AsyncMock()
    loc.scroll_into_view_if_needed = AsyncMock()
    loc.evaluate = AsyncMock()
    return loc


class TestInboxReplyIsolation(unittest.TestCase):

    def test_private_reply_never_typed_into_comment_reply_boxes_when_on_facebook_tab(self):
        """
        Đảm bảo khi đang ở trang inbox/facebook:
        Nếu không có popup modal riêng (div[role="dialog"]), bot tuyệt đối KHÔNG coi đó là chat view
        và KHÔNG gõ private_reply_text vào các textbox trả lời bình luận công khai.
        """
        async def run_test():
            page = MagicMock()
            page.url = "https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512"
            page.evaluate = AsyncMock(return_value={"clicked": True, "text": "See Chat"})

            dialogs_mock = make_async_locator(count_val=0, visible_val=False)
            public_reply_textbox = make_async_locator(count_val=1, visible_val=True, aria_val="Viết câu trả lời...")
            chat_panel_mock = make_async_locator(count_val=0, visible_val=False)
            marked_btn_mock = make_async_locator(count_val=0, visible_val=False)

            def locator_router(selector):
                if 'data-dan86-msg-btn' in selector:
                    return marked_btn_mock
                if 'div[role="dialog"]' in selector:
                    return dialogs_mock
                if '[data-pagelet="ChatTab"]' in selector:
                    return chat_panel_mock
                if 'textbox' in selector or 'textarea' in selector:
                    return public_reply_textbox
                return make_async_locator(count_val=0, visible_val=False)

            page.locator = MagicMock(side_effect=locator_router)

            with patch("bot.page_bot_engine.send_inbox_via_messenger_search", new_callable=AsyncMock) as mock_fallback, \
                 patch("bot.page_bot_engine.dismiss_blocking_modals", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock):
                mock_fallback.return_value = False

                res = await send_private_inbox_to_commenter(
                    page=page,
                    post_url="https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512",
                    author_name="Nguyễn Văn A",
                    private_reply_text="DAN86 xin gửi bạn thông tin set quà...",
                    comment_text="Cho mình xin giá",
                    dom_index=0,
                )

                # Xác nhận: Textbox bình luận công khai tuyệt đối KHÔNG bị gõ tin nhắn riêng
                self.assertEqual(public_reply_textbox.press_sequentially.call_count, 0)
                # Xác nhận: Bot kích hoạt fallback sang Messenger thay vì gõ bừa vào ô comment
                mock_fallback.assert_awaited_once()
                self.assertFalse(res)

        import asyncio
        asyncio.run(run_test())

    def test_private_reply_rejected_if_dialog_is_comment_article_modal(self):
        """
        Đảm bảo nếu popup dialog là modal xem bài viết/bình luận (chứa aria-label='Viết bình luận...'),
        bot phát hiện và từ chối gõ private_reply_text vào đó.
        """
        async def run_test():
            page = MagicMock()
            page.url = "https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512"
            page.evaluate = AsyncMock(return_value={"clicked": False, "text": ""})

            # Dialog có hiển thị nhưng textbox trong dialog là ô bình luận
            comment_textbox_in_dialog = make_async_locator(count_val=1, visible_val=True, aria_val="Viết bình luận công khai...")
            dialog_mock = make_async_locator(count_val=1, visible_val=True)
            dialog_mock.locator = MagicMock(return_value=comment_textbox_in_dialog)

            chat_panel_mock = make_async_locator(count_val=0, visible_val=False)
            marked_btn_mock = make_async_locator(count_val=0, visible_val=False)

            def locator_router(selector):
                if 'data-dan86-msg-btn' in selector:
                    return marked_btn_mock
                if 'div[role="dialog"]' in selector:
                    return dialog_mock
                if '[data-pagelet="ChatTab"]' in selector:
                    return chat_panel_mock
                return make_async_locator(count_val=0, visible_val=False)

            page.locator = MagicMock(side_effect=locator_router)

            with patch("bot.page_bot_engine.send_inbox_via_messenger_search", new_callable=AsyncMock) as mock_fallback, \
                 patch("bot.page_bot_engine.dismiss_blocking_modals", new_callable=AsyncMock), \
                 patch("bot.page_bot_engine.human_sleep", new_callable=AsyncMock):
                mock_fallback.return_value = False

                res = await send_private_inbox_to_commenter(
                    page=page,
                    post_url="https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512",
                    author_name="Lê Thị B",
                    private_reply_text="DAN86 xin gửi bạn thông tin set quà...",
                    comment_text="Ib mình với",
                    dom_index=0,
                )

                # Không được gõ vào textbox bình luận trong dialog
                self.assertEqual(comment_textbox_in_dialog.press_sequentially.call_count, 0)
                mock_fallback.assert_awaited_once()
                self.assertFalse(res)

        import asyncio
        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
