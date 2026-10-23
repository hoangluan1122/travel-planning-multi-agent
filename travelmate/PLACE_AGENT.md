# Place Agent độc lập

> **Giao diện hiện tại (23/10/2026):** dùng `.\start-live-place.ps1` và
> [LIVE_PLACE_AGENT.md](LIVE_PLACE_AGENT.md), hỗ trợ nhiều địa điểm/ba nhóm qua Photon.
> Tài liệu dưới đây dành cho API/provider thế hệ trước. Không chạy đồng thời hai
> ứng dụng cùng cổng 8001.

**Cập nhật 22/10/2026:** đã thêm provider OSM, mặc định `PLACE_PROVIDER=osm`,
không cần Maps key. Xem [OSM_PLACE_PROVIDER.md](OSM_PLACE_PROVIDER.md) để cấu hình,
chọn địa danh và đọc giới hạn kiểm chứng. Các mô tả Google bên dưới là provider
ban đầu, vẫn dùng được với `PLACE_PROVIDER=google`.

## Phạm vi

Đây là một agent ADK có LLM và ba function tools, chạy riêng, không gọi Planner,
Memory, Weather, Budget hoặc orchestration. Lớp PlaceAgent cũ trong agents.py vẫn
là adapter cho luồng preview cũ; bản mới là PlaceAssistant trong place_agent.py.
Chưa thay thế luồng cũ để tránh trộn bước xây một agent với bước tích hợp multi-agent.

## Chạy

Trong thư mục travelmate:

```powershell
uv sync --extra dev --extra ai
uv run --no-sync uvicorn app.place_api:create_app --factory --host 127.0.0.1 --port 8001
```

Hoặc chạy `.\start-place-agent.ps1`. Script tự chuyển tới đúng thư mục dự án,
không sửa dữ liệu hay tạo khóa.

File `.env` cần GOOGLE_API_KEY, GOOGLE_MAPS_API_KEY, TRAVELMATE_API_TOKEN.
Cấu hình GEMINI_MODEL thành model tài khoản có quyền dùng. Không gửi khóa lên chat.
Ứng dụng này chỉ chạy live, không âm thầm chuyển sang demo; thiếu khóa thì từ chối
khởi động. API có thể phát sinh phí. TRAVELMATE_MODE của ứng dụng cũ không áp dụng
cho ứng dụng Place Agent độc lập.

Mở http://127.0.0.1:8001/docs, chọn Authorize và nhập API token, rồi dùng
POST /api/v1/agent/places:

```json
{
  "destination": "Da Nang, Vietnam",
  "category": "restaurant",
  "needs": "Tìm nhà hàng chay phù hợp gia đình",
  "limit": 5
}
```

Không nhập chuỗi `Bearer ` vào ô Swagger nếu ô đã khai báo HTTP Bearer.
Với HTTP client khác, dùng header `Authorization: Bearer <token>`.

## Hợp đồng và vòng xử lý

1. Pydantic kiểm tra destination, category, needs và limit (1–20).
2. LLM đọc yêu cầu, chọn từ khóa; search_places luôn giữ destination/category
   từ đầu vào đã kiểm tra. Agent có thể tìm lại tối đa ba lần.
3. Tool gọi Google Text Search. Kết quả được lưu trong bộ nhớ riêng của request.
4. get_place_details chỉ được gọi với ID từng xuất hiện từ search. Tool gọi
   Google Place Details để đọc tên/địa chỉ/tọa độ/types, không lấy giá hay tình trạng phòng.
5. LLM gọi submit_places với danh sách ID. Server kiểm tra trùng ID, số lượng,
   nguồn gốc ID và các lần tìm trước đó, rồi dựng output từ dữ liệu tool.
6. Nếu nộp sai, lỗi trở thành observation để LLM sửa. Text tự do không được chấp nhận.

Không nhận tên, giá, địa chỉ hoặc tọa độ do LLM tự viết làm dữ liệu cuối.
`fetched_at` là thời điểm truy vấn, không phải thời điểm nhà cung cấp cập nhật.

| status | Ý nghĩa |
| --- | --- |
| candidates | Có ứng viên từ nguồn; không bảo đảm mọi nhu cầu đã được kiểm chứng |
| no_results | Truy vấn thành công nhưng không có ứng viên; không có nghĩa địa điểm không tồn tại |
| partial | Có ứng viên nhưng ít nhất một truy vấn/chi tiết đã lỗi |
| provider_error | Không có ứng viên và ít nhất một truy vấn đã lỗi |

Lỗi hết thời gian toàn agent trả HTTP 504. Không tạo được output hợp lệ, lỗi LLM
hoặc hết ngân sách thực thi trả 502. Token sai trả 401; input sai trả 422.
Provider_error nằm trong output có cấu trúc, không bị biến thành no_results.

## Giới hạn và bảo vệ

- Tối đa 10 lần gọi model, 3 tìm kiếm, 3 lần lấy chi tiết, 3 lần nộp kết quả.
- Timeout toàn agent mặc định 60 giây, có thể cấu hình tới 180 giây.
- Không tự retry HTTP; LLM có thể quyết định tìm lại trong ngân sách ba lượt.
- Model, tool state, session và bản ghi được tách theo request.
- Token bắt buộc; không có thao tác đặt phòng, thanh toán, ghi database hoặc chạy lệnh.
- API key được tiêm vào client từng request, không thay đổi biến môi trường toàn tiến trình.
- Chỉ log request ID, tên tool và số lượng; không log khóa hoặc chuỗi suy nghĩ.
- Chỉ chạy localhost. Chưa có JWT người dùng, rate limit hoặc quota theo tài khoản.

Prompt injection được giảm bằng chỉ dẫn và kiểm tra output, không thể tuyên bố
loại bỏ hoàn toàn. Từ khóa tìm kiếm và việc chọn ứng viên vẫn do LLM quyết định;
không có kiểm tra địa lý bằng polygon hay chứng minh semantic mọi ràng buộc.
Chưa hỗ trợ ảnh, giá, giờ mở cửa, phòng trống, đặt chỗ hoặc lưu hội thoại lâu dài.

## Kiểm thử

```powershell
uv run --no-sync pytest tests/test_place_agent.py tests/test_places.py -q
```

ScriptedModel thay LLM trong test nhưng ADK Runner và Python tools chạy thật.
HTTP MockTransport thay Google Places để kiểm chứng request và chuẩn hóa response.
Các test này không chứng minh chất lượng Gemini hay độ chính xác dữ liệu Google.

Trước khi gọi là sẵn sàng sử dụng, cần thử live với khóa riêng: một truy vấn nhà
hàng, một khách sạn, một bảo tàng, địa danh mơ hồ và yêu cầu không có kết quả.
Đối chiếu tên/địa chỉ với nguồn, ghi latency và số tool calls, xác nhận không
biến thiếu giá thành miễn phí. Health check không kiểm chứng khóa nhà cung cấp.

## Tài liệu đối chiếu

- Google ADK Function Tools: https://adk.dev/tools-custom/function-tools/
- Google Places Text Search: https://developers.google.com/maps/documentation/places/web-service/text-search
- Google Place Details: https://developers.google.com/maps/documentation/places/web-service/place-details

API nhà cung cấp dùng field mask cụ thể, không lấy toàn bộ trường bằng wildcard.
Mã được kiểm thử với phiên bản ADK đã khóa trong uv.lock, không tự nâng lên ADK 2.
