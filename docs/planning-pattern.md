# Planning pattern (Bài 07) trong TravelMate

Bật bằng `TRAVELMATE_ORCHESTRATOR=planning`. Mã: `travelmate/app/planning.py`, schema trong
`travelmate/app/models.py` (`TravelPlan`, `TravelSubTask`, `PlanningTrace`).

## Ba bước của pattern

1. **Task decomposition + structured output.** Planning Agent (LLM, chạy được ADK hoặc MAF)
   đọc yêu cầu, kể cả ghi chú tự do, và nộp một `TravelPlan` dạng JSON: danh sách việc con,
   mỗi việc giao cho một agent (`places`, `place_search`, `weather`, `recommendation`,
   `itinerary`, `budget`), có mục tiêu và phụ thuộc. Planning Agent tự quyết các lượt
   `place_search` theo nhu cầu được nêu (ví dụ quán ăn “chay”, điểm tham quan “lăng”).
2. **Submit gate.** Kế hoạch chỉ được nhận khi: id không trùng, chỉ dùng agent cho phép, có đủ
   năm bước lõi, phụ thuộc tồn tại và không vòng, các phụ thuộc bắt buộc được khai rõ, tối đa
   4 lượt tìm theo nhu cầu. Bị từ chối thì LLM nhận lỗi và sửa (tối đa 3 lần nộp).
3. **Iterative re-planning.** Executor chạy các việc con theo phụ thuộc, dùng lại agent sẵn có.
   Lượt tìm nào không ra kết quả hoặc lỗi được đưa lại cho Planning Agent kèm kết quả thật để
   sửa kế hoạch (tối đa 2 vòng). Lượt tìm được nhận diện theo nội dung (loại + từ khoá), nên
   bản sửa giữ id cũ nhưng đổi từ khoá vẫn được chạy.

## An toàn và minh bạch

- Planning Agent lỗi, hết ngân sách hay treo quá `TRAVELMATE_AGENT_TIMEOUT` → dùng kế hoạch
  mặc định (chỉ các bước lõi); chuyến đi vẫn được lập.
- Lỗi tạm thời của Gemini (5xx, 429, timeout mạng) được thử lại tối đa 2 lần (chờ 2 s, 5 s);
  lỗi nghiệp vụ như vượt ngân sách thì dừng ngay.
- Response có `planning`: mọi vòng, mọi việc con và kết quả từng lượt tìm. Giao diện hiện mục
  “Agent đã lên kế hoạch thế nào”, kể cả vòng sửa không thêm gì mới.

## Kết quả chạy thật (Huế 2 ngày, ghi chú “Muốn ăn chay và xem lăng tẩm”, MAF)

- Vòng 1: Planning Agent thêm hai lượt tìm: quán ăn “chay” → không thấy; điểm tham quan
  “lăng” → 1 nơi.
- Vòng 2: đổi sang “vegetarian” → 6 quán.
- Lịch: ngày 1 có bánh mì chay, Lăng Tự Đức, Lăng Đồng Khánh, đồ ăn nhanh chay, Lăng Khải Định,
  nhà hàng chay; ngày 2 có quán chay.

## Giới hạn

- LLM đoán từ khoá có thể sai (một lần đổi “chay” thành “thiện” và ra nhà hàng thường).
- Việc xếp lịch có tôn trọng mong muốn trong ghi chú hay không vẫn tuỳ LLM từng lượt; muốn
  chắc chắn cần bước tự kiểm tra kết quả, là việc của pattern Metacognition (Bài 09).
- Các bước lõi luôn chạy giống nhau; Planning Agent chỉ thay đổi được các lượt tìm theo nhu cầu.
