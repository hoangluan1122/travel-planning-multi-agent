# Hợp đồng và phạm vi từng agent

Cập nhật 21/10/2026. Phần này hoàn thiện agent độc lập; không thay đổi thành A2A
hoặc khẳng định đã có orchestration sản phẩm hoàn chỉnh.

## Hợp đồng chạy chung

`BaseAgent.run(input, context, timeout)` kiểm tra lại cả đối tượng Pydantic đã được
khởi tạo, tạo dữ liệu riêng cho mỗi lần gọi và kiểm tra đầu ra trước khi trả về.
Việc sửa danh sách/địa điểm trong agent không làm thay đổi dữ liệu của caller.
Timeout phải hữu hạn và dương. Hủy request truyền xuống coroutine; không bị biến
thành kết quả thành công. Log chỉ có tên agent, request ID, trạng thái và thời gian,
không ghi yêu cầu riêng tư hoặc thông báo lỗi chứa thông tin nhà cung cấp.

Các lớp giữ hợp đồng `input_schema`, `output_schema`, `execute`; Registry từ chối
tên trùng. Chỉ các lớp dùng LLM mới cần model factory. Không buộc Weather/Budget/
Memory phụ thuộc LLM khi thao tác của chúng phải có kết quả xác định.

## Place

- LLM: model factory ADK, tạo riêng mỗi invocation.
- Tools: search_places, get_place_details, submit_places.
- Destination/category do caller khóa; model chỉ tinh chỉnh keyword.
- Giới hạn: 3 search, 3 detail, 3 submit, mặc định 10 model calls.
- ID chi tiết phải có trong kết quả tìm kiếm. Output lấy từ dữ liệu provider,
  không lấy tên/giá/địa chỉ do model tự viết.
- Kiểm tra lại schema dữ liệu provider, kể cả object đã bị sửa sau khởi tạo.
- Phân biệt no_results, provider_error và partial; dữ liệu hỏng không được coi
  là bằng chứng có địa điểm. Nếu detail hỏng, giữ search record và ghi cảnh báo.
- Chưa có provider tìm địa điểm miễn phí thay Maps; không có ảnh hay trạng thái phòng.

## Weather

- Input: tọa độ, IANA timezone, start_date/end_date (1–14 ngày).
- Tool: HTTP GET Open-Meteo; chỉ gọi khi có ngày trong horizon 16 ngày.
- Retry tối đa 3 lần với backoff 0,2/0,4 giây cho timeout/lỗi kết nối/502/503/504.
  Không retry 429, lỗi 4xx hoặc payload JSON hỏng; outer timeout vẫn giới hạn tổng.
- Kiểm tra mảng daily, độ dài, ngày trùng, kiểu số (không nhận bool thành số),
  xác suất mưa 0–100. Null là thiếu dữ liệu, không phải trời tốt.
- Output có nguồn, fetched_at, provider_attempts, missing_dates và cờ outdoor_risk.
  not_flagged không phải cam kết an toàn; không tự tạo dữ liệu ngoài horizon.

## Budget

- Input: budget_vnd và các CostLine có ID, nhóm, đơn giá, số lượng, nguồn, certainty.
- Decimal dùng xuyên suốt. quantity phải là integer thật, không nhận true như 1.
- ID được trim trước khi kiểm tra trùng. Giá unknown phải là null; giá 0 có thể
  hợp lệ khi có certainty quoted/estimated và nguồn.
- Output: line_totals, category_subtotals, quoted_subtotal_vnd,
  estimated_subtotal_vnd, unknown_line_ids, missing_categories, subtotal và phần
  ngân sách còn lại so với khoản đã biết. Các tổng này cân đối với nhau.
- over_budget ưu tiên khi phần đã biết vượt ngân sách. incomplete khi thiếu khoản;
  within_estimate chỉ nói về các khoản được cung cấp, không bảo đảm mọi chi phí đã đủ.
- Không có tool tra giá, đổi ngoại tệ hoặc thanh toán.

## Memory

- Input: read/save/forget, preferences, confirmed, expected_version, ttl_days.
- confirmed phải đúng kiểu boolean; chuỗi "yes"/"true" và số 1 bị từ chối.
- Chỉ save nhận preferences; chuỗi rỗng bị loại, khoảng trắng được trim và bỏ trùng.
- Identity do host xác thực/cấu hình, không do LLM hoặc request body cung cấp.
- SQLite transaction và version chống ghi đè: hai thao tác ghi cùng version chỉ
  một thành công. Sau conflict phải read lại; không tự retry ghi.
- TTL làm dữ liệu hết hạn trở thành empty nhưng giữ version chống ghi cũ.
- Hủy coroutine không đảm bảo dừng thread SQLite đã bắt đầu: đọc lại sau timeout.
- Đây là kho sở thích local, chưa có semantic memory, PostgreSQL hay lịch sử chat.

## Recommendation

- LLM + tools inspect_candidates/submit_ranking; mặc định 6 model calls, 3 submit.
- Input tối đa 30 ứng viên, 20 sở thích, limit 1–20, required_place_ids,
  excluded_place_ids. ID ràng buộc phải thuộc ứng viên và không xung đột.
- Submit thiếu điểm bắt buộc, có điểm bị loại, trùng ID hoặc ID không tồn tại bị
  từ chối và cho phép sửa trong số lần giới hạn. Chỉ trả record gốc đã cung cấp.
- Kết quả là thứ tự do LLM đề xuất, không phải điểm đánh giá khách du lịch hay
  chứng minh địa điểm đáp ứng mọi nhu cầu. Chưa có benchmark chất lượng semantic.

## Planner

- LLM + tools inspect_trip/submit_itinerary; 8 model calls, 3 submit, 3 inspect.
- Input gồm trip, places, weather, constraints; dữ liệu thời tiết không được có
  ngày trùng hoặc ngoài chuyến đi. Không tự tra cứu địa điểm hay thời tiết.
- constraints hỗ trợ giờ bắt đầu/kết thúc ngày, thời lượng hoạt động tối thiểu,
  số hoạt động tối đa/ngày, ID bắt buộc/bị loại và visit_windows có source.
- Validator từ chối thiếu/sai thứ tự ngày, chồng giờ, ID lạ, lặp địa điểm trong
  một ngày tham quan, vi phạm ràng buộc. LLM có thể sửa submission bị từ chối.
- Ràng buộc giờ là dữ liệu caller cung cấp, không chứng minh giờ mở cửa thực tế.
- RoutedPlanner tiếp tục giữ các ràng buộc chung khi tối ưu: lấy phần giao với
  khung giờ theo ngày, không bỏ các giới hạn mà Planner đã nhận.
- Chưa tự dịch notes/nguyện vọng tự do thành ràng buộc cứng. Caller nên gửi
  constraints khi có yêu cầu bắt buộc. Không đảm bảo ngân sách chỉ bằng prompt.

Ví dụ thêm vào PlannerInput:

```json
{
  "constraints": {
    "day_start_minute": 540,
    "day_end_minute": 1080,
    "min_activity_minutes": 45,
    "max_activities_per_day": 4,
    "required_place_ids": ["ID_CO_TRONG_PLACES"],
    "excluded_place_ids": [],
    "visit_windows": {
      "ID_CO_TRONG_PLACES": {
        "opens_minute": 600,
        "closes_minute": 1020,
        "source": "Nguon gio tham quan do caller cung cap"
      }
    }
  }
}
```

## Kiểm chứng

Chạy `uv run --no-sync pytest -q` và `uv run --no-sync ruff check app tests`.
Test mới nằm trong test_agent_contracts.py, test_specialist_llm.py,
test_place_agent.py và test_routed_planner.py. Bao gồm lỗi schema/provider,
retry, hủy request, giới hạn LLM, sửa submission, cô lập state, xung đột ghi,
cân đối Decimal và ràng buộc Planner qua cả bước routing.

Test ADK chạy Runner/tool thật với scripted model; không chứng minh chất lượng
Gemini thực tế. Test provider dùng HTTP mock; không đánh đồng với độ chính xác
dữ liệu du lịch. Xem SPECIALIST_API.md để thử từng API với dữ liệu riêng.
