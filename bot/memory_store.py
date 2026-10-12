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


def make_comment_key(
    author_name: str,
    comment_text: str,
    comment_id: str = "",
    post_id: str = "",
    dom_index: int = 0,
) -> str:
    """
    Tạo khóa định danh duy nhất cho mỗi bình luận của khách.
    - Kết hợp: post_id (selected_item_id) + normalize_text(author_name) + normalize_text(comment_text).
    - Ổn định và bền vững: Không bị thay đổi khóa khi thứ tự DOM / domIndex thay đổi.
    """
    from bot.bot_config import clean_customer_name
    c_name = clean_customer_name(author_name) if author_name else ""
    norm_author = normalize_text(c_name or author_name)
    norm_text = normalize_text(comment_text)

    # Ưu tiên tạo key kết hợp post_id + dom_index + author + text
    if post_id and str(post_id).strip():
        pid = str(post_id).strip()
        raw = f"{pid}|{dom_index}|{norm_author}|{norm_text}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"cmt:{pid}:{dom_index}:{digest}"

    # Nếu có comment_id riêng biệt (không trùng post_id)
    if comment_id and str(comment_id).strip():
        cid = str(comment_id).strip()
        raw = f"{cid}|{dom_index}|{norm_author}|{norm_text}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"id:{cid}:{dom_index}:{digest}"

    # Fallback cho trường hợp không có post_id (như trong unit test cơ bản)
    raw = f"{dom_index}|{norm_author}|{norm_text}" if dom_index > 0 else f"{norm_author}|{norm_text}"
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
        except Exception as e:
            # Nếu file hỏng nhưng có dữ liệu, tạo bản sao lưu khẩn cấp để không bị mất
            if os.path.exists(self.memory_path) and os.path.getsize(self.memory_path) > 10:
                try:
                    bak_path = f"{self.memory_path}.corrupted_{int(time.time())}"
                    import shutil
                    shutil.copyfile(self.memory_path, bak_path)
                except Exception:
                    pass

    def save(self) -> None:
        """Lưu dữ liệu bộ nhớ xuống ổ đĩa an toàn (atomic write)."""
        try:
            os.makedirs(os.path.dirname(self.memory_path) or STATE_DIR, exist_ok=True)
            temp_path = f"{self.memory_path}.tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, self.memory_path)
        except Exception:
            pass

    def merge_from_dict(self, other_data: Dict[str, Any]) -> bool:
        """
        Hợp nhất dữ liệu bộ nhớ từ nguồn ngoài (remote hoặc file khác) mà không làm mất comment/hội thoại nào.
        """
        if not isinstance(other_data, dict):
            return False

        changed = False

        # 1. Hợp nhất bình luận đã phản hồi
        other_comments = other_data.get("replied_comments", {})
        if isinstance(other_comments, dict):
            for k, v in other_comments.items():
                if not isinstance(v, dict):
                    continue
                if k not in self.data["replied_comments"]:
                    self.data["replied_comments"][k] = v
                    changed = True
                else:
                    cur = self.data["replied_comments"][k]
                    if isinstance(cur, dict):
                        if not cur.get("private_inbox_sent") and v.get("private_inbox_sent"):
                            cur["private_inbox_sent"] = True
                            if v.get("private_reply_text"):
                                cur["private_reply_text"] = v["private_reply_text"]
                            changed = True

        # 2. Hợp nhất hội thoại Messenger
        other_convs = other_data.get("conversations", {})
        if isinstance(other_convs, dict):
            for k, v in other_convs.items():
                if not isinstance(v, dict):
                    continue
                if k not in self.data["conversations"]:
                    self.data["conversations"][k] = v
                    changed = True
                else:
                    cur = self.data["conversations"][k]
                    if isinstance(cur, dict):
                        cur_ts = max(float(cur.get("last_bot_reply_ts", 0)), float(cur.get("last_interaction_ts", 0)))
                        v_ts = max(float(v.get("last_bot_reply_ts", 0)), float(v.get("last_interaction_ts", 0)))
                        if v_ts > cur_ts:
                            self.data["conversations"][k] = v
                            changed = True
                        elif v.get("stage", 0) > cur.get("stage", 0):
                            cur["stage"] = v["stage"]
                            changed = True

        # 3. Đồng bộ thống kê
        total_cmts = len(self.data["replied_comments"])
        total_inbox = sum(
            1 for c in self.data["replied_comments"].values() if isinstance(c, dict) and c.get("private_inbox_sent")
        )
        if self.data["stats"].get("comments_replied", 0) != total_cmts:
            self.data["stats"]["comments_replied"] = total_cmts
            changed = True
        if self.data["stats"].get("private_inboxes_from_comment", 0) != total_inbox:
            self.data["stats"]["private_inboxes_from_comment"] = total_inbox
            changed = True

        other_stats = other_data.get("stats", {})
        if isinstance(other_stats, dict):
            for stat_k in ("first_inbox_replies", "wait_staff_replies"):
                if other_stats.get(stat_k, 0) > self.data["stats"].get(stat_k, 0):
                    self.data["stats"][stat_k] = other_stats[stat_k]
                    changed = True

        if changed:
            self.save()

        return changed

    # ==========================================================================
    # XỬ LÝ BÌNH LUẬN (COMMENT + AUTO INBOX NGƯỜI COMMENT)
    # ==========================================================================
    def get_comment_record(
        self,
        comment_key: str = "",
        author_name: str = "",
        comment_text: str = "",
        post_id: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        Tìm kiếm bản ghi bình luận đã được xử lý trong bộ nhớ:
        1. Tìm trực tiếp theo comment_key chính xác.
        2. Nếu không thấy (do dom_index thay đổi khi DOM re-render), tìm theo (author_name + comment_text + post_id).
        """
        if comment_key and comment_key in self.data.get("replied_comments", {}):
            return self.data["replied_comments"][comment_key]

        from bot.bot_config import clean_customer_name
        c_name = clean_customer_name(author_name) if author_name else ""
        norm_author = normalize_text(c_name or author_name)
        norm_text = normalize_text(comment_text)
        pid_clean = str(post_id).strip()

        if not norm_author or norm_author == "bạn":
            return None

        norm_words = set(norm_author.split())
        for rk, rv in self.data.get("replied_comments", {}).items():
            if isinstance(rv, dict):
                r_author = normalize_text(rv.get("author", ""))
                r_text = normalize_text(rv.get("comment_text", ""))
                r_pid = str(rv.get("post_id", "")).strip()

                is_author_match = (r_author == norm_author) or (
                    len(norm_words) > 1 and norm_words == set(r_author.split())
                )
                if r_author and is_author_match:
                    if r_text and norm_text and r_text == norm_text:
                        if pid_clean:
                            if pid_clean in rk or (r_pid and r_pid == pid_clean):
                                return rv
                        else:
                            return rv
        return None

    def is_customer_in_cooldown(
        self,
        customer_name: str,
        cooldown_seconds: float = 300.0,
        now_ts: Optional[float] = None,
        post_id: str = "",
        comment_text: str = "",
    ) -> bool:
        """
        Kiểm tra khách hàng có đang trong thời gian cooldown chống spam hay không.
        - Nếu có post_id: Chỉ áp dụng cooldown trên chính bài viết đó (tránh rep lặp trên cùng bài viết,
          nhưng khi khách bình luận trên bài viết khác hoặc có bình luận mới thì vẫn được phản hồi ngay lập tức!).
        - Hỗ trợ nhận diện đảo ngữ tên khách (ví dụ: 'Đức Trí' và 'Trí Đức').
        """
        from bot.bot_config import clean_customer_name
        clean_name = clean_customer_name(customer_name) if customer_name else ""
        norm_name = normalize_text(clean_name or customer_name)
        if not norm_name or norm_name == "bạn":
            return False

        current_time = now_ts if now_ts is not None else time.time()
        norm_words = set(norm_name.split())
        target_pid = str(post_id).strip()
        norm_cmt = normalize_text(comment_text) if comment_text else ""

        # 1. Kiểm tra trong các bình luận đã trả lời
        for rk, rv in self.data.get("replied_comments", {}).items():
            if isinstance(rv, dict):
                r_author = normalize_text(rv.get("author", ""))
                r_ts = float(rv.get("replied_at", 0))
                r_pid = str(rv.get("post_id", "")).strip()

                if r_author:
                    is_match = (r_author == norm_name) or (
                        len(norm_words) > 1 and norm_words == set(r_author.split())
                    )
                    if is_match:
                        # Nếu có chỉ định post_id: chỉ tính cooldown trên cùng bài viết đó
                        if target_pid:
                            match_post = (target_pid == r_pid) or (target_pid in rk)
                            if not match_post:
                                continue
                            # Nếu có comment_text và nội dung khác nhau: cho phép phản hồi câu mới
                            if norm_cmt:
                                r_text = normalize_text(rv.get("comment_text", ""))
                                if r_text and r_text != norm_cmt:
                                    continue
                        else:
                            # Khi chưa biết post_id (vd quét từ trang thông báo):
                            # Nếu có comment_text và nội dung khác với bình luận đã rep trước đó:
                            # Cho phép phản hồi bình luận mới, KHÔNG bị chặn oan!
                            if norm_cmt:
                                r_text = normalize_text(rv.get("comment_text", ""))
                                if r_text and r_text != norm_cmt:
                                    continue

                        diff = current_time - r_ts
                        if -5 <= diff < cooldown_seconds:
                            return True

        # 2. Kiểm tra trong các cuộc hội thoại inbox (chỉ khi không giới hạn theo bài viết cụ thể và không phải kiểm tra bình luận)
        if not target_pid and not norm_cmt:
            for tk, tv in self.data.get("conversations", {}).items():
                if isinstance(tv, dict):
                    c_name = normalize_text(tv.get("customer_name", ""))
                    last_reply = float(tv.get("last_bot_reply_ts", 0))
                    if c_name:
                        is_match = (c_name == norm_name) or (
                            len(norm_words) > 1 and norm_words == set(c_name.split())
                        )
                        if is_match:
                            diff = current_time - last_reply
                            if -5 <= diff < cooldown_seconds:
                                return True

        return False

    def should_reply_comment(
        self,
        author_name: str,
        comment_text: str,
        has_page_reply_in_dom: bool = False,
        comment_id: str = "",
        post_id: str = "",
        dom_index: int = 0,
        now_ts: Optional[float] = None,
        customer_cooldown_seconds: float = 0.0,
    ) -> Tuple[bool, str]:
        """
        Kiểm tra xem bình luận này có cần trả lời hay không.
        Trả về (True/False, comment_key).
        Quy tắc:
        1. Tên tác giả là nhãn hệ thống -> Bỏ qua.
        2. Nếu trên DOM thực tế ĐÃ CÓ câu trả lời của Page ngay dưới bình luận này (has_page_reply_in_dom == True) -> Bỏ qua.
        3. Chấp nhận mọi bình luận của khách kể cả 1 ký tự ('.', icon, sticker, số, chữ ngắn).
        4. Kiểm tra trong bộ nhớ:
           - Khóa định danh duy nhất của bình luận này đã nằm trong replied_comments.
           - Hoặc đã tồn tại bản ghi bình luận cùng tác giả + cùng nội dung trên cùng bài viết (tránh lệch dom_index).
        5. Kiểm tra cooldown chống spam cấp độ khách hàng nếu customer_cooldown_seconds > 0.
        """
        from bot.bot_config import clean_customer_name, is_system_label
        
        # 1. Nếu tên tác giả bị dính nhãn hệ thống (ví dụ: "Chỉ báo trạng thái online"), tuyệt đối không trả lời
        if is_system_label(author_name):
            return False, ""

        clean_name = clean_customer_name(author_name)
        if clean_name == "bạn" and is_system_label(author_name):
            return False, ""

        key = make_comment_key(
            author_name=clean_name,
            comment_text=comment_text,
            comment_id=comment_id,
            post_id=post_id,
            dom_index=dom_index,
        )

        # 2. Nếu trên DOM thực tế đã có phản hồi của Page ngay dưới bình luận này -> Tuyệt đối không trả lời trùng
        if has_page_reply_in_dom:
            return False, key

        # 3. Cho phép bình luận ngắn, sticker, emoji, dấu chấm:
        # Chỉ từ chối khi bình luận hoàn toàn trống rỗng không có ký tự hay nội dung nào
        norm_text = normalize_text(comment_text)
        if not norm_text and not comment_text:
            return False, key

        # 4. Kiểm tra trong bộ nhớ:
        # 4.1 Khóa định danh duy nhất của bình luận này đã nằm trong replied_comments
        if key in self.data["replied_comments"]:
            rec = self.data["replied_comments"][key]
            p_reply = str(rec.get("public_reply", ""))
            if (p_reply.startswith("(Bỏ qua") or p_reply.startswith("(Đã phản hồi")) and not has_page_reply_in_dom:
                pass
            else:
                return False, key

        # 4.2 Kiểm tra nếu bình luận này đã được rep trước đó trên cùng bài viết (tránh lệch key khi dom_index thay đổi)
        existing_rec = self.get_comment_record(
            comment_key=key,
            author_name=clean_name,
            comment_text=comment_text,
            post_id=post_id,
        )
        if existing_rec is not None:
            p_reply = str(existing_rec.get("public_reply", ""))
            if (p_reply.startswith("(Bỏ qua") or p_reply.startswith("(Đã phản hồi")) and not has_page_reply_in_dom:
                pass
            else:
                return False, key

        # 5. Cooldown chống spam cấp độ khách hàng (nếu được kích hoạt)
        current_time = now_ts if now_ts is not None else time.time()
        if customer_cooldown_seconds > 0:
            if self.is_customer_in_cooldown(clean_name, cooldown_seconds=customer_cooldown_seconds, now_ts=current_time):
                return False, key

        # Chống gửi lặp trong cùng 1 phiên ngắn (cooldown chống spam khách hàng liên tục)
        from bot.bot_config import CUSTOMER_ANTI_SPAM_COOLDOWN_SECONDS

        for rk, rv in self.data["replied_comments"].items():
            if isinstance(rv, dict):
                r_author = normalize_text(rv.get("author", ""))
                r_text = normalize_text(rv.get("comment_text", ""))
                r_ts = float(rv.get("replied_at", 0))
                if r_author and r_author == normalize_text(clean_name):
                    if r_text and norm_text and r_text == norm_text:
                        if post_id and str(post_id).strip() in rk and (current_time - r_ts < CUSTOMER_ANTI_SPAM_COOLDOWN_SECONDS):
                            return False, rk

        # Nếu trên DOM thực tế chưa có phản hồi của Page và chưa rep trong memory -> Bắt buộc trả lời!
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
        post_id: str = "",
        dom_index: int = 0,
    ) -> None:
        """Đánh dấu bình luận đã được trả lời và đã gửi inbox riêng."""
        from bot.bot_config import clean_customer_name
        ts = now_ts if now_ts is not None else time.time()
        c_name = clean_customer_name(author_name)

        pid = str(post_id).strip()
        d_idx = dom_index
        if comment_key and comment_key.startswith("cmt:"):
            parts = comment_key.split(":")
            if len(parts) >= 4:
                if not pid:
                    pid = parts[1]
                if d_idx == 0 and parts[2].isdigit():
                    d_idx = int(parts[2])

        existing = self.data["replied_comments"].get(comment_key, {})
        inbox_attempts = existing.get("inbox_attempts", 0) + 1

        self.data["replied_comments"][comment_key] = {
            "author": c_name,
            "comment_text": comment_text,
            "public_reply": public_reply or existing.get("public_reply", ""),
            "private_inbox_sent": bool(private_inbox_sent or existing.get("private_inbox_sent", False)),
            "private_reply_text": private_reply_text or existing.get("private_reply_text", ""),
            "replied_at": existing.get("replied_at", ts) if (existing and not private_inbox_sent) else ts,
            "post_id": pid,
            "dom_index": d_idx,
            "inbox_attempts": inbox_attempts,
        }
        self.data["stats"]["comments_replied"] += 1
        if private_inbox_sent:
            self.data["stats"]["private_inboxes_from_comment"] += 1

        # Đồng thời ghi nhận trạng thái hội thoại của khách này ở Stage 1
        if private_inbox_sent and c_name:
            t_key = make_thread_key(c_name)
            if t_key not in self.data["conversations"]:
                self.data["conversations"][t_key] = {
                    "customer_name": c_name,
                    "stage": 1,
                    "last_replied_customer_msg": normalize_text(comment_text),
                    "last_bot_reply_ts": ts,
                    "source": "comment_private_reply",
                }
            else:
                self.data["conversations"][t_key]["last_bot_reply_ts"] = ts
        self.save()

    # ==========================================================================
    # XỬ LÝ TIN NHẮN HỘP THƯ (MESSENGER INBOX CHUẨN THƯƠNG MẠI)
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
        Quyết định hành động cho cuộc hội thoại Messenger Inbox:
        1. Cứ khi nào khách nhắn lần đầu -> Bot rep DUY NHẤT 1 tin chào & tư vấn,
           sau đó DỪNG HOÀN TOÀN để nhân viên vào trả lời.
        2. Kể cả khách nhắn thêm tin thứ 2, thứ 3 ngay sau đó -> Bot vẫn giữ im lặng nhường nhân viên.
        3. CHỈ KHI NÀO 2 bên im lặng quá lâu tầm 3 tiếng (>= 180 phút) mà khách nhắn lại tin mới,
           lúc đó Bot mới rep DUY NHẤT 1 tin chờ nhân viên rồi lại dừng nhường nhân viên!
        """
        from bot.bot_config import clean_customer_name
        ts = now_ts if now_ts is not None else time.time()
        c_name = clean_customer_name(customer_name)
        t_key = make_thread_key(c_name, thread_id)
        norm_msg = normalize_text(last_message_text)

        # 1. Nếu không có nội dung tin nhắn hoặc tin nhắn cuối cùng là của chính Fanpage -> Bỏ qua
        if not norm_msg or last_sender_is_page:
            return "NONE", "", t_key

        record = self.data["conversations"].get(t_key)
        # Fallback tìm theo tên khách nếu trước đó lưu từ comment_private_reply (chưa có thread_id)
        if record is None and thread_id:
            name_key = make_thread_key(c_name, "")
            if name_key in self.data["conversations"]:
                record = self.data["conversations"].pop(name_key)
                self.data["conversations"][t_key] = record

        # 2. Trường hợp khách hoàn toàn mới (chưa có trong bộ nhớ & trên DOM chưa có tin nhắn của Page)
        if record is None and not has_prior_page_messages_in_dom:
            reply_text = pick_template(
                FIRST_INBOX_REPLIES,
                customer_name=c_name,
                category_key="first_inbox",
            )
            return "FIRST_REPLY", reply_text, t_key

        # 3. Trường hợp trên giao diện DOM đã từng có tin nhắn của Page nhưng bộ nhớ chưa lưu
        if record is None and has_prior_page_messages_in_dom:
            # Ghi nhận khách đã ở Stage 1 (đã có Page trả lời) để nhường nhân viên xử lý
            self.data["conversations"][t_key] = {
                "customer_name": c_name,
                "stage": 1,
                "last_replied_customer_msg": norm_msg,
                "last_bot_reply_ts": ts,
                "last_interaction_ts": ts,
                "source": "prior_history",
            }
            self.save()
            return "NONE", "", t_key

        # 4. Đã có hồ sơ hội thoại trong bộ nhớ
        assert record is not None
        last_replied_msg = record.get("last_replied_customer_msg", "")
        last_bot_ts = float(record.get("last_bot_reply_ts", 0))
        last_interaction_ts = float(record.get("last_interaction_ts", last_bot_ts))
        elapsed_seconds = ts - max(last_bot_ts, last_interaction_ts)
        silence_threshold = SILENCE_REMINDER_MINUTES * 60  # 180 phút = 10,800 giây (3 tiếng)

        # Nếu tin nhắn cuối cùng trên màn hình vẫn chính là tin nhắn mà Bot vừa trả lời -> Không rep lại
        if norm_msg == last_replied_msg and elapsed_seconds < silence_threshold:
            return "NONE", "", t_key

        # Nếu 2 bên im lặng quá lâu tầm 3 tiếng mà khách nhắn lại tin mới:
        # Bot rep DUY NHẤT 1 tin chờ nhân viên (WAIT_STAFF_REPLY), rồi lại dừng để chờ nhân viên
        if elapsed_seconds >= silence_threshold:
            # Nếu vừa rep WAIT_STAFF_REPLY cho chính nội dung tin nhắn này rồi thì không rep lại nữa
            if record.get("stage") == 2 and norm_msg == last_replied_msg:
                return "NONE", "", t_key

            reply_text = pick_template(
                WAIT_STAFF_REPLIES,
                customer_name=c_name,
                category_key="wait_staff",
            )
            return "WAIT_STAFF_REPLY", reply_text, t_key

        # Nếu chưa đủ 3 tiếng: Bot giữ im lặng tuyệt đối ("NONE") để nhân viên thật trả lời khách
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
            "last_interaction_ts": ts,
        }
        if action_type == "FIRST_REPLY":
            self.data["stats"]["first_inbox_replies"] += 1
        elif action_type == "WAIT_STAFF_REPLY":
            self.data["stats"]["wait_staff_replies"] += 1
        self.save()

    def touch_staff_interaction(
        self,
        customer_name: str,
        thread_id: str = "",
        now_ts: Optional[float] = None,
    ) -> None:
        """Ghi nhận Fanpage / nhân viên thật vừa tương tác trong hội thoại (reset mốc tính 3 tiếng im lặng)."""
        from bot.bot_config import clean_customer_name
        ts = now_ts if now_ts is not None else time.time()
        c_name = clean_customer_name(customer_name)
        t_key = make_thread_key(c_name, thread_id)
        if t_key in self.data["conversations"]:
            self.data["conversations"][t_key]["last_interaction_ts"] = ts
            self.data["conversations"][t_key]["stage"] = 1
            self.save()
