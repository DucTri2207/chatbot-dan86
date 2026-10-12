"""
Empirical Verification Harness for Challenger 2
Tests:
- R2 & R3: Memory Store Logic & needs_inbox_only behavior
- Edge cases: system labels, multiple comments, domIndex stability, timing boundaries (10799s vs 10800s)
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.bot_config import is_system_label
from bot.memory_store import BotMemoryStore, make_comment_key, make_thread_key



class TestEmpiricalChallenger2(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.temp_file.close()
        self.memory = BotMemoryStore(memory_path=self.temp_file.name)

    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            try:
                os.remove(self.temp_file.name)
            except Exception:
                pass

    def test_r2_needs_inbox_only_logic_flow(self):
        """
        Verify the exact candidate selection loop logic from bot/page_bot_engine.py:
        - records with private_inbox_sent: False get targeted with needs_inbox_only = True
        - records with private_inbox_sent: True get skipped
        - records with no page reply get targeted with needs_inbox_only = False
        - records with external page reply but no memory record get targeted with needs_inbox_only = True
        """
        post_id = "post_1001"

        # Case 1: unreplied comment on DOM, not in memory
        cand1 = {
            "author_name": "Nguyen Van A",
            "comment_text": "Gia bao nhieu shop?",
            "dom_index": 0,
            "has_page_reply": False,
        }

        # Case 2: comment already has public reply in DOM, but private_inbox_sent is False
        cand2 = {
            "author_name": "Tran Thi B",
            "comment_text": "Cho minh xin thong tin san pham",
            "dom_index": 1,
            "has_page_reply": True,
        }
        # Mark cand2 as replied in memory, but private_inbox_sent = False
        _, key2 = self.memory.should_reply_comment(
            author_name=cand2["author_name"],
            comment_text=cand2["comment_text"],
            has_page_reply_in_dom=False,
            post_id=post_id,
            dom_index=cand2["dom_index"],
        )
        self.memory.mark_comment_replied(
            comment_key=key2,
            author_name=cand2["author_name"],
            comment_text=cand2["comment_text"],
            public_reply="Da chao ban!",
            private_inbox_sent=False,
        )

        # Case 3: comment already has public reply in DOM, and private_inbox_sent is True
        cand3 = {
            "author_name": "Le Van C",
            "comment_text": "Set qua dep qua",
            "dom_index": 2,
            "has_page_reply": True,
        }
        _, key3 = self.memory.should_reply_comment(
            author_name=cand3["author_name"],
            comment_text=cand3["comment_text"],
            has_page_reply_in_dom=False,
            post_id=post_id,
            dom_index=cand3["dom_index"],
        )
        self.memory.mark_comment_replied(
            comment_key=key3,
            author_name=cand3["author_name"],
            comment_text=cand3["comment_text"],
            public_reply="Da cam on ban!",
            private_inbox_sent=True,
            private_reply_text="DAN86 gui bang gia a",
        )

        # Case 4: comment has public reply in DOM, but NOT in memory at all (e.g. replied via mobile app)
        cand4 = {
            "author_name": "Pham Thi D",
            "comment_text": "Ib minh nhe",
            "dom_index": 3,
            "has_page_reply": True,
        }

        # Case 5: system label comment (must be completely ignored)
        cand5 = {
            "author_name": "Chỉ báo trạng thái online",
            "comment_text": "Online",
            "dom_index": 4,
            "has_page_reply": True,
        }

        # Simulate candidate loop from page_bot_engine.py
        def evaluate_candidate(cand):
            author = cand["author_name"]
            text = cand["comment_text"]
            idx = cand["dom_index"]
            has_reply = cand["has_page_reply"]

            should_rep, comment_key = self.memory.should_reply_comment(
                author_name=author,
                comment_text=text,
                has_page_reply_in_dom=has_reply,
                post_id=post_id,
                dom_index=idx,
            )
            if should_rep:
                return "FULL_REPLY", comment_key, False

            if has_reply and comment_key:
                existing_rec = self.memory.data["replied_comments"].get(comment_key)
                if not existing_rec or not existing_rec.get("private_inbox_sent"):
                    return "INBOX_ONLY", comment_key, True

            return "SKIP", comment_key, False

        # Verify Cand 1: Needs full reply
        action1, k1, inbox1 = evaluate_candidate(cand1)
        self.assertEqual(action1, "FULL_REPLY")
        self.assertFalse(inbox1)

        # Verify Cand 2: Needs inbox only (retry)
        action2, k2, inbox2 = evaluate_candidate(cand2)
        self.assertEqual(action2, "INBOX_ONLY")
        self.assertTrue(inbox2)
        self.assertEqual(k2, key2)

        # Verify Cand 3: Fully handled -> Must SKIP
        action3, k3, inbox3 = evaluate_candidate(cand3)
        self.assertEqual(action3, "SKIP")
        self.assertFalse(inbox3)

        # Verify Cand 4: DOM has reply, memory has nothing -> Needs inbox only
        action4, k4, inbox4 = evaluate_candidate(cand4)
        self.assertEqual(action4, "INBOX_ONLY")
        self.assertTrue(inbox4)

        # Verify Cand 5: System label -> Must SKIP, key is empty
        action5, k5, inbox5 = evaluate_candidate(cand5)
        self.assertEqual(action5, "SKIP")
        self.assertEqual(k5, "")
        self.assertFalse(inbox5)

    def test_r3_inbox_180min_silence_boundary_conditions(self):
        """
        Adversarial test on silence boundary:
        10799s (179m59s) -> NONE (Must not trigger WAIT_STAFF_REPLY)
        10800s (180m00s) -> WAIT_STAFF_REPLY (Exact boundary triggers)
        10801s (180m01s) -> WAIT_STAFF_REPLY
        """
        customer = "Hoang Minh"
        t0 = 1000000.0

        # Stage 0 -> 1: First message
        action, reply, t_key = self.memory.decide_inbox_action(
            customer_name=customer,
            last_message_text="Chao shop",
            last_sender_is_page=False,
            has_prior_page_messages_in_dom=False,
            thread_id="thread_123",
            now_ts=t0,
        )
        self.assertEqual(action, "FIRST_REPLY")
        self.memory.record_inbox_reply(
            thread_key=t_key,
            customer_name=customer,
            customer_message_text="Chao shop",
            action_type="FIRST_REPLY",
            reply_text=reply,
            now_ts=t0,
        )

        # Test at t0 + 10799s (1 second before 3 hours)
        action_under, _, _ = self.memory.decide_inbox_action(
            customer_name=customer,
            last_message_text="Con hang khong shop?",
            last_sender_is_page=False,
            thread_id="thread_123",
            now_ts=t0 + 10799.0,
        )
        self.assertEqual(action_under, "NONE", "At 179m59s silence, bot must remain silent for human staff")

        # Test at t0 + 10800s (exactly 180 minutes)
        action_exact, reply_exact, _ = self.memory.decide_inbox_action(
            customer_name=customer,
            last_message_text="Con hang khong shop?",
            last_sender_is_page=False,
            thread_id="thread_123",
            now_ts=t0 + 10800.0,
        )
        self.assertEqual(action_exact, "WAIT_STAFF_REPLY", "At exactly 180m silence, bot sends wait staff reply")
        self.assertTrue(len(reply_exact) > 0)

        # Record wait staff reply
        self.memory.record_inbox_reply(
            thread_key=t_key,
            customer_name=customer,
            customer_message_text="Con hang khong shop?",
            action_type="WAIT_STAFF_REPLY",
            reply_text=reply_exact,
            now_ts=t0 + 10800.0,
        )

        # If customer sends message again right after wait staff reply (< 180m):
        action_after, _, _ = self.memory.decide_inbox_action(
            customer_name=customer,
            last_message_text="Vang em doi a",
            last_sender_is_page=False,
            thread_id="thread_123",
            now_ts=t0 + 10860.0,
        )
        self.assertEqual(action_after, "NONE", "After WAIT_STAFF_REPLY, bot remains completely silent")

    def test_persistence_atomic_write_recovery(self):
        """
        Verify that save() and load() preserve all fields and stats across re-instantiation.
        """
        post_id = "post_atom"
        _, key = self.memory.should_reply_comment("User Atom", "Text Atom", False, post_id=post_id, dom_index=0)
        self.memory.mark_comment_replied(key, "User Atom", "Text Atom", "Reply Atom", True, "Inbox Atom")

        # Reload new store instance from same file
        reloaded = BotMemoryStore(memory_path=self.temp_file.name)
        self.assertIn(key, reloaded.data["replied_comments"])
        self.assertTrue(reloaded.data["replied_comments"][key]["private_inbox_sent"])
        self.assertEqual(reloaded.data["stats"]["comments_replied"], 1)
        self.assertEqual(reloaded.data["stats"]["private_inboxes_from_comment"], 1)

    def test_corrupted_json_resilience(self):
        """
        Adversarial test: If memory file contains corrupted JSON or broken data,
        BotMemoryStore must safely keep default structure without crashing.
        """
        with open(self.temp_file.name, "w", encoding="utf-8") as f:
            f.write("{ INVALID JSON DATA %%%")

        store = BotMemoryStore(memory_path=self.temp_file.name)
        self.assertIsInstance(store.data["replied_comments"], dict)
        self.assertIsInstance(store.data["conversations"], dict)
        self.assertEqual(store.data["stats"]["comments_replied"], 0)

    def test_special_char_and_sticker_handling(self):
        """
        Adversarial test: Ensure single character '.', emojis, stickers, and mixed case
        are correctly accepted and never cause crashes or false rejections.
        """
        post_id = "post_emoji"
        inputs = [
            ("Nguyễn Văn A ❤️", ".", 0),
            ("ĐẶNG THỊ B", "[Sticker / GIPHY]", 1),
            ("   Lê   Văn   C   ", "🌻🌿", 2),
            ("User 4", "123", 3),
        ]
        for author, text, idx in inputs:
            should_rep, key = self.memory.should_reply_comment(
                author_name=author,
                comment_text=text,
                has_page_reply_in_dom=False,
                post_id=post_id,
                dom_index=idx,
            )
            self.assertTrue(should_rep, f"Failed to accept valid comment input: author={author}, text={text}")
            self.assertTrue(key.startswith(f"cmt:{post_id}:{idx}:"))


if __name__ == "__main__":
    unittest.main()

