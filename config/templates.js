/**
 * Cấu hình mẫu câu trả lời mặc định xoay vòng cho Fanpage DAN86 (Dần86Farm)
 * Tự động chọn ngẫu nhiên mẫu câu để tránh bị Facebook quét spam
 */

module.exports = {
  // 1. Mẫu câu TRẢ LỜI BÌNH LUẬN CÔNG KHAI (Public Comment Replies)
  commentReplies: [
    (name) => `Dạ chào ${name || 'bạn'}, DAN86 đã gửi thông tin chi tiết và bảng giá set quà vào tin nhắn cho mình rồi ạ. Bạn kiểm tra hộp thư/tin nhắn chờ giúp shop nhé! ❤️`,
    (name) => `Dạ shop chào ${name || 'mình'} ạ! DAN86 vừa nhắn tin tư vấn chi tiết set quà qua Messenger cho bạn rồi nhé. Bạn check inbox giúp shop nha! ✨`,
    (name) => `Dạ cảm ơn ${name || 'bạn'} đã quan tâm đến Quà tặng thuần Việt DAN86! Shop đã chủ động inbox tư vấn cho mình rồi ạ, bạn vào xem nhé! 🎁`,
    (name) => `Dạ chào ${name || 'bạn'}! DAN86 đã gửi hình ảnh thực tế và báo giá quà tặng vào tin nhắn cho mình rồi ạ. Bạn có thể xem trọn bộ set quà tại website: https://dan86.vn nhé! 🌾`,
    (name) => `Dạ chào bạn, DAN86 đã gửi tin nhắn riêng cho bạn rồi ạ. Bạn kiểm tra Messenger để shop tư vấn chi tiết set quà phù hợp nhất nhé! 🌿`
  ],

  // 2. Mẫu câu GỬI TIN NHẮN RIÊNG VÀO INBOX KHI KHÁCH BÌNH LUẬN (Private Reply to Comment)
  privateReplies: [
    (name) => `Chào ${name || 'bạn'}, DAN86 cảm ơn bạn đã để lại bình luận quan tâm đến sản phẩm!
🎁 Bên em chuyên các set quà tặng thuần Việt Nam tinh tế, mây tre đan thủ công, nông sản và thảo mộc thiên nhiên phù hợp làm quà tặng 20/10, quà đối tác, doanh nghiệp.
🌐 Bạn có thể xem toàn bộ các set quà tại website: https://dan86.vn
Dạ bạn đang quan tâm set quà ngân sách khoảng bao nhiêu để shop tư vấn mẫu phù hợp nhất cho mình ạ?`,

    (name) => `Dạ shop chào ${name || 'bạn'} ạ!
Cảm ơn bạn đã quan tâm đến Quà tặng thuần Việt DAN86 (CTY TNHH Bá Lộc Green).
🌾 Hiện shop đang có sẵn nhiều mẫu set quà tặng tinh tế kết hợp đặc sản và thủ công truyền thống:
- Hộp quà mây tre đan, túi cỏ bàng, khăn rằn dệt tay.
- Nông sản rang mộc, trà thảo mộc hữu cơ, mật ong rừng, tinh dầu thiên nhiên.
🌐 Chi tiết sản phẩm: https://dan86.vn
Bạn đang cần tìm quà tặng cho cá nhân hay cho đoàn/doanh nghiệp để shop hỗ trợ mình ngay nhé!`
  ],

  // 3. Mẫu câu TỰ ĐỘNG CHÀO VÀ TƯ VẤN KHI KHÁCH NHẮN TRỰC TIẾP VÀO INBOX (Messenger Inquiries)
  inboxReplies: [
    `Dạ DAN86 xin chào bạn! Cảm ơn bạn đã nhắn tin cho shop.
Hiện shop có các dòng quà tặng thuần Việt cao cấp và thân thiện môi trường:
1. Set quà tặng cá nhân (20/10, sinh nhật, tri ân).
2. Set quà lưu niệm cho du khách, đoàn khách quốc tế.
3. Quà tặng doanh nghiệp thiết kế theo yêu cầu (in logo, may đo riêng).

🌐 Mời bạn tham khảo các mẫu mới nhất tại website chính thức: https://dan86.vn
Dạ bạn đang cần tìm quà tặng cho dịp nào và số lượng bao nhiêu ạ? Shop sẽ hỗ trợ bạn ngay!`
  ]
};
