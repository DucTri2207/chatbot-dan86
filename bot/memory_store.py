"""
Bộ nhớ lưu trữ trạng thái hội thoại & bình luận (Memory Store) cho Fanpage DAN86.
Đảm bảo:
1. Mỗi bình luận (Comment) chỉ được trả lời + gửi inbox riêng ĐÚNG 1 LẦN DUY NHẤT.
2. Khách nhắn Inbox lần đầu -> Gửi mẫu chào & tư vấn sản phẩm (Random xoay vòng).
3. Khách im một thời gian rồi nhắn lại (hoặc nhắn tiếp sau câu chào) -> Gửi đúng mẫu
   "Đợi nhân viên sẽ liên hệ lại ngay" (Random xoay vòng) rồi tạm ngưng để chờ nhân viên thật.
"""

import hashlib
import json
import os
import time
from typing import Any, Dict, Optional, Tuple

from bot.bot_config import (
    COMMENT_REPLIES,
    FIRST_INBOX_REPLIES,
    FOLLOWUP_MIN_SILENCE_SECONDS,
    MEMORY_FILE,
    PRIVATE_REPLIES_FROM_COMMENT,
    SILENCE_REMINDER_MINUTES,
    STATE_DIR,
    WAIT_STAFF_REPLIES,
    pick_template,
)


def normalize_text(text: str) -> str:
    """Chuẩn hóa chuỗi văn bản để so sánh và tạo mã băm (hash)."""
    return " ".join((text or "").strip().lower().split())


def make_comment_key(author_name: str, comment_text: str, comment_id: str = "") -> str:
    """Tạo khóa định danh duy nhất cho mỗi bình luận của khách."""
    if comment_id and comment_id.strip():
        return f"id:{comment_id.strip()}"
    raw = f"{normalize_text(author_name)}|{normalize_text(comment_text)}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"hash:{digest}"


def make_thread_key(customer_name: str, thread_id: str = "") -> str:
    """Tạo khóa định danh duy nhất cho mỗi cuộc hội thoại Inbox."""
    if thread_id and thread_id.strip():
        return f"tid:{thread_id.strip()}"
    norm_name = normalize_text(customer_name) or "unknown_customer"
    return f"name:{norm_name}"


class BotMemoryStore:
    """Quản lý đọc/ghi bền vững file state/bot_memory.json."""

    def __init__(self, memory_path: str = MEMORY_FILE) -> None:
        self.memory_path = memory_path
        os.makedirs(os.path.dirname(self.memory_path) or STATE_DIR, exist_ok=True)
        self.data: Dict[str, Any] = {
            "replied_comments": {},
            "conversations": {},
            "stats": {
                "comments_replied": 0,
                "private_inboxes_from_comment": 0,
                "first_inbox_replies": 0,
                "wait_staff_replies": 0,
            },
        }
        self.load()

    def load(self) -> None:
        """Nạp dữ liệu bộ nhớ từ ổ đĩa nếu tồn tại."""
        if not os.path.exists(self.memory_path):
            return
        try:
            with open(self.memory_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.data["replied_comments"] = loaded.get("replied_comments", {})
                self.data["conversations"] = loaded.get("conversations", {})
                if isinstance(loaded.get("stats"), dict):
                    self.data["stats"].update(loaded["stats"])
        except Exception:
            # Nếu file hỏng hoặc trống, giữ nguyên cấu trúc mặc định an toàn
            pass

    def save(self) -> None:
        """Lưu dữ liệu bộ nhớ xuống ổ đĩa an toàn (atomic write)."""
        os.makedirs(os.path.dirname(self.memory_path) or STATE_DIR, exist_ok=True)
        temp_path = f"{self.memory_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, self.memory_path)

    # ==========================================================================
    # XỬ LÝ BÌNH LUẬN (COMMENT + AUTO INBOX NGƯỜI COMMENT)
    # ==========================================================================
    def should_reply_comment(
        self,
        author_name: str,
        comment_text: str,
        has_page_reply_in_dom: bool = False,
        comment_id: str = "",
    ) -> Tuple[bool, str]:
        """
        Kiểm tra xem bình luận này có cần trả lời hay không.
        Trả về (True/False, comment_key).
        """
        key = make_comment_key(author_name, comment_text, comment_id)
        if not normalize_text(comment_text):
            return False, key
        if has_page_reply_in_dom:
            return False, key
        if key in self.data["replied_comments"]:
            return False, key
        return True, key

    def prepare_comment_and_inbox_replies(
        self, customer_name: str
    ) -> Tuple[str, str]:
        """
        Sinh ngẫu nhiên (Random không lặp):
        1. Câu trả lời bình luận công khai (public_reply)
        2. Câu nhắn tin riêng vào Inbox cho người bình luận đó (private_inbox_reply)
        """
        public_reply = pick_template(
            COMMENT_REPLIES,
            customer_name=customer_name,
            category_key="comment_public",
        )
        private_inbox_reply = pick_template(
            PRIVATE_REPLIES_FROM_COMMENT,
            customer_name=customer_name,
            category_key="comment_private_inbox",
        )
        return public_reply, private_inbox_reply

    def mark_comment_replied(
        self,
        comment_key: str,
        author_name: str,
        comment_text: str,
        public_reply: str,
        private_inbox_sent: bool,
        private_reply_text: str = "",
        now_ts: Optional[float] = None,
    ) -> None:
        """Đánh dấu bình luận đã được trả lời và đã gửi inbox riêng."""
        ts = now_ts if now_ts is not None else time.time()
        self.data["replied_comments"][comment_key] = {
            "author": author_name,
            "comment_text": comment_text,
            "public_reply": public_reply,
            "private_inbox_sent": bool(private_inbox_sent),
            "private_reply_text": private_reply_text,
            "replied_at": ts,
        }
        self.data["stats"]["comments_replied"] += 1
        if private_inbox_sent:
            self.data["stats"]["private_inboxes_from_comment"] += 1

        # Đồng thời ghi nhận trạng thái hội thoại của khách này ở Stage 1
        # để nếu khách trả lời lại tin nhắn inbox đó thì Bot tự chuyển sang mẫu "Đợi nhân viên"!
        if private_inbox_sent and author_name:
            t_key = make_thread_key(author_name)
            if t_key not in self.data["conversations"]:
                self.data["conversations"][t_key] = {
                    "customer_name": author_name,
                    "stage": 1,
                    "last_replied_customer_msg": normalize_text(comment_text),
                    "last_bot_reply_ts": ts,
                    "source": "comment_private_reply",
                }
        self.save()

    # ==========================================================================
    # XỬ LÝ TIN NHẮN HỘP THƯ (MESSENGER INBOX 3 GIAI ĐOẠN)
    # ==========================================================================
    def decide_inbox_action(
        self,
        customer_name: str,
        last_message_text: str,
        last_sender_is_page: bool,
        has_prior_page_messages_in_dom: bool = False,
        thread_id: str = "",
        now_ts: Optional[float] = None,
    ) -> Tuple[str, str, str]:
        """
        Quyết định hành động cho cuộc hội thoại Messenger Inbox.
        Trả về bộ 3 giá trị: (action_type, reply_text, thread_key)
        Trong đó `action_type` thuộc:
          - "NONE": Không nhắn gì cả (khi tin cuối là của Page hoặc đang chờ nhân viên).
          - "FIRST_REPLY": Khách nhắn lần đầu -> Gửi mẫu chào & tư vấn lần 1 (Random).
          - "WAIT_STAFF_REPLY": Khách nhắn tiếp / im một thời gian rồi nhắn lại -> Gửi mẫu
                                "Đợi nhân viên sẽ liên hệ lại ngay" (Random).
        """
        ts = now_ts if now_ts is not None else time.time()
        t_key = make_thread_key(customer_name, thread_id)
        norm_msg = normalize_text(last_message_text)

        # 1. Nếu không có nội dung tin nhắn hoặc tin nhắn cuối cùng là của chính Fanpage -> Bỏ qua
        if not norm_msg or last_sender_is_page:
            return "NONE", "", t_key

        record = self.data["conversations"].get(t_key)
        # Fallback tìm theo tên khách nếu trước đó lưu từ comment_private_reply (chưa có thread_id)
        if record is None and thread_id:
            name_key = make_thread_key(customer_name, "")
            if name_key in self.data["conversations"]:
                record = self.data["conversations"].pop(name_key)
                self.data["conversations"][t_key] = record

        # 2. Trường hợp khách hoàn toàn mới (chưa có trong bộ nhớ & trên DOM chưa có tin nhắn của Page)
        if record is None and not has_prior_page_messages_in_dom:
            reply_text = pick_template(
                FIRST_INBOX_REPLIES,
                customer_name=customer_name,
                category_key="first_inbox",
            )
            return "FIRST_REPLY", reply_text, t_key

        # 3. Trường hợp trên giao diện DOM đã từng có tin nhắn của Page nhưng bộ nhớ chưa lưu
        if record is None and has_prior_page_messages_in_dom:
            reply_text = pick_template(
                WAIT_STAFF_REPLIES,
                customer_name=customer_name,
                category_key="wait_staff",
            )
            return "WAIT_STAFF_REPLY", reply_text, t_key

        # 4. Đã có hồ sơ hội thoại trong bộ nhớ
        assert record is not None
        stage = int(record.get("stage", 1))
        last_replied_msg = record.get("last_replied_customer_msg", "")
        last_bot_ts = float(record.get("last_bot_reply_ts", 0))
        elapsed_seconds = ts - last_bot_ts

        # Nếu tin nhắn cuối cùng trên màn hình vẫn chính là tin nhắn mà Bot vừa trả lời -> Không rep lại
        if norm_msg == last_replied_msg and elapsed_seconds < SILENCE_REMINDER_MINUTES * 60:
            return "NONE", "", t_key

        if stage == 1:
            # Khách đã nhận câu chào lần 1, sau đó nhắn lại (hoặc im một lúc rồi nhắn tiếp)
            if elapsed_seconds >= FOLLOWUP_MIN_SILENCE_SECONDS or norm_msg != last_replied_msg:
                reply_text = pick_template(
                    WAIT_STAFF_REPLIES,
                    customer_name=customer_name,
                    category_key="wait_staff",
                )
                return "WAIT_STAFF_REPLY", reply_text, t_key
            return "NONE", "", t_key

        # Stage >= 2: Bot đã gửi câu "Đợi nhân viên sẽ liên hệ lại ngay" rồi.
        # Giữ im lặng tuyệt đối để nhường nhân viên thật, trừ khi khách im lặng quá lâu (> 120 phút) rồi nhắn lại.
        if elapsed_seconds >= SILENCE_REMINDER_MINUTES * 60:
            reply_text = pick_template(
                WAIT_STAFF_REPLIES,
                customer_name=customer_name,
                category_key="wait_staff",
            )
            return "WAIT_STAFF_REPLY", reply_text, t_key

        return "NONE", "", t_key

    def record_inbox_reply(
        self,
        thread_key: str,
        customer_name: str,
        customer_message_text: str,
        action_type: str,
        reply_text: str,
        now_ts: Optional[float] = None,
    ) -> None:
        """Ghi nhận Bot vừa gửi tin nhắn trả lời trong Messenger Inbox."""
        ts = now_ts if now_ts is not None else time.time()
        new_stage = 1 if action_type == "FIRST_REPLY" else 2
        self.data["conversations"][thread_key] = {
            "customer_name": customer_name,
            "stage": new_stage,
            "last_replied_customer_msg": normalize_text(customer_message_text),
            "last_bot_reply_text": reply_text,
            "last_bot_reply_ts": ts,
        }
        if action_type == "FIRST_REPLY":
            self.data["stats"]["first_inbox_replies"] += 1
        elif action_type == "WAIT_STAFF_REPLY":
            self.data["stats"]["wait_staff_replies"] += 1
        self.save()
