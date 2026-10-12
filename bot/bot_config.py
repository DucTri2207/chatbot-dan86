"""
Cấu hình trung tâm cho Bot Trực Fanpage DAN86 (Dần86Farm) 24/24.
Tương thích 100% đa nền tảng (Windows Local PC & Ubuntu Linux trên GitHub Actions VPS).
Hỗ trợ Random câu trả lời chống trùng lặp liên tiếp (Anti-Spam Spintax).
"""

import os
import random
from typing import Dict, List

# Đường dẫn thư mục gốc dự án (tự động nhận diện trên cả Windows và Linux)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.join(BASE_DIR, "state")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# Profile & Cookies nguồn từ hệ thống d:\dan86 (dùng chung, không tạo thêm thư mục mới nặng máy)
DAN86_SYSTEM_PROFILE_DIR = r"d:\dan86\.chrome_profile"
DAN86_SYSTEM_COOKIES_FILE = r"d:\dan86\dan86_saved_cookies.json"

if os.path.exists(DAN86_SYSTEM_PROFILE_DIR):
    CHROME_PROFILE_DIR = DAN86_SYSTEM_PROFILE_DIR
else:
    CHROME_PROFILE_DIR = os.path.join(BASE_DIR, ".chrome_profile")

STORAGE_STATE_FILE = os.path.join(STATE_DIR, "fb_storage_state.json")
GITHUB_SECRET_EXPORT_FILE = os.path.join(STATE_DIR, "GITHUB_SECRET_VALUE.txt")
MEMORY_FILE = os.path.join(STATE_DIR, "bot_memory.json")
BOT_STATUS_FILE = os.path.join(STATE_DIR, "bot_status.json")

# URL Quản trị Hộp thư & Bình luận của Meta Business Suite (Dần86Farm ID: 104011958817512)
META_INBOX_ALL_URL = os.environ.get(
    "META_INBOX_URL",
    "https://business.facebook.com/latest/inbox/all?asset_id=104011958817512",
)
META_INBOX_MESSENGER_URL = os.environ.get(
    "META_MESSENGER_URL",
    "https://business.facebook.com/latest/inbox/messenger?asset_id=104011958817512",
)
META_INBOX_COMMENTS_URL = os.environ.get(
    "META_COMMENTS_URL",
    "https://business.facebook.com/latest/inbox/facebook?asset_id=104011958817512",
)

# Tên nhận diện Fanpage của mình (kiểm tra xem tin nhắn/bình luận cuối có phải của shop không)
PAGE_NAMES = [
    "dần86",
    "dan86",
    "dần 86",
    "dan 86",
    "dan86farm",
    "dần86farm",
    "bá lộc green",
    "ba loc green",
]

# Danh sách các cụm từ nhãn trạng thái hệ thống cấm kỵ (không bao giờ là tên người)
SYSTEM_PHRASES_BLACKLIST: List[str] = [
    "chỉ báo trạng thái online",
    "online status indicator",
    "đang hoạt động",
    "active now",
    "đang có mặt",
    "người dùng facebook",
    "facebook user",
    "hộp thư",
    "bình luận trên trang",
    "trao đổi thêm",
    "tạo quảng cáo",
    "thông tin chi tiết",
    "quy trình tự động hóa",
    "quảng bá",
    "xem thêm phản hồi",
    "xem 1 phản hồi",
    "xem phản hồi",
    "view more replies",
]

# Danh sách từ nhãn nút/hệ thống đơn lẻ (chỉ cấm khi trùng khớp hoàn toàn, tránh lọc nhầm tên người như 'Nguyễn Văn Ẩn')
EXACT_SYSTEM_LABELS = {
    "ẩn",
    "hide",
    "trả lời",
    "reply",
    "thích",
    "like",
    "bày tỏ cảm xúc",
    "theo dõi",
    "theo dõi lại",
    "follow",
    "follow back",
    "mới nhất",
    "phù hợp nhất",
    "tất cả bình luận",
    "xem thêm",
    "see more",
    "chưa đọc",
    "unread",
    "bạn",
    "khách",
    "user",
    "see chat",
    "chat",
    "gửi tin nhắn",
    "nhắn tin",
    "send message",
    "message",
    "tác giả",
    "author",
}

# Hợp nhất danh sách để tương thích ngược
SYSTEM_BLACKLIST_STRINGS: List[str] = SYSTEM_PHRASES_BLACKLIST + list(EXACT_SYSTEM_LABELS)

# CHẾ ĐỘ THỬ NGHIỆM AN TOÀN TRONG PHIÊN SỬA LỖI:
# Nếu danh sách này không rỗng, Bot TUYỆT ĐỐI CHỈ tương tác (rep cmt & gửi inbox) với các khách hàng trong danh sách này!
# Người dùng yêu cầu: "đừng gửi tin cmt cho bất cứ ai ngoài đức trí trong phiên sửa lỗi này"
TEST_ONLY_AUTHOR_WHITELIST: List[str] = [
    "đức trí",
    "trí đức",
    "duc tri",
    "tri duc",
]

# Cooldown chống Spam cấp độ khách hàng: Nếu một khách hàng vừa được rep trong vòng 60 giây gần nhất trên cùng bài viết, KHÔNG ĐƯỢC rep tiếp liên tục.
CUSTOMER_ANTI_SPAM_COOLDOWN_SECONDS: float = 60.0  # 60 giây (1 phút)


def is_system_label(text: str) -> bool:
    """Kiểm tra một chuỗi có phải là nhãn hệ thống/nút bấm của Facebook hay không."""
    if not text:
        return True
    norm = " ".join(str(text).lower().split())
    if norm in EXACT_SYSTEM_LABELS:
        return True
    if any(phrase in norm for phrase in SYSTEM_PHRASES_BLACKLIST):
        return True
    if any(p in norm for p in PAGE_NAMES):
        return True
    return False


def clean_customer_name(name: str) -> str:
    """Lọc sạch tên khách hàng, loại bỏ hoàn toàn các chuỗi nhãn hệ thống hoặc ký tự thừa."""
    import re
    if not name:
        return "bạn"
    cleaned = str(name).strip()

    # Hỗ trợ cả tiếng Việt và tiếng Anh aria-label:
    # 'Bình luận dưới tên Trí Đức vào 2 giờ trước'
    # 'Comment by Trí Đức 2 hours ago'
    # 'Bình luận dưới tên Trí Đức'
    aria_match = re.search(
        r"(?:bình luận dưới tên|comment by)\s+(.+?)(?:\s+(?:vào|at|ago|on)|\s*$)",
        cleaned,
        re.IGNORECASE,
    )
    if aria_match:
        cleaned = aria_match.group(1).strip()

    cleaned = cleaned.split("·")[0].split("•")[0].split("\n")[0].strip()
    # Loại bỏ phần timestamp thừa nếu có dính vào (vd: 'Trí Đức 1 phút', 'Trí Đức 2 giờ trước')
    cleaned = re.sub(
        r"\s+\d+\s+(?:giây|phút|giờ|ngày|tuần|tháng|năm|s|m|h|d|w|min|mins|hour|hours|day|days)\b.*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    norm = " ".join(cleaned.lower().split())
    if not norm or is_system_label(norm):
        return "bạn"
    if len(cleaned) < 2 or len(cleaned) > 50:
        return "bạn"
    return cleaned


# Thông số thời gian & Chống Facebook quét Spam (Human-like delays)
SCAN_INTERVAL_SECONDS = (15, 30)          # Khoảng nghỉ giữa mỗi chu kỳ quét (15 - 30 giây)
ACTION_COOLDOWN_SECONDS = (5, 10)         # Nghỉ ngơi giữa mỗi khách hàng (5 - 10 giây)
TYPING_DELAY_MS = (20, 45)                # Tốc độ gõ từng ký tự (ms) như người thật
SILENCE_REMINDER_MINUTES = 180            # 3 tiếng (180 phút): 2 bên im lặng quá 3 tiếng khách nhắn lại mới báo tin chờ 1 lần
MAX_THREADS_PER_CYCLE = 10                # Số hội thoại tối đa kiểm tra mỗi vòng quét (10 bài viết có hoạt động mới nhất)

# ==============================================================================
# 1. MẪU CÂU TRẢ LỜI BÌNH LUẬN CÔNG KHAI (RANDOM XOAY VÒNG - REP 1 LẦN DUY NHẤT)
# ==============================================================================
COMMENT_REPLIES: List[str] = [
    "Dạ chào {name}, DAN86 đã gửi thông tin chi tiết và bảng giá set quà vào tin nhắn cho mình rồi ạ. Bạn kiểm tra hộp thư/tin nhắn chờ giúp shop nhé! ❤️",
    "Dạ shop chào {name} ạ! DAN86 vừa nhắn tin tư vấn chi tiết set quà qua Messenger cho bạn rồi nhé. Bạn check inbox giúp shop nha! ✨",
    "Dạ cảm ơn {name} đã quan tâm đến Quà tặng thuần Việt DAN86! Shop đã chủ động inbox tư vấn cho mình rồi ạ, bạn vào xem nhé! 🎁",
    "Dạ chào {name}! DAN86 đã gửi hình ảnh thực tế và báo giá quà tặng vào tin nhắn cho mình rồi ạ. Cần hỗ trợ gấp bạn liên hệ Hotline/Zalo: 0933 133 516 nhé! 🌾",
    "Dạ chào {name}, DAN86 đã gửi tin nhắn riêng cho bạn rồi ạ. Bạn kiểm tra Messenger để shop tư vấn chi tiết set quà phù hợp nhất nhé! 🌿",
    "Dạ cảm ơn {name} đã để lại bình luận! Bên em vừa gửi mẫu kèm báo giá chi tiết vào hộp thư Messenger của mình rồi ạ, bạn mở tin nhắn xem giúp DAN86 nha! 🌸",
    "Dạ chào {name} ạ, shop đã inbox trực tiếp thông tin các set quà thuần Việt cho mình rồi nhé. Bạn kiểm tra mục tin nhắn hoặc tin nhắn chờ giúp shop ạ! 💖",
    "Dạ DAN86 xin chào {name}! Thông tin chi tiết và ưu đãi set quà đã được shop gửi vào Messenger của bạn rồi ạ. Bạn check hộp thư giúp shop nhé! 🎋",
]

# ==============================================================================
# 2. MẪU CÂU TỰ ĐỘNG INBOX RIÊNG CHO NGƯỜI BÌNH LUẬN (RANDOM XOAY VÒNG - 1 LẦN)
# ==============================================================================
PRIVATE_REPLIES_FROM_COMMENT: List[str] = [
    (
        "Chào {name}, DAN86 cảm ơn bạn đã để lại bình luận quan tâm đến sản phẩm! 🎁\n"
        "Bên em chuyên các set quà tặng thuần Việt tinh tế, mây tre đan thủ công, nông sản và thảo mộc thiên nhiên phù hợp làm quà tặng dịp lễ, quà đối tác, doanh nghiệp.\n"
        "🌐 Xem toàn bộ các set quà tại website: https://dan86.vn\n"
        "📞 Hotline / Zalo tư vấn nhanh: 0933 133 516\n"
        "Dạ bạn đang quan tâm set quà ngân sách khoảng bao nhiêu để shop tư vấn mẫu phù hợp nhất cho mình ạ?"
    ),
    (
        "Dạ shop chào {name} ạ! Cảm ơn bạn đã bình luận quan tâm đến Quà tặng thuần Việt DAN86 (CTY TNHH Bá Lộc Green). 🌾\n"
        "Hiện shop đang có sẵn nhiều mẫu set quà tặng tinh tế kết hợp đặc sản và thủ công truyền thống:\n"
        "- Hộp quà mây tre đan, túi cỏ bàng, khăn rằn dệt tay.\n"
        "- Nông sản rang mộc, trà thảo mộc hữu cơ, mật ong rừng, tinh dầu thiên nhiên.\n"
        "🌐 Chi tiết sản phẩm: https://dan86.vn | 📞 Zalo/Hotline: 0933 133 516\n"
        "Bạn đang cần tìm quà tặng cho cá nhân hay cho đoàn/doanh nghiệp để shop hỗ trợ mình ngay nhé!"
    ),
    (
        "Dạ DAN86 chào {name} nhé! Shop thấy mình vừa bình luận trên bài viết của trang nên nhắn tin hỗ trợ mình ngay ạ. ❤️\n"
        "Các set quà bên em đều được làm thủ công tỉ mỉ từ mây tre đan, cỏ bàng kết hợp đặc sản thuần Việt, nhận thiết kế riêng và in logo theo yêu cầu.\n"
        "🌐 Mời bạn xem mẫu & bảng giá tại: https://dan86.vn\n"
        "📞 Hotline / Zalo: 0933 133 516\n"
        "Dạ mình dự định đặt số lượng khoảng bao nhiêu set để bên em báo giá tốt nhất cho mình ạ?"
    ),
    (
        "Xin chào {name}! Cảm ơn bạn đã yêu thích các set quà mộc mạc thuần Việt của DAN86. 🌿\n"
        "Shop xin gửi thông tin để bạn dễ tham khảo:\n"
        "✨ Toàn bộ mẫu quà tặng mới nhất: https://dan86.vn\n"
        "✨ Hotline / Zalo tư vấn trực tiếp: 0933 133 516\n"
        "Dạ bạn đang tìm quà tặng cho dịp nào để nhân viên bên em gửi hình ảnh thực tế từng mẫu cho mình chọn nhé!"
    ),
    (
        "Dạ chào {name} ạ, DAN86 vừa nhận được bình luận của mình trên bài đăng! 🎁\n"
        "Bên em có đầy đủ các dòng set quà từ bình dân đến cao cấp (hộp mây tre, túi cỏ bàng, khăn rằn, cà phê phin, trà thảo mộc...).\n"
        "🌐 Website: https://dan86.vn\n"
        "📞 Zalo/Hotline hỗ trợ gấp: 0933 133 516\n"
        "Bạn cho shop xin nhu cầu hoặc mức ngân sách dự kiến để shop gửi mẫu chuẩn nhất cho mình nha!"
    ),
]

# ==============================================================================
# 3. MẪU CÂU CHÀO KHI KHÁCH NHẮN TIN LẦN ĐẦU VÀO HỘP THƯ (STAGE 1 - RANDOM)
# ==============================================================================
FIRST_INBOX_REPLIES: List[str] = [
    (
        "Dạ DAN86 xin chào {name}! Cảm ơn bạn đã nhắn tin cho shop. 🎁\n"
        "Hiện shop có các dòng quà tặng thuần Việt cao cấp và thân thiện môi trường:\n"
        "1. Set quà tặng cá nhân (dịp lễ, sinh nhật, tri ân).\n"
        "2. Set quà lưu niệm cho du khách, đoàn khách quốc tế.\n"
        "3. Quà tặng doanh nghiệp thiết kế theo yêu cầu (in logo, may đo riêng).\n\n"
        "🌐 Mời bạn tham khảo các mẫu mới nhất tại: https://dan86.vn\n"
        "📞 Hỗ trợ nhanh (Hotline/Zalo): 0933 133 516\n"
        "Dạ bạn đang cần tìm quà tặng cho dịp nào và số lượng bao nhiêu ạ? Shop sẽ hỗ trợ bạn ngay!"
    ),
    (
        "Dạ chào {name} ạ! Cảm ơn bạn đã liên hệ Quà tặng thuần Việt DAN86 (CTY TNHH Bá Lộc Green). 🌿\n"
        "Bên em chuyên cung cấp các set quà tặng thủ công mây tre đan, túi cỏ bàng, khăn rằn Nam Bộ, cà phê phin và đặc sản thiên nhiên Việt Nam.\n"
        "🌐 Danh mục sản phẩm & bảng giá: https://dan86.vn\n"
        "📞 Hotline / Zalo: 0933 133 516\n"
        "Dạ mình đang quan tâm mẫu quà tặng nào hoặc ngân sách khoảng bao nhiêu để DAN86 tư vấn chi tiết cho mình nhé!"
    ),
    (
        "Dạ shop chào {name}! Rất vui được đón tiếp bạn tại Fanpage Dần86Farm (DAN86). ❤️\n"
        "Bên em chuyên thiết kế các set quà tặng văn hóa thuần Việt (lẻ & sỉ doanh nghiệp, quà tặng đối tác nước ngoài, quà lễ/tri ân).\n"
        "🌐 Xem trọn bộ sưu tập tại: https://dan86.vn\n"
        "📞 Liên hệ nhanh qua Zalo/SĐT: 0933 133 516\n"
        "Bạn nhắn giúp shop mẫu bạn đang ưng ý hoặc số lượng cần đặt để shop báo giá chi tiết ngay nha!"
    ),
    (
        "Xin chào {name}! Cảm ơn bạn đã quan tâm đến sản phẩm của DAN86. 🌾\n"
        "Tất cả các set quà bên em đều được chăm chút tỉ mỉ từ chất liệu thủ công Việt Nam (mây tre, cỏ bàng, khăn rằn, nông sản sạch...).\n"
        "🌐 Tham khảo mẫu và giá tại: https://dan86.vn\n"
        "📞 Hotline / Zalo: 0933 133 516\n"
        "Dạ bạn đang cần tư vấn set quà cho cá nhân hay đơn hàng doanh nghiệp ạ?"
    ),
]

# ==============================================================================
# 4. MẪU CÂU KHI KHÁCH IM MỘT THỜI GIAN RỒI NHẮN LẠI / NHẮN TIẾP (STAGE 2 - RANDOM)
# ==============================================================================
WAIT_STAFF_REPLIES: List[str] = [
    (
        "Dạ DAN86 đã nhận được tin nhắn của {name} rồi ạ! "
        "Hiện nhân viên tư vấn của shop đang kiểm tra thông tin và sẽ liên hệ lại hỗ trợ mình ngay nhé. "
        "Nếu cần gấp bạn có thể gọi hoặc nhắn Zalo Hotline: 0933 133 516 ạ! ❤️"
    ),
    (
        "Dạ cảm ơn {name} đã nhắn tin cho DAN86! "
        "Shop đã ghi nhận nội dung của mình, bộ phận tư vấn sẽ phản hồi lại cho bạn ngay trong ít phút nữa nha. "
        "Cần hỗ trợ tức thì bạn liên hệ Hotline/Zalo: 0933 133 516 giúp shop nhé! 🌿"
    ),
    (
        "Dạ shop đã nhận được phản hồi của {name} ạ! "
        "Nhân viên trực page của DAN86 sẽ vào liên hệ và tư vấn chi tiết cho mình ngay bây giờ nhé. "
        "Hotline/Zalo hỗ trợ nhanh: 0933 133 516 ạ! 🎁"
    ),
    (
        "Dạ thông tin của {name} đã được chuyển tới bộ phận chăm sóc khách hàng của DAN86 rồi ạ! "
        "Bạn vui lòng đợi ít phút nhân viên bên em sẽ vào trả lời mình ngay nha. "
        "Nếu cần trao đổi gấp, bạn kết nối Zalo/Hotline: 0933 133 516 nhé! ✨"
    ),
    (
        "Dạ cảm ơn {name}! Hiện nhân viên tư vấn của DAN86 đang bận xử lý đơn trong giây lát và sẽ liên hệ lại với bạn ngay lập tức ạ. "
        "Bạn cũng có thể nhắn trực tiếp qua Zalo/Hotline: 0933 133 516 để được ưu tiên hỗ trợ ngay nhé! 🌾"
    ),
]

# Lưu chỉ mục mẫu câu vừa chọn gần nhất của từng nhóm để chống lặp 2 câu giống nhau liên tiếp
_LAST_PICKED_INDEX: Dict[str, int] = {}


def pick_template(
    templates: List[str],
    customer_name: str = "bạn",
    category_key: str = "default",
) -> str:
    """
    Chọn ngẫu nhiên 1 mẫu câu từ danh sách, đảm bảo KHÔNG trùng với mẫu câu
    vừa dùng ở lượt liền trước của cùng hạng mục (Anti-Repeat Randomization).
    """
    if not templates:
        return ""

    clean_name = clean_customer_name(customer_name)

    total = len(templates)
    if total == 1:
        idx = 0
    else:
        last_idx = _LAST_PICKED_INDEX.get(category_key, -1)
        candidates = [i for i in range(total) if i != last_idx]
        idx = random.choice(candidates)

    _LAST_PICKED_INDEX[category_key] = idx
    return templates[idx].format(name=clean_name)
