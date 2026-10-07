/**
 * test_webhook.js - Kiểm thử tự động Webhook Serverless Function cho Fanpage DAN86
 */

const assert = require('assert');
const webhookHandler = require('./api/webhook');

// Helper giả lập đối tượng Response của Vercel Serverless Function
function createMockRes() {
  return {
    statusCode: null,
    body: null,
    status(code) {
      this.statusCode = code;
      return this;
    },
    send(data) {
      this.body = data;
      return this;
    },
    json(data) {
      this.body = data;
      return this;
    }
  };
}

async function runTests() {
  console.log('====================================================');
  console.log('🚀 BẮT ĐẦU CHẠY BỘ KIỂM THỬ TỰ ĐỘNG WEBHOOK DAN86');
  console.log('====================================================\n');

  let passedTests = 0;
  let totalTests = 0;

  function recordPass(testName) {
    totalTests++;
    passedTests++;
    console.log(`✅ [PASS] ${testName}`);
  }

  function recordFail(testName, error) {
    totalTests++;
    console.error(`❌ [FAIL] ${testName}:`, error.message);
  }

  // Cấu hình biến môi trường kiểm thử mặc định
  process.env.VERIFY_TOKEN = 'dan86_secret_2026';
  process.env.PAGE_ACCESS_TOKEN = 'mock_page_access_token_for_test';
  process.env.PAGE_ID = '10987654321';

  // Mock global.fetch để kiểm tra các request gửi sang Facebook Graph API mà không cần kết nối mạng thực tế
  const interceptedCalls = [];
  const originalFetch = global.fetch;

  global.fetch = async (url, options) => {
    interceptedCalls.push({ url, options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ success: true, id: 'mock_response_id' })
    };
  };

  try {
    // -------------------------------------------------------------------------
    // TEST 1: GET Webhook Verification Handshake
    // -------------------------------------------------------------------------
    try {
      const req = {
        method: 'GET',
        query: {
          'hub.mode': 'subscribe',
          'hub.verify_token': 'dan86_secret_2026',
          'hub.challenge': 'test_challenge_123'
        }
      };
      const res = createMockRes();

      await webhookHandler(req, res);

      assert.strictEqual(res.statusCode, 200, 'Status code phải là 200');
      assert.strictEqual(res.body, 'test_challenge_123', 'Body phải trả về đúng giá trị challenge');
      recordPass('Test 1: GET verification hợp lệ (trả về challenge và status 200)');
    } catch (err) {
      recordFail('Test 1: GET verification hợp lệ', err);
    }

    // -------------------------------------------------------------------------
    // TEST 1.1 (Edge case): GET với verify_token sai -> 403 Forbidden
    // -------------------------------------------------------------------------
    try {
      const req = {
        method: 'GET',
        query: {
          'hub.mode': 'subscribe',
          'hub.verify_token': 'sai_token_roi',
          'hub.challenge': 'test_challenge_123'
        }
      };
      const res = createMockRes();

      await webhookHandler(req, res);

      assert.strictEqual(res.statusCode, 403, 'Sai verify_token phải trả về 403');
      assert.strictEqual(res.body, 'Forbidden', 'Body phải là "Forbidden"');
      recordPass('Test 1.1: GET verification với token sai -> 403 Forbidden');
    } catch (err) {
      recordFail('Test 1.1: GET verification với token sai', err);
    }

    // -------------------------------------------------------------------------
    // TEST 1.2 (Edge case): GET thiếu tham số query -> 400 Bad Request
    // -------------------------------------------------------------------------
    try {
      const req = {
        method: 'GET',
        query: {}
      };
      const res = createMockRes();

      await webhookHandler(req, res);

      assert.strictEqual(res.statusCode, 400, 'Thiếu tham số phải trả về 400');
      recordPass('Test 1.2: GET verification thiếu tham số -> 400 Bad Request');
    } catch (err) {
      recordFail('Test 1.2: GET verification thiếu tham số', err);
    }

    // -------------------------------------------------------------------------
    // TEST 1.3 (Edge case): GET khi req.query là undefined -> 400 Bad Request (không crash)
    // -------------------------------------------------------------------------
    try {
      const req = {
        method: 'GET'
      };
      const res = createMockRes();

      await webhookHandler(req, res);

      assert.strictEqual(res.statusCode, 400, 'Undefined query phải trả về 400');
      recordPass('Test 1.3: GET verification khi req.query là undefined -> 400 Bad Request');
    } catch (err) {
      recordFail('Test 1.3: GET verification khi req.query là undefined', err);
    }

    // -------------------------------------------------------------------------
    // TEST 2: POST Facebook Comment Event Payload
    // -------------------------------------------------------------------------
    try {
      interceptedCalls.length = 0; // reset lịch sử gọi API

      const mockCommentPayload = {
        object: 'page',
        entry: [
          {
            id: '10987654321',
            time: 1710000000,
            changes: [
              {
                field: 'feed',
                value: {
                  item: 'comment',
                  verb: 'add',
                  comment_id: 'comment_998877_001',
                  post_id: 'post_112233_001',
                  sender_id: 'customer_user_888',
                  from: {
                    id: 'customer_user_888',
                    name: 'Nguyễn Văn A'
                  },
                  message: 'Shop ơi set quà 20/10 giá bao nhiêu ạ?'
                }
              }
            ]
          }
        ]
      };

      const req = {
        method: 'POST',
        body: mockCommentPayload
      };
      const res = createMockRes();

      await webhookHandler(req, res);

      assert.strictEqual(res.statusCode, 200, 'Status code phải là 200');
      assert.strictEqual(res.body, 'EVENT_RECEIVED', 'Body phản hồi phải là EVENT_RECEIVED');

      // Xác minh 3 Graph API actions đã được gọi: 1 like, 1 comment reply, 1 private message
      assert.strictEqual(interceptedCalls.length, 3, 'Phải thực hiện đủ 3 tác vụ Graph API (like, reply, inbox)');
      
      const likeCall = interceptedCalls.find(c => c.url.includes('comment_998877_001/likes'));
      assert.ok(likeCall, 'Graph API like comment phải được gọi');

      const replyCall = interceptedCalls.find(c => c.url.includes('comment_998877_001/comments'));
      assert.ok(replyCall, 'Graph API rep public comment phải được gọi');

      const inboxCall = interceptedCalls.find(c => c.url.includes('me/messages'));
      assert.ok(inboxCall, 'Graph API private inbox reply phải được gọi');

      recordPass('Test 2: POST mock comment event (status 200, EVENT_RECEIVED & đủ like/rep/inbox không crash)');
    } catch (err) {
      recordFail('Test 2: POST mock comment event', err);
    }

    // -------------------------------------------------------------------------
    // TEST 2.1: POST Chống lặp vô hạn (comment từ chính Fanpage, string ID)
    // -------------------------------------------------------------------------
    try {
      interceptedCalls.length = 0;

      const pageCommentPayload = {
        object: 'page',
        entry: [
          {
            id: '10987654321',
            time: 1710000000,
            changes: [
              {
                field: 'feed',
                value: {
                  item: 'comment',
                  verb: 'add',
                  comment_id: 'comment_self_page_002',
                  post_id: 'post_112233_001',
                  sender_id: '10987654321',
                  from: {
                    id: '10987654321',
                    name: 'Dần86 Farm'
                  },
                  message: 'Cảm ơn bạn đã quan tâm!'
                }
              }
            ]
          }
        ]
      };

      const req = {
        method: 'POST',
        body: pageCommentPayload
      };
      const res = createMockRes();

      await webhookHandler(req, res);

      assert.strictEqual(res.statusCode, 200);
      assert.strictEqual(interceptedCalls.length, 0, 'Comment từ chính Page không được kích hoạt rep');
      recordPass('Test 2.1: POST comment từ chính Page (string ID) -> bỏ qua chống lặp vô hạn');
    } catch (err) {
      recordFail('Test 2.1: POST comment từ chính Page (string ID)', err);
    }

    // -------------------------------------------------------------------------
    // TEST 2.2 (Edge case): POST Chống lặp vô hạn khi sender_id là dạng số nguyên
    // -------------------------------------------------------------------------
    try {
      interceptedCalls.length = 0;

      const numericIdPayload = {
        object: 'page',
        entry: [
          {
            id: '10987654321',
            changes: [
              {
                field: 'feed',
                value: {
                  item: 'comment',
                  verb: 'add',
                  comment_id: 'comment_numeric_003',
                  from: {
                    id: 10987654321 // Numeric ID thay vì string
                  },
                  message: 'Comment phản hồi từ page dạng số'
                }
              }
            ]
          }
        ]
      };

      const req = { method: 'POST', body: numericIdPayload };
      const res = createMockRes();

      await webhookHandler(req, res);

      assert.strictEqual(res.statusCode, 200);
      assert.strictEqual(interceptedCalls.length, 0, 'Numeric PAGE_ID phải được chống lặp vô hạn');
      recordPass('Test 2.2: POST comment từ chính Page với numeric ID -> bỏ qua chống lặp vô hạn');
    } catch (err) {
      recordFail('Test 2.2: POST comment với numeric ID', err);
    }

    // -------------------------------------------------------------------------
    // TEST 2.3 (Edge case): POST comment từ khách hàng không có name -> fallback 'bạn'
    // -------------------------------------------------------------------------
    try {
      interceptedCalls.length = 0;

      const noNamePayload = {
        object: 'page',
        entry: [
          {
            changes: [
              {
                field: 'feed',
                value: {
                  item: 'comment',
                  verb: 'add',
                  comment_id: 'comment_noname_004',
                  from: { id: 'cust_no_name' }, // Không có thuộc tính name
                  message: 'Cho em xin giá'
                }
              }
            ]
          }
        ]
      };

      const req = { method: 'POST', body: noNamePayload };
      const res = createMockRes();

      await webhookHandler(req, res);

      assert.strictEqual(res.statusCode, 200);
      assert.strictEqual(interceptedCalls.length, 3, 'Vẫn phải thực hiện đủ 3 hành động Graph API');
      recordPass('Test 2.3: POST comment không có trường name -> fallback an toàn, không crash');
    } catch (err) {
      recordFail('Test 2.3: POST comment không có trường name', err);
    }

    // -------------------------------------------------------------------------
    // TEST 2.4 (Edge case): POST feed changes thiếu thuộc tính value -> không crash
    // -------------------------------------------------------------------------
    try {
      const malformedFeedPayload = {
        object: 'page',
        entry: [
          {
            changes: [
              { field: 'feed' } // Thiếu value
            ]
          }
        ]
      };

      const req = { method: 'POST', body: malformedFeedPayload };
      const res = createMockRes();

      await webhookHandler(req, res);

      assert.strictEqual(res.statusCode, 200);
      recordPass('Test 2.4: POST feed changes thiếu value -> xử lý an toàn, không crash');
    } catch (err) {
      recordFail('Test 2.4: POST feed changes thiếu value', err);
    }

    // -------------------------------------------------------------------------
    // TEST 2.5: POST Mock Messenger Direct Message
    // -------------------------------------------------------------------------
    try {
      interceptedCalls.length = 0;

      const messengerPayload = {
        object: 'page',
        entry: [
          {
            id: '10987654321',
            time: 1710000000,
            messaging: [
              {
                sender: { id: 'customer_user_888' },
                recipient: { id: '10987654321' },
                timestamp: 1710000000,
                message: {
                  mid: 'mid_001122',
                  text: 'Chào shop, tư vấn giúp em set quà tặng nhé!'
                }
              }
            ]
          }
        ]
      };

      const req = {
        method: 'POST',
        body: messengerPayload
      };
      const res = createMockRes();

      await webhookHandler(req, res);

      assert.strictEqual(res.statusCode, 200);
      assert.strictEqual(res.body, 'EVENT_RECEIVED');
      assert.strictEqual(interceptedCalls.length, 1, 'Phải gửi 1 tin nhắn trả lời tự động');
      recordPass('Test 2.5: POST Messenger direct message (status 200, phản hồi inbox thành công)');
    } catch (err) {
      recordFail('Test 2.5: POST Messenger direct message', err);
    }

    // -------------------------------------------------------------------------
    // TEST 2.6 (Edge case): POST Messenger event thiếu thuộc tính sender -> không crash
    // -------------------------------------------------------------------------
    try {
      const malformedMsgPayload = {
        object: 'page',
        entry: [
          {
            messaging: [
              {
                message: { text: 'Tin nhắn không có sender' }
              }
            ]
          }
        ]
      };

      const req = { method: 'POST', body: malformedMsgPayload };
      const res = createMockRes();

      await webhookHandler(req, res);

      assert.strictEqual(res.statusCode, 200);
      recordPass('Test 2.6: POST Messenger event thiếu sender -> bỏ qua an toàn, không crash');
    } catch (err) {
      recordFail('Test 2.6: POST Messenger event thiếu sender', err);
    }

    // -------------------------------------------------------------------------
    // TEST 2.7 (Edge case): POST Messenger tin nhắn từ chính Page -> bỏ qua chống lặp
    // -------------------------------------------------------------------------
    try {
      interceptedCalls.length = 0;

      const selfMsgPayload = {
        object: 'page',
        entry: [
          {
            messaging: [
              {
                sender: { id: '10987654321' }, // Trùng PAGE_ID
                message: { text: 'Tin nhắn do chính Page gửi' }
              }
            ]
          }
        ]
      };

      const req = { method: 'POST', body: selfMsgPayload };
      const res = createMockRes();

      await webhookHandler(req, res);

      assert.strictEqual(res.statusCode, 200);
      assert.strictEqual(interceptedCalls.length, 0, 'Tin nhắn từ chính Page không kích hoạt trả lời');
      recordPass('Test 2.7: POST Messenger từ chính Page -> bỏ qua chống lặp');
    } catch (err) {
      recordFail('Test 2.7: POST Messenger từ chính Page', err);
    }

    // -------------------------------------------------------------------------
    // TEST 2.8 (Edge case): POST không có body (req.body là undefined) -> 400 Bad Request
    // -------------------------------------------------------------------------
    try {
      const req = { method: 'POST' }; // body undefined
      const res = createMockRes();

      await webhookHandler(req, res);

      assert.strictEqual(res.statusCode, 400);
      recordPass('Test 2.8: POST req.body undefined -> 400 Bad Request không crash');
    } catch (err) {
      recordFail('Test 2.8: POST req.body undefined', err);
    }

    // -------------------------------------------------------------------------
    // TEST 2.9 (Edge case): POST object không phải là 'page' -> 404 Not Found
    // -------------------------------------------------------------------------
    try {
      const req = { method: 'POST', body: { object: 'user' } };
      const res = createMockRes();

      await webhookHandler(req, res);

      assert.strictEqual(res.statusCode, 404);
      recordPass('Test 2.9: POST với body.object !== "page" -> 404 Not Found');
    } catch (err) {
      recordFail('Test 2.9: POST với body.object !== "page"', err);
    }

    // -------------------------------------------------------------------------
    // TEST 2.10 (Edge case): POST khi chưa cấu hình PAGE_ACCESS_TOKEN -> 200 không crash
    // -------------------------------------------------------------------------
    try {
      const prevToken = process.env.PAGE_ACCESS_TOKEN;
      delete process.env.PAGE_ACCESS_TOKEN;

      const payload = {
        object: 'page',
        entry: [{ id: '123' }]
      };
      const req = { method: 'POST', body: payload };
      const res = createMockRes();

      await webhookHandler(req, res);

      assert.strictEqual(res.statusCode, 200);
      process.env.PAGE_ACCESS_TOKEN = prevToken;
      recordPass('Test 2.10: POST khi chưa cấu hình PAGE_ACCESS_TOKEN -> xử lý an toàn không crash');
    } catch (err) {
      recordFail('Test 2.10: POST thiếu PAGE_ACCESS_TOKEN', err);
    }

    // -------------------------------------------------------------------------
    // TEST 3: Phương thức không hỗ trợ -> 405 Method Not Allowed
    // -------------------------------------------------------------------------
    try {
      const req = { method: 'DELETE' };
      const res = createMockRes();

      await webhookHandler(req, res);

      assert.strictEqual(res.statusCode, 405);
      recordPass('Test 3: DELETE request -> 405 Method Not Allowed');
    } catch (err) {
      recordFail('Test 3: DELETE request', err);
    }

  } finally {
    global.fetch = originalFetch;
  }

  console.log('\n====================================================');
  console.log(`📊 TỔNG KẾT KIỂM THỬ: ${passedTests}/${totalTests} TESTS PASSED (${Math.round((passedTests / totalTests) * 100)}%)`);
  console.log('====================================================');

  if (passedTests === totalTests) {
    console.log('🎉 TẤT CẢ CÁC BÀI TEST ĐÃ PASS 100%!');
    process.exit(0);
  } else {
    console.error('💥 CÓ TEST BỊ FAILED!');
    process.exit(1);
  }
}

runTests();
