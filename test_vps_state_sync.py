"""
Unit tests cho cơ chế đồng bộ trạng thái VPS GitHub Actions và Smart Merge Memory.
"""

import json
import os
import tempfile
import unittest

from bot.state_sync import (
    safe_load_json,
    safe_save_json,
    smart_merge_memory,
    sync_state_to_github,
)
from bot.memory_store import BotMemoryStore


class TestVpsStateSync(unittest.TestCase):

    def test_smart_merge_memory_union_comments(self):
        local = {
            "replied_comments": {
                "cmt:1": {"author": "A", "comment_text": "hello", "private_inbox_sent": False},
                "cmt:2": {"author": "B", "comment_text": "price?", "private_inbox_sent": True},
            },
            "conversations": {},
            "stats": {"comments_replied": 2, "private_inboxes_from_comment": 1},
        }

        remote = {
            "replied_comments": {
                "cmt:1": {"author": "A", "comment_text": "hello", "private_inbox_sent": True, "private_reply_text": "inbox_ok"},
                "cmt:3": {"author": "C", "comment_text": "order", "private_inbox_sent": False},
            },
            "conversations": {},
            "stats": {"comments_replied": 2, "private_inboxes_from_comment": 1},
        }

        merged, changed = smart_merge_memory(local, remote)
        self.assertTrue(changed)
        # Đảm bảo giữ đủ 3 comment không mất bất kỳ bản ghi nào
        self.assertEqual(len(merged["replied_comments"]), 3)
        self.assertIn("cmt:1", merged["replied_comments"])
        self.assertIn("cmt:2", merged["replied_comments"])
        self.assertIn("cmt:3", merged["replied_comments"])

        # cmt:1 được nâng cấp trạng thái private_inbox_sent từ False -> True
        self.assertTrue(merged["replied_comments"]["cmt:1"]["private_inbox_sent"])
        self.assertEqual(merged["replied_comments"]["cmt:1"]["private_reply_text"], "inbox_ok")

        # cmt:2 giữ nguyên
        self.assertTrue(merged["replied_comments"]["cmt:2"]["private_inbox_sent"])

        # stats được tính toán lại chính xác
        self.assertEqual(merged["stats"]["comments_replied"], 3)
        self.assertEqual(merged["stats"]["private_inboxes_from_comment"], 2)

    def test_smart_merge_memory_conversations_progression(self):
        local = {
            "replied_comments": {},
            "conversations": {
                "tid:user1": {"customer_name": "User 1", "stage": 1, "last_bot_reply_ts": 1000, "last_interaction_ts": 1000},
                "tid:user2": {"customer_name": "User 2", "stage": 1, "last_bot_reply_ts": 3000, "last_interaction_ts": 3000},
            },
            "stats": {},
        }

        remote = {
            "replied_comments": {},
            "conversations": {
                "tid:user1": {"customer_name": "User 1", "stage": 2, "last_bot_reply_ts": 2000, "last_interaction_ts": 2000},
                "tid:user3": {"customer_name": "User 3", "stage": 1, "last_bot_reply_ts": 1500, "last_interaction_ts": 1500},
            },
            "stats": {"wait_staff_replies": 1},
        }

        merged, changed = smart_merge_memory(local, remote)
        self.assertTrue(changed)
        self.assertEqual(len(merged["conversations"]), 3)
        # user1 lấy bản ghi remote vì có stage 2 và timestamp mới hơn
        self.assertEqual(merged["conversations"]["tid:user1"]["stage"], 2)
        self.assertEqual(merged["conversations"]["tid:user1"]["last_bot_reply_ts"], 2000)

        # user2 giữ nguyên
        self.assertEqual(merged["conversations"]["tid:user2"]["last_bot_reply_ts"], 3000)

        # user3 được bổ sung
        self.assertIn("tid:user3", merged["conversations"])
        self.assertEqual(merged["stats"]["wait_staff_replies"], 1)

    def test_safe_load_save_atomic(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_file = os.path.join(tmp_dir, "test_state.json")
            self.assertEqual(safe_load_json(target_file), {})

            data = {"hello": "world", "count": 42}
            saved = safe_save_json(target_file, data)
            self.assertTrue(saved)
            self.assertTrue(os.path.exists(target_file))
            self.assertFalse(os.path.exists(f"{target_file}.tmp"))

            loaded = safe_load_json(target_file)
            self.assertEqual(loaded, data)

    def test_bot_memory_store_merge_from_dict(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            mem_file = os.path.join(tmp_dir, "memory.json")
            store = BotMemoryStore(memory_path=mem_file)
            store.data["replied_comments"]["cmt:10"] = {"author": "Nam", "comment_text": "alo", "private_inbox_sent": False}
            store.save()

            remote_dict = {
                "replied_comments": {
                    "cmt:10": {"author": "Nam", "comment_text": "alo", "private_inbox_sent": True, "private_reply_text": "rep Nam"},
                    "cmt:20": {"author": "Lan", "comment_text": "co qua khong", "private_inbox_sent": False},
                },
                "conversations": {},
                "stats": {"comments_replied": 2, "private_inboxes_from_comment": 1},
            }

            changed = store.merge_from_dict(remote_dict)
            self.assertTrue(changed)
            self.assertEqual(len(store.data["replied_comments"]), 2)
            self.assertTrue(store.data["replied_comments"]["cmt:10"]["private_inbox_sent"])

            # Kiểm tra tính bền vững trên ổ đĩa
            reloaded_store = BotMemoryStore(memory_path=mem_file)
            self.assertEqual(len(reloaded_store.data["replied_comments"]), 2)
            self.assertTrue(reloaded_store.data["replied_comments"]["cmt:10"]["private_inbox_sent"])

    def test_sync_state_to_github_guard_when_no_actions(self):
        # Khi không có biến môi trường GITHUB_ACTIONS và force=False, hàm trả về True ngay lập tức
        old_env = os.environ.pop("GITHUB_ACTIONS", None)
        try:
            self.assertTrue(sync_state_to_github(force=False))
        finally:
            if old_env is not None:
                os.environ["GITHUB_ACTIONS"] = old_env


if __name__ == "__main__":
    unittest.main()
