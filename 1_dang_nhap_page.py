"""
Bước 1: Đăng nhập & Kết nối Fanpage DAN86 (Dần86Farm).
Hỗ trợ tái sử dụng trực tiếp Chrome Profile & Cookies sẵn có tại d:\\dan86
(d:\\dan86\\dan86_saved_cookies.json và d:\\dan86\\.chrome_profile).

Ưu điểm vượt trội:
- SIÊU NHẸ: Chỉ lưu file trạng thái JSON ~3.8 KB vào state/fb_storage_state.json.
- KHÔNG TỐN DUNG LƯỢNG Ổ CỨNG: Không tạo thêm thư mục profile Chrome nặng hàng trăm MB trong dự án!
- TỰ ĐỘNG: Lấy ngay cookies đăng nhập có sẵn trong 0.05 giây mà không cần người dùng nhập lại tài khoản!
"""

import argparse
import asyncio
import base64
import json
import os
import sys

# Đảm bảo in tiếng Việt có dấu chuẩn UTF-8 trên Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from playwright.async_api import async_playwright

from bot.auth_helper import (
    extract_facebook_cookies,
    get_storage_state_status,
    sync_facebook_credentials_from_dan86,
)
from bot.bot_config import (
    CHROME_PROFILE_DIR,
    DAN86_SYSTEM_COOKIES_FILE,
    DAN86_SYSTEM_PROFILE_DIR,
    GITHUB_SECRET_EXPORT_FILE,
    META_INBOX_ALL_URL,
    STATE_DIR,
    STORAGE_STATE_FILE,
)


def print_header() -> None:
    print("=" * 76)
    print("   DAN86 BOT - BƯỚC 1: KẾT NỐI & ĐĂNG NHẬP FANPAGE (SIÊU NHẸ - 0MB RÁC)")
    print("=" * 76)


def auto_sync_from_existing() -> bool:
    """Tự động trích xuất cookies từ d:\\dan86 vào state/fb_storage_state.json."""
    print("👉 Đang tìm kiếm Profile & Cookies Facebook có sẵn tại d:\\dan86...")
    res = sync_facebook_credentials_from_dan86()
    if res.get("success"):
        print("\n" + "=" * 76)
        print("✅ ĐÃ KẾT NỐI TỰ ĐỘNG THÀNH CÔNG VỚI PROFILE CÓ SẴN!")
        print(f"   - Nguồn cookies        : {DAN86_SYSTEM_COOKIES_FILE}")
        print(f"   - Số lượng cookies FB  : {res.get('cookies_count')} cookies (Bao gồm c_user, xs, datr, sb)")
        print(f"   - File lưu trữ phiên   : {res.get('storage_file')} ({res.get('storage_size_bytes')} bytes ~3.8 KB)")
        print(f"   - Mã khóa GitHub VPS   : {res.get('secret_file')}")
        print("   - Dung lượng tiết kiệm : Không tạo profile mới, tiết kiệm 100% ổ cứng!")
        print("=" * 76)
        print("👉 Bây giờ bạn có thể:")
        print("   1. Chạy '2_CHAY_THU_TREN_MAY.bat' để xem Bot trực tiếp trả lời Fanpage.")
        print("   2. Chạy '4_MO_DASHBOARD.bat' để mở Dashboard theo dõi thời gian thực!")
        print("   3. Đẩy lên VPS GitHub Actions theo hướng dẫn trong '3_DAY_LEN_VPS_GITHUB.bat'.")
        return True
    else:
        print(f"❌ Không thể tự động trích xuất: {res.get('message')}")
        return False


async def launch_interactive_login(profile_dir: str) -> None:
    """Mở trình duyệt trực tiếp để kiểm tra hoặc đăng nhập lại."""
    print(f"\n👉 Đang khởi động trình duyệt Chrome với profile: {profile_dir}...")
    os.makedirs(profile_dir, exist_ok=True)

    async with async_playwright() as p:
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-notifications",
                ],
                viewport={"width": 1440, "height": 900},
                locale="vi-VN",
            )
        except Exception as e:
            print(f"⚠️ Không thể mở persistent profile (có thể Chrome đang mở): {e}")
            print("👉 Đang chuyển sang mở trình duyệt tạm...")
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                locale="vi-VN",
            )

        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(META_INBOX_ALL_URL, wait_until="domcontentloaded")

        await asyncio.to_thread(
            input,
            "\n👉 Sau khi đã nhìn thấy rõ Hộp thư Fanpage Dần86Farm trên màn hình,\n"
            "   nhấn phím [ENTER] tại đây để lưu khóa đăng nhập: ",
        )

        current_url = page.url
        state_data = await context.storage_state(path=STORAGE_STATE_FILE)

        # Lọc gọn cookies facebook & messenger
        fb_cookies = [
            c
            for c in state_data.get("cookies", [])
            if any(k in c.get("domain", "") for k in ["facebook.com", "messenger.com", "meta.com"])
        ]
        compact_state = {"cookies": fb_cookies, "origins": []}
        compact_json = json.dumps(compact_state, ensure_ascii=False)
        b64_secret = base64.b64encode(compact_json.encode("utf-8")).decode("ascii")

        with open(STORAGE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(compact_state, f, ensure_ascii=False, indent=2)

        with open(GITHUB_SECRET_EXPORT_FILE, "w", encoding="utf-8") as f:
            f.write(b64_secret)

        await context.close()

    print("\n" + "=" * 76)
    print("✅ ĐÃ LƯU PHIÊN ĐĂNG NHẬP THÀNH CÔNG!")
    print(f"   - URL hiện tại : {current_url}")
    print(f"   - File phiên   : {STORAGE_STATE_FILE}")
    print(f"   - Mã cho VPS   : {GITHUB_SECRET_EXPORT_FILE}")
    print("=" * 76)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Đăng nhập / Đồng bộ phiên Fanpage DAN86")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Tự động trích xuất cookies từ d:\\dan86 không mở trình duyệt.",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Mở trình duyệt trực tiếp để đăng nhập thủ công.",
    )
    return parser.parse_args()


async def main() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    print_header()

    args = parse_args()
    has_existing_cookies = os.path.exists(DAN86_SYSTEM_COOKIES_FILE)
    has_existing_profile = os.path.exists(DAN86_SYSTEM_PROFILE_DIR)

    if args.auto:
        auto_sync_from_existing()
        return

    if args.browser:
        target_profile = DAN86_SYSTEM_PROFILE_DIR if has_existing_profile else CHROME_PROFILE_DIR
        await launch_interactive_login(target_profile)
        return

    # Menu tương tác thông minh
    print("Trạng thái Profile hiện có trên máy:")
    print(f"  • Cookies d:\\dan86 : {'✅ TÌM THẤY' if has_existing_cookies else '❌ CHƯA CÓ'}")
    print(f"  • Profile d:\\dan86 : {'✅ TÌM THẤY' if has_existing_profile else '❌ CHƯA CÓ'}")

    curr_status = get_storage_state_status()
    if curr_status.get("exists"):
        print(f"  • Phiên hiện tại   : ✅ Đã có ({curr_status.get('cookies_count')} cookies, cập nhật lúc {curr_status.get('last_modified_str')})")
    print("-" * 76)

    print("Chọn phương thức đăng nhập:")
    print("  [1] (Khuyên dùng - Siêu nhẹ, 0MB rác): Lấy phiên từ Profile/Cookies có sẵn tại d:\\dan86")
    print("      (Tự động xong trong 0.05 giây, không cần gõ mật khẩu, dung lượng chỉ ~3.8 KB)")
    print("  [2] Mở trình duyệt Chrome trực tiếp để kiểm tra / đăng nhập lại Hộp thư Meta")
    print("  [3] Thoát")
    print("-" * 76)

    try:
        choice = input("👉 Nhập lựa chọn của bạn [1, 2, 3] (mặc định là 1): ").strip()
    except EOFError:
        choice = "1"

    if choice in ("", "1"):
        success = auto_sync_from_existing()
        if not success and has_existing_profile:
            print("Chuyển sang mở trình duyệt để kiểm tra...")
            await launch_interactive_login(DAN86_SYSTEM_PROFILE_DIR)
    elif choice == "2":
        target = DAN86_SYSTEM_PROFILE_DIR if has_existing_profile else CHROME_PROFILE_DIR
        await launch_interactive_login(target)
    else:
        print("Đã thoát.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nĐã hủy.")
        sys.exit(0)
