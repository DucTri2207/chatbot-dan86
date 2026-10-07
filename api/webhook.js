/**
 * Webhook Serverless Function cho Vercel - Xử lý Fanpage DAN86
 */

const templates = require('../config/templates');

// Helper chọn ngẫu nhiên một mẫu câu
function getRandomItem(arr) {
  if (!Array.isArray(arr) || arr.length === 0) return null;
  return arr[Math.floor(Math.random() * arr.length)];
}

// Helper gửi request tới Facebook Graph API
async function callGraphAPI(endpoint, method = 'POST', data = null, token) {
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint.slice(1) : endpoint;
  const url = `https://graph.facebook.com/v21.0/${cleanEndpoint}`;
  const options = {
    method,
    headers: {
      'Content-Type': 'application/json'
    }
  };

  if (data) {
    options.body = JSON.stringify(data);
  }

  // Thêm access_token vào query hoặc body
  const separator = url.includes('?') ? '&' : '?';
  const finalUrl = `${url}${separator}access_token=${encodeURIComponent(token || '')}`;

  try {
    const response = await fetch(finalUrl, options);
    const result = await response.json();
    return result;
  } catch (error) {
    console.error(`Lỗi khi gọi Graph API [${cleanEndpoint}]:`, error.message || error);
    return null;
  }
}

module.exports = async (req, res) => {
  const PAGE_ACCESS_TOKEN = process.env.PAGE_ACCESS_TOKEN;
  const VERIFY_TOKEN = process.env.VERIFY_TOKEN || 'dan86_secret_2026';
  const PAGE_ID = process.env.PAGE_ID || '';

  // 1. XÁC THỰC WEBHOOK VỚI FACEBOOK (GET Request)
  if (req.method === 'GET') {
    const query = req.query || {};
    const mode = query['hub.mode'];
    const token = query['hub.verify_token'];
    const challenge = query['hub.challenge'];

    if (mode && token) {
      if (mode === 'subscribe' && token === VERIFY_TOKEN) {
        console.log('✅ WEBHOOK_VERIFIED THÀNH CÔNG');
        return res.status(200).send(challenge);
      } else {
        console.warn('❌ Xác thực thất bại: Sai VERIFY_TOKEN');
        return res.status(403).send('Forbidden');
      }
    }
    return res.status(400).send('Thiếu tham số xác thực');
  }

  // 2. NHẬN VÀ XỬ LÝ SỰ KIỆN TỪ FACEBOOK (POST Request)
  if (req.method === 'POST') {
    const body = req.body;
    if (!body || typeof body !== 'object') {
      return res.status(400).send('Bad Request: Missing or invalid request body');
    }

    if (body.object === 'page') {
      // Phản hồi 200 OK ngay lập tức cho Facebook để không bị timeout
      res.status(200).send('EVENT_RECEIVED');

      if (!PAGE_ACCESS_TOKEN) {
        console.error('⚠️ Chưa cấu hình PAGE_ACCESS_TOKEN trong biến môi trường!');
        return;
      }

      // Duyệt qua từng sự kiện trong payload
      for (const entry of (Array.isArray(body.entry) ? body.entry : [])) {
        if (!entry) continue;

        // --- A. XỬ LÝ SỰ KIỆN BÌNH LUẬN (FEED CHANGES) ---
        if (Array.isArray(entry.changes)) {
          for (const change of entry.changes) {
            if (change && change.field === 'feed') {
              const val = change.value;
              
              // Chỉ xử lý khi có bình luận mới được thêm vào (item === 'comment' & verb === 'add')
              if (val && val.item === 'comment' && val.verb === 'add') {
                const commentId = val.comment_id;
                if (!commentId) continue;

                const senderId = val.from ? val.from.id : null;
                const senderName = (val.from && val.from.name) ? val.from.name : 'bạn';
                const messageText = val.message || '';

                console.log(`[COMMENT MỚI] Từ: ${senderName} (${senderId}) - Nội dung: "${messageText}"`);

                // CHỐNG LẶP VÔ HẠN: Nếu bình luận do chính Fanpage đăng thì bỏ qua!
                if (PAGE_ID && senderId && String(senderId) === String(PAGE_ID)) {
                  console.log('Bình luận của chính Fanpage, bỏ qua không rep.');
                  continue;
                }

                try {
                  // 1. Tự động THẢ LIKE cho bình luận của khách
                  await callGraphAPI(`${commentId}/likes`, 'POST', null, PAGE_ACCESS_TOKEN);

                  // 2. Tự động TRẢ LỜI BÌNH LUẬN CÔNG KHAI
                  const commentReplyFunc = getRandomItem(templates.commentReplies);
                  const commentReplyText = typeof commentReplyFunc === 'function' 
                    ? commentReplyFunc(senderName) 
                    : commentReplyFunc;

                  if (commentReplyText) {
                    await callGraphAPI(
                      `${commentId}/comments`,
                      'POST',
                      { message: commentReplyText },
                      PAGE_ACCESS_TOKEN
                    );
                    console.log(`✅ Đã rep cmt cho ${senderName}`);
                  }

                  // 3. Tự động GỬI TIN NHẮN RIÊNG VÀO INBOX CỦA KHÁCH (Private Reply)
                  const privateReplyFunc = getRandomItem(templates.privateReplies);
                  const privateReplyText = typeof privateReplyFunc === 'function' 
                    ? privateReplyFunc(senderName) 
                    : privateReplyFunc;

                  if (privateReplyText) {
                    const privateMsgResult = await callGraphAPI(
                      'me/messages',
                      'POST',
                      {
                        recipient: { comment_id: commentId },
                        message: { text: privateReplyText }
                      },
                      PAGE_ACCESS_TOKEN
                    );
                    console.log(`✅ Đã gửi inbox riêng cho ${senderName}:`, privateMsgResult);
                  }

                } catch (err) {
                  console.error('Lỗi khi xử lý bình luận:', err);
                }
              }
            }
          }
        }

        // --- B. XỬ LÝ SỰ KIỆN KHÁCH NHẮN TIN VÀO MESSENGER ---
        if (Array.isArray(entry.messaging)) {
          for (const event of entry.messaging) {
            if (event && event.message && !event.message.is_echo) {
              const senderId = event.sender ? event.sender.id : null;
              if (!senderId) continue;

              // Chống lặp vô hạn tin nhắn từ chính Fanpage
              if (PAGE_ID && String(senderId) === String(PAGE_ID)) {
                console.log('Tin nhắn từ chính Fanpage, bỏ qua.');
                continue;
              }

              const textReceived = event.message.text || '';
              console.log(`[MESSENGER INBOX] Từ: ${senderId} - Nội dung: "${textReceived}"`);

              try {
                const inboxReplyTemplate = getRandomItem(templates.inboxReplies);
                const inboxReplyText = typeof inboxReplyTemplate === 'function' 
                  ? inboxReplyTemplate() 
                  : inboxReplyTemplate;

                if (inboxReplyText) {
                  await callGraphAPI(
                    'me/messages',
                    'POST',
                    {
                      recipient: { id: senderId },
                      message: { text: inboxReplyText }
                    },
                    PAGE_ACCESS_TOKEN
                  );
                  console.log(`✅ Đã tự động trả lời inbox cho ${senderId}`);
                }
              } catch (err) {
                console.error('Lỗi khi trả lời inbox:', err);
              }
            }
          }
        }

      }
      return;
    }

    return res.status(404).send('Not Found');
  }

  return res.status(405).send('Method Not Allowed');
};
