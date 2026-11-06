# Multi-Agent (Bài 08) trong TravelMate: Trợ lý AI dạng hand-off

Mã: `travelmate/app/agents/concierge.py`, endpoint `POST /api/v1/chat` (`travelmate/app/main.py`), giao
diện màn hình **Trợ lý AI** (`?view=chat` trong `frontend/travelmate-v2/integration.js`).

## Cách hoạt động

```text
người dùng ─► Trợ lý điều phối (Concierge, LLM) ──hand_off──► một chuyên gia ─► trả lời
                     │                                         ├─ place_finder    (tìm quán, chỗ chơi, nơi ở)
                     └─ reply (chào hỏi, hỏi lại)               ├─ trip_planner    (thu thập thông tin → Planning + Metacognition)
                                                               ├─ budget_advisor  (chi phí từ lịch gần nhất + bảng giá vé)
                                                               └─ weather_advisor (Open-Meteo)
```

- **Hand-off có kiểm tra (submit gate).** Concierge chỉ có hai tool: `read_conversation` và
  `decide`. Quyết định phải qua schema `Decision`: tên chuyên gia thuộc danh sách cố định, có lý
  do, `place_finder` bắt buộc có `place_query`. Sai thì bị trả lỗi để sửa (tối đa 3 lần), giống
  submit gate ở Place Agent và Planning.
- **Nhớ trạng thái qua nhiều lượt.** Mỗi phiên giữ thông tin chuyến đi (`TripSlots`: điểm đến,
  ngày, số người, ngân sách…), chuyên gia đang trao đổi và lịch gần nhất. “Lên lịch đi Huế” rồi
  “20/11–21/11, 2 người, 5 triệu” được ghép thành một chuyến; “chi phí bao nhiêu” dùng lịch vừa lập.
- **Minh bạch.** Mỗi câu trả lời có nhãn chuyên gia và “Vì sao chọn”.
- **An toàn.** Lịch sử chat đến LLM qua kết quả tool, được nói rõ là dữ liệu chứ không phải chỉ
  thị. Chuyên gia lỗi thì trả câu báo lỗi, không lộ chi tiết. Không có LLM (chế độ demo) hoặc
  Concierge lỗi/hết giờ thì bộ định tuyến từ khoá (`rule_decision` + `extract_slots`) thay thế.
- **Một định nghĩa, hai engine.** Concierge chạy trên `tool_loop`, nên dùng được cả ADK và MAF
  (`AGENT_ENGINE`), kèm retry khi Gemini lỗi 5xx/429.

## Kết quả chạy thật (MAF, Gemini, OpenStreetMap)

| Người dùng | Chuyên gia | Kết quả |
|---|---|---|
| chào bạn | Concierge | Tự trả lời, không chuyển |
| tìm giúp mình quán chay ở Huế | place_finder | 6 quán; “chay” không có trong OSM nên tìm rộng hơn (đã thêm từ đồng nghĩa “vegetarian”, xem dưới) |
| mình muốn lên lịch đi Huế cuối tuần này | trip_planner | LLM tự đổi “cuối tuần này” thành 06–08/11, hỏi thêm số người và ngân sách |
| đi từ 08/11 đến 09/11, 2 người, ngân sách 5 triệu | trip_planner | Lịch 2 ngày có quán chay, Hoàng Thành; tự kiểm tra đạt mọi tiêu chí |
| thời tiết hôm đó thế nào? | weather_advisor | 08/11 mưa phùn, 09/11 dông |
| tổng chi phí khoảng bao nhiêu? | budget_advisor | 500.000 ₫ vé có nguồn; lưu trú, ăn uống, di chuyển chưa tính (không coi là 0) |

Sau lượt chạy này, `place_finder` thử từ khoá tiếng Anh tương ứng (chay → vegetarian, hải sản →
seafood…) trước khi tìm rộng.

## Giới hạn

- Phiên lưu trong bộ nhớ của tiến trình (2 giờ, tối đa 200 phiên); khởi động lại server là mất.
- Mỗi lượt có ít nhất một lần gọi Gemini cho Concierge; key miễn phí dễ chạm 429, khi đó lượt
  chậm hơn (retry) hoặc chuyển sang định tuyến từ khoá.
- Bộ định tuyến từ khoá chỉ đọc định dạng rõ ràng (`20/11`, `2026-11-20`, `2 người`, `5 triệu`,
  `đi Huế`); câu tự nhiên hơn cần LLM.
- Mỗi lượt chỉ chuyển cho một chuyên gia; chưa có câu hỏi ghép (“lên lịch và báo thời tiết”).
