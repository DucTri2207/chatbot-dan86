# Original User Request

## 2026-10-11T23:38:37Z

Audit, harden, and verify the 24/7 automated Facebook Fanpage bot (`Dần86Farm - Sản phẩm và Quà tặng thuần Việt Nam`, `asset_id=104011958817512`) so it runs **100% on GitHub Actions VPS** (zero background bot processes on the user's local PC) and responds rapidly and reliably whenever a new comment or new Messenger message arrives.

Working directory: d:\chat bot dan 86
Integrity mode: development

## Requirements

### R1. Zero Local Execution — 100% Cloud VPS Operation
The bot must not run as a background process on the user's Windows PC. All continuous 24/7 scanning and replying must execute exclusively on the GitHub Actions VPS workflow (`DucTri2207/chatbot-dan86`, `.github/workflows/vps_bot_24_7.yml`), while the local Dashboard (`dashboard.py` / `dashboard.html`) only reads/syncs live state from GitHub without spawning local Playwright bot loops.

### R2. Immediate & Unconditional New Comment Handling (Public Reply + 1 Direct Inbox Message)
Whenever a new comment is posted on any Fanpage post (timestamps `vừa xong`, `giây`, `phút`, `giờ`, `hôm qua`, `1–3 ngày`), regardless of comment content (including single characters like `.`, emojis, stickers) and regardless of whether the commenter has commented or chatted in the past:
1. Never delete, hide, or mark any post as "Done" (`Đã xong`).
2. Strictly ignore old comments (`tuần`, `tháng`, `năm`, or `> 3 ngày`).
3. If the comment does not yet have a Page reply underneath it, post 1 non-repeating randomized nested public reply (`Nested Reply`) directly under that comment.
4. Whether or not the comment already had a public reply underneath it, if a private message has not yet been sent for that specific comment record in `state/bot_memory.json`, immediately send 1 direct private message (`Inbox`) to that commenter (via Popup Modal, `See Chat` composer, or Messenger search fallback) without pointer-event interception timeouts.

### R3. Immediate Automated Messenger Inbox Handling
Whenever a customer sends a direct message to the Fanpage Messenger Inbox (`inbox/messenger`):
1. Ensure the Messenger thread list selector reliably opens the top unread/recent conversation rows (`div[role="presentation"].x1ypdohk`, `div._a6ag._a6ah`) and accurately detects whether the last message is from the customer vs. the Page.
2. First-time customer message (`Stage 0 -> Stage 1`): immediately send 1 randomized greeting & product consultation message (`FIRST_INBOX_REPLIES`), then pause bot replies so human staff can take over.
3. Returning message after >= 180 minutes (3 hours) of mutual silence (`Stage 1 -> Stage 2`): send 1 randomized "please wait for staff" message (`WAIT_STAFF_REPLIES`), then remain silent.

### R4. Persistent Session & Fast VPS Loop Reliability
1. Preserve `origins` (`https://business.facebook.com` `localStorage`) and cookies in `state/fb_storage_state.json` and `state/GITHUB_SECRET_VALUE.txt` so the VPS session never redirects to `business/loginpage`.
2. Ensure the VPS scan loop runs continuously with minimal latency between cycles (`15–30s`), syncs `state/bot_memory.json` and `state/bot_status.json` to `origin/master` without Git rebase conflicts, and hands off shifts cleanly without getting stuck in `pending`.

## Verification Resources

- Existing unit test suites: `test_bot_logic.py` and `test_auth_and_dashboard.py` (`python -m unittest discover -s . -p "test_*.py" -v`).
- Live session state: `state/fb_storage_state.json` and GitHub repository `DucTri2207/chatbot-dan86`.
- Recent VPS logs in `state/bot_status.json` showing pointer-event interception (`subtree intercepts pointer events`) during click actions that must be eliminated.

## Acceptance Criteria

### Local PC Cleanliness
- [ ] Zero `2_chay_bot_truc_page.py` or Playwright `headless_shell.exe` bot processes running on the local Windows machine.

### Automated Comment & Messenger Verification
- [ ] All unit tests in `test_bot_logic.py` and `test_auth_and_dashboard.py` pass (`0` failures), plus new regression tests covering pointer-intercept resilience, `needs_inbox_only` comment handling, and Messenger thread detection.
- [ ] Live headless verification against Meta Business Suite (`inbox/facebook` and `inbox/messenger`) confirms zero `subtree intercepts pointer events` click timeouts, accurate detection of newest comments and unread/latest customer Messenger messages, and zero modification of post status.
- [ ] GitHub Actions workflow `vps_bot_24_7.yml` on `DucTri2207/chatbot-dan86` is verified in `in_progress` state (no `pending` queue jam) and actively pushing fresh `last_heartbeat_str` updates to `origin/master:state/bot_status.json`.

Keep your final report concise (summary of changes, short diffs, file paths, and verification results).


## 2026-10-12T11:03:39Z

This is a single self-contained fix; keep it small and focused.

Working directory: d:\chat bot dan 86
Integrity mode: development

## Problem & Context

1. **Vấn đề bao phủ bài viết (Toàn bộ bài viết, không chỉ 10-20 bài)**:
   - Cơ chế hiện tại quét danh sách thread bên trái trong Meta Business Suite Inbox (MAX_THREADS_PER_CYCLE = 10), chỉ nạp tối đa 10-11 bài gần nhất.
   - Khi khách (hoặc người kiểm thử) bình luận vào bất kỳ bài viết nào nằm ngoài Top 10, bot hoàn toàn không nhìn thấy, dẫn đến tình trạng 'lúc rep lúc không' rất chập chờn.
   - **Giải pháp dứt điểm**: Sử dụng **Trang Thông báo Fanpage (Facebook Notifications)**:
     URL: https://business.facebook.com/latest/notifications?asset_id=104011958817512.
     Bất kể bài viết đăng hôm nay hay 2 năm trước, chỉ cần có bình luận mới, Facebook ngay lập tức đẩy 1 thông báo lên đầu danh sách. Bot bấm vào thông báo là Facebook tự động điều hướng thẳng đến đúng bài viết và đúng comment đó.

2. **Vấn đề định vị nút bấm & ô trả lời lồng nhau (Không suy đoán, lấy tọa độ F12 vật lý)**:
   - Tránh suy đoán selector mơ hồ.
   - Sử dụng JavaScript getBoundingClientRect() (tương đương F12 Console) để trích xuất tọa độ pixel thực tế (x, y) của nút 'Trả lời' và nút 'Gửi tin nhắn' ngay trên comment article.
   - Dùng chuột máy tính click vật lý (page.mouse.click) vào tọa độ đó.
   - Xác định tọa độ ô nhập phản hồi lồng nhau xuất hiện ngay bên dưới comment (ràng buộc tọa độ Y: comment_y < box_y < comment_y + comment_height + 250), click vật lý vào ô này để gõ câu trả lời -> Enter.
   - Tuyệt đối cấm gõ vào ô bình luận cấp 1 ở đáy trang bài viết.
   - Gửi tin nhắn riêng (Private Inbox) cho người bình luận qua popup dialog hoặc See Chat.

3. **Chế độ Thử Nghiệm An Toàn (Whitelist)**:
   - Tiếp tục duy trì TEST_ONLY_AUTHOR_WHITELIST: ['đức trí', 'trí đức', 'duc tri', 'tri duc'] để bảo vệ khách hàng khác trong suốt quá trình thử nghiệm.

## Requirements

### R1. Module Quét Thông Báo Facebook (Facebook Notifications Scanner)
- Xây dựng luồng quét thông báo tại https://business.facebook.com/latest/notifications?asset_id=104011958817512:
  - Lọc các thông báo mới có chứa từ khóa bình luận ('đã bình luận', 'commented').
  - Trích xuất tên tác giả và thời gian tương đối ('vừa xong', '1 phút', 'vài giây').
  - Nếu tác giả nằm trong Whitelist (Đức Trí) và chưa có trong memory.replied_comments:
    - Click vào thông báo để Facebook mở chi tiết bài viết và cuộn tới đúng comment.
  - Vẫn duy trì cơ chế quét Hộp thư Inbox làm phương án dự phòng (fallback).

### R2. Động Cơ Định Vị Tọa Độ F12 Vật Lý (Coordinate-based DOM Engine)
- Thay thế hoàn toàn cơ chế phỏng đoán selector bằng trích xuất tọa độ DOM thực tế:
  - Hàm get_element_coordinates(target_element) trả về {x, y, width, height} chính xác từ getBoundingClientRect().
  - Click vật lý bằng chuột: page.mouse.click(center_x, center_y).
  - Sau khi click nút 'Trả lời', đợi ô nhập lồng nhau bung ra trong phạm vi hình học box_y < comment_bottom + 250.
  - Click chuột vật lý vào ô nhập lồng nhau -> type_human_like -> Enter.
  - Fail-safe guard: Nếu không tìm thấy ô lồng nhau trong phạm vi tọa độ sát comment, HỦY BỎ thao tác comment để chống văng ra ngoài bài viết.
  - Định vị tọa độ nút 'Gửi tin nhắn' / 'Nhắn tin' của chính comment đó để gửi inbox riêng.

### R3. Bộ Kiểm Thử & Xác Minh Độc Lập
- Cập nhật và bổ sung unit test kiểm chứng:
  - Logic phân tích danh sách thông báo Facebook Notifications.
  - Logic kiểm tra tọa độ bounding box lọc ô nhập lồng nhau vs ô bài viết đáy trang.
  - Đảm bảo 100% bộ test hiện tại (72 tests) và test mới đều PASS.

### R4. Triển Khai & Kiểm Chứng Thực Tế Trên VPS 24/7
- Đẩy mã nguồn lên nhánh master GitHub.
- Khởi động ca VPS mới trên GitHub Actions.
- Theo dõi log live xác nhận bot quét qua Thông báo và phản hồi thành công.

## Acceptance Criteria

### Tính Đúng Đắn & Bao Phủ
- [ ] Bot phát hiện bình luận mới trên TOÀN BỘ bài viết thông qua Trang Thông báo (không bị giới hạn 10-20 bài).
- [ ] Bình luận phản hồi công khai BẮT BUỘC lồng chuẩn xác bên dưới comment của khách (Nested Reply), 0% khả năng văng ra ngoài bài viết.
- [ ] Gửi tin nhắn riêng vào Messenger của người bình luận thành công đúng 1 lần.
- [ ] Sử dụng tọa độ chuột vật lý (F12 Coordinates) để tương tác, không đoán mò selector.
- [ ] 100% Unit Tests PASS không có lỗi hồi quy.
- [ ] Khách hàng khác ngoài Đức Trí được bảo vệ 100% bởi TEST_ONLY_AUTHOR_WHITELIST.
- [ ] VPS GitHub Actions chạy ổn định và đồng bộ memory an toàn.


## Follow-up — 2026-10-12T13:37:23Z

This is a single self-contained fix; keep it small and focused.

Working directory: d:\chat bot dan 86
Integrity mode: development

## Problem & Context

1. **Mở khóa toàn bộ tài khoản (Production Live)**:
   - Giai đoạn thử nghiệm giới hạn Whitelist (chỉ rep Đức Trí) đã hoàn thành xuất sắc.
   - Giờ cần mở khóa cho TOÀN BỘ khách hàng: Bất kỳ ai bình luận trên bài viết hoặc nhắn tin vào Messenger đều được Bot tiếp nhận và phản hồi tự động.

2. **Chuẩn hóa nội dung phản hồi (Bỏ SĐT, chỉ để Website)**:
   - Khách hàng yêu cầu: Bỏ hoàn toàn số điện thoại / Hotline / Zalo (0933 133 516) khỏi tất cả các mẫu câu trả lời.
   - Chỉ giữ và điều hướng khách hàng truy cập website chính thức: `https://dan86.vn`.
   - Áp dụng trên cả 4 nhóm mẫu tin trong `bot/bot_config.py`:
     + `COMMENT_REPLIES` (Bình luận công khai lồng bên dưới)
     + `PRIVATE_REPLIES_FROM_COMMENT` (Tin nhắn riêng tự động khi khách bình luận)
     + `FIRST_INBOX_REPLIES` (Chào lần đầu khi khách nhắn tin vào Messenger)
     + `WAIT_STAFF_REPLIES` (Nhắc chờ nhân viên khi khách nhắn lại sau 3 tiếng)

3. **Đảm bảo cơ chế ngẫu nhiên (Randomization & Anti-Repeat)**:
   - Đảm bảo hàm `pick_template` xoay vòng ngẫu nhiên trong danh sách các mẫu câu, không trùng lặp 2 câu giống nhau liên tiếp của cùng một nhóm.

## Requirements

### R1. Mở Khóa Tương Tác Cho Tất Cả Khách Hàng
- Trong `bot/bot_config.py`: Đặt `TEST_ONLY_AUTHOR_WHITELIST: List[str] = []` (danh sách rỗng).
- Rà soát các luồng trong `bot/page_bot_engine.py`:
  - `process_post_comments_by_coordinates`: Xử lý bình luận của mọi khách hàng.
  - `process_facebook_notifications_tab`: Tiếp nhận thông báo bình luận của mọi khách hàng.
  - `process_facebook_comments_tab`: Quét thread bình luận của mọi khách hàng.
  - `process_messenger_inbox_tab`: Tiếp nhận và phản hồi tin nhắn Messenger của mọi khách hàng.
- Duy trì cooldown chống spam an toàn cho khách hàng (`CUSTOMER_ANTI_SPAM_COOLDOWN_SECONDS = 60.0`).

### R2. Sửa Nội Dung Toàn Bộ Mẫu Tin Nhắn
- Loại bỏ 100% số điện thoại `0933 133 516`, từ khóa `Hotline`, `Zalo`, `SĐT` trong tất cả các mẫu câu thuộc `bot/bot_config.py`.
- Tích hợp và làm nổi bật link website `https://dan86.vn` một cách tự nhiên, lịch sự và chuyên nghiệp.

### R3. Xác Minh Cơ Chế Chọn Mẫu Ngẫu Nhiên (Randomization)
- Kiểm tra hàm `pick_template` với tham số `category_key` hoạt động chuẩn xác, chọn ngẫu nhiên các câu trả lời khác nhau qua các lượt.

### R4. Cập Nhật Test Suite & Kiểm Chứng Hồi Quy
- Cập nhật các test assertion trong `test_bot_logic.py` và `test_hardening_regression.py` để kiểm tra `https://dan86.vn` thay vì SĐT.
- Chạy toàn bộ 100% unit tests: `python -m unittest discover -s . -p "test_*.py" -v` đạt PASS 100%.

### R5. Đẩy Mã Nguồn Lên GitHub & Khởi Động Ca VPS 24/7 Mới
- Commit và push mã nguồn sạch lên nhánh `master`.
- Kích hoạt ca workflow mới trên GitHub Actions và kiểm tra trạng thái hoạt động.

## Acceptance Criteria

### Tính Chuẩn Xác & Vận Hành
- [ ] `TEST_ONLY_AUTHOR_WHITELIST` được đặt là rỗng `[]`, mọi tài khoản comment hoặc inbox đều được bot phản hồi.
- [ ] Không còn bất kỳ số điện thoại / Hotline / Zalo nào trong các template phản hồi; 100% hướng về `https://dan86.vn`.
- [ ] Cơ chế `pick_template` chọn ngẫu nhiên mượt mà và không trùng lặp câu liền kề.
- [ ] 100% Unit Tests PASS (không có bất kỳ fail hay error nào).
- [ ] Code được commit & push lên `master`, ca VPS mới chạy ổn định trên GitHub Actions.

## 2026-10-12T16:54:38Z

This is a single self-contained fix; keep it small and focused.

Working directory: d:\chat bot dan 86
Integrity mode: development

## Problem & Context

1. **Lỗi trả lời đè (Double-Reply / Mù trước bình luận cũ của Page)**:
   - Trong `bot/page_bot_engine.py` (hàm `inspect_comment_panel` dòng 1140-1148), có logic `isGenericSystemReply` ép `isPageReply = false` nếu bình luận có chữ "đã gửi tin nhắn cho bạn" hoặc "đã gửi tin nhắn". Điều này khiến bot cố tình phớt lờ câu trả lời của Page và trả lời đè lần 2.
   - Danh sách `PAGE_NAMES` trong `bot/bot_config.py` thiếu tên đầy đủ hiển thị thực tế của Page: "Quà tặng thuần Việt DAN86", "DAN86 - Quà tặng thuần Việt", dẫn đến việc so khớp tên bị trượt.
   - DOM thiếu nhận diện huy hiệu "Tác giả" / "Author" của Facebook.

2. **Lỗi kẹt vòng lặp thử lại (Retry Loop Bottleneck)**:
   - Trong `bot/memory_store.py` (`should_reply_comment` dòng 380-384 và 393-397):
     `if (p_reply.startswith("(Bỏ qua") or p_reply.startswith("(Đã phản hồi")) and not has_page_reply_in_dom: pass`
     Khi một comment bị bỏ qua cmt công khai (vì không tìm thấy ô lồng nhau), nó lại thực hiện `pass` và trả về `True`, khiến bot cố thử lại 5-6 lần liên tiếp trong cùng một chu kỳ, ngốn mất 10-14 phút và chặn đứng tất cả comment của khách hàng khác.

## Requirements

### R1. Khắc phục triệt để cơ chế nhận diện phản hồi của Fanpage (Chống trả lời đè)
- Trong `bot/page_bot_engine.py` (`inspect_comment_panel`):
  - XÓA BỎ 100% đoạn ép buộc `isGenericSystemReply` (bất kể câu trả lời trước đó của Page có chứa từ khóa gì, chỉ cần là Page hoặc tác giả thì BẮT BUỘC tính là `isPageReply = true`).
  - Nhận diện huy hiệu "Tác giả" / "Author" trên comment article: Nếu article có chứa `tác giả`, `author`, `badge`, hoặc biểu tượng tác giả của bài viết -> `isPageReply = true`.
- Trong `bot/bot_config.py`:
  - Bổ sung vào `PAGE_NAMES`: `"quà tặng thuần việt dan86"`, `"quà tặng thuần việt"`, `"dan86 - quà tặng thuần việt"`, `"dan86 quà tặng thuần việt"`, `"bá lộc green"`.

### R2. Khóa vĩnh viễn vòng lặp Retry lặp lại (Chống kẹt hàng đợi)
- Trong `bot/memory_store.py` (`should_reply_comment`):
  - Xóa bỏ nhánh `pass` cho `(Bỏ qua...` và `(Đã phản hồi...`.
  - Một khi bình luận đã có bản ghi trong `replied_comments` (dù là đã phản hồi công khai hay đã bỏ qua cmt công khai), BẮT BUỘC trả về `False, key` ngay lập tức.
  - Đảm bảo mỗi comment chỉ được xử lý đúng 1 lượt duy nhất trong toàn bộ vòng đời của bot.

### R3. Kiểm chứng bộ Unit Test
- Cập nhật test nếu có assertion phụ thuộc.
- Chạy toàn bộ test suite `python -m unittest discover -s . -p "test_*.py" -v` đảm bảo 100% tests PASS, không có bất kỳ regression nào.

### R4. Triển khai & Kích hoạt Ca VPS 24/7 Mới
- Đẩy toàn bộ mã nguồn lên nhánh `master`.
- Hủy ca VPS cũ (nếu đang chạy) và kích hoạt ca VPS mới qua `gh workflow run vps_bot_24_7.yml`.
- Xác nhận ca mới đã khởi động thành công và sẵn sàng chạy 24/7.

## Acceptance Criteria

### Tính Chuẩn Xác & Vận Hành
- [ ] Xóa bỏ hoàn toàn `isGenericSystemReply`, không bao giờ ép `isPageReply = false` khi Page đã phản hồi.
- [ ] Bổ sung đầy đủ nhận diện tên Fanpage và huy hiệu "Tác giả" của Facebook.
- [ ] Khóa triệt để cơ chế retry lặp lại trong `memory_store.py`: Mỗi comment chỉ xử lý đúng 1 lần.
- [ ] 100% Unit Tests PASS không có lỗi hồi quy.
- [ ] Code được commit & push lên `master`.
- [ ] Khởi chạy ca VPS mới trên GitHub Actions và kiểm tra trạng thái in_progress.
