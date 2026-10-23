# TravelMate backend và Multi-Agent

**Các specialist độc lập:** xem [SPECIALISTS.md](SPECIALISTS.md) để chạy Weather,
Budget, Memory, Recommendation và Planner riêng lẻ. Chưa tích hợp vào multi-agent.

**Place Agent có giao diện, cập nhật 23/10/2026:** xem [NATIONAL_PLACE_AGENT.md](NATIONAL_PLACE_AGENT.md).
Chạy `.\start-live-place.ps1`, mở http://127.0.0.1:8001/. Hỗ trợ lưu trú, ăn uống,
tham quan qua GeoNames/Photon/OSM, có phân trang và xuất JSON. Không cần Maps key.
Có tìm quanh điểm, theo polygon của 34 tỉnh/thành tham chiếu, 63 khu vực lịch sử,
và phạm vi cả nước. Không khẳng định đã có mọi địa điểm hoặc ranh giới pháp lý hiện hành.
Chế độ mặc định dùng công cụ xác định; ADK + Gemini là chế độ cấu hình riêng.
Chưa tích hợp workflow multi-agent. [PLACE_AGENT.md](PLACE_AGENT.md) mô tả API/provider cũ.

Bản nền tảng đầu tiên: API tạo bản nháp lịch trình, 6 agent có schema vào/ra,
registry chống trùng tên, điều phối Place/Weather song song, ADK adapter cho Planner.
Không phải bản hoàn chỉnh của sản phẩm. Không thay đổi database PostgreSQL hiện có.

## Chạy demo (PowerShell)

```powershell
uv sync --extra dev
uv run uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

Mở http://127.0.0.1:8000/docs, chọn POST /api/v1/plans/preview.
Nhập destination, start_date/end_date ở tương lai, travelers, budget_vnd và interests.
Demo trả địa điểm **giả lập**, không gọi dịch vụ ngoài, không tốn lượt Gemini.
Không mở cổng public khi chưa cấu hình bảo mật người dùng và giới hạn truy cập.

## Chạy với dịch vụ thật

1. `uv sync --extra dev --extra ai`.
2. Sao chép `.env.example` thành `.env` (không commit file này).
3. Điền GOOGLE_API_KEY, GOOGLE_MAPS_API_KEY, TRAVELMATE_API_TOKEN và model có quyền sử dụng.
4. Đặt TRAVELMATE_MODE=live. Khởi động như trên.
5. Chạy `uv run --no-sync uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000` để giữ các dependency AI đã cài.
6. Gửi header `Authorization: Bearer <TRAVELMATE_API_TOKEN>`.

Live gọi Google Places, Open-Meteo và Gemini qua ADK. Có thể phát sinh chi phí API.
Không fallback sang địa điểm demo khi live lỗi. Weather lỗi được hiển thị dưới dạng cảnh báo.
API token ở đây chỉ bảo vệ bản thử nghiệm, KHÔNG thay thế đăng nhập JWT/phân quyền người dùng.

## Thiết kế

- `app/models.py`: hợp đồng Pydantic; input sai bị từ chối.
- `app/agents.py`: BaseAgent generic, Registry và 6 agent.
- `app/orchestrator.py`: workflow và kiểm tra lịch trình trước khi trả ra.
- `app/providers.py`: công cụ dữ liệu demo/live, HTTP timeout.
- `app/adk_adapter.py`: Planner LLM gọi tool đọc dữ liệu và nộp lịch trình; lỗi được trả về để sửa, có giới hạn số lượt và session riêng từng request.
- `AGENT_DESIGN.md`: nguồn nghiên cứu, cơ chế tool loop, ranh giới kiểm thử và phần còn thiếu.
- `app/main.py`: FastAPI, cấu hình và endpoint preview không ghi dữ liệu.

Thêm agent: định nghĩa schema, kế thừa BaseAgent, đăng ký tên duy nhất, bổ sung bước
workflow và test. Không giữ trạng thái người dùng trong thuộc tính dùng chung.
Input văn bản từ nguồn bên ngoài không được coi là chỉ dẫn hệ thống.

## Giới hạn đã biết và bước tiếp theo

- Memory mới dùng sở thích trong request; chưa đọc/lưu lịch sử PostgreSQL.
- Recommendation dùng đối sánh từ khóa đơn giản, chưa có xếp hạng semantic.
- API tìm địa điểm hỗ trợ điểm tham quan/khách sạn/nhà hàng; chưa lấy ảnh và giờ mở cửa.
- Luồng Planner vẫn chỉ dùng điểm tham quan; chưa tự ghép khách sạn và bữa ăn vào lịch trình.
- Weather geocoding lấy kết quả đầu tiên; cần xác nhận địa danh trước dùng thực tế.
- Planner trả bản nháp, chưa kiểm tra Routes API, giờ mở cửa hay tối ưu toàn cục.
- Budget chỉ cộng chi phí tham quan nếu có; chi phí còn thiếu luôn được báo rõ.
- Chưa có auth JWT, migration, lưu lịch trình, frontend, hàng đợi, SSE hoặc A2A.
- Không triển khai 6 dịch vụ giả để gọi là A2A: cần bổ sung adapter A2A chính thức
  cùng authentication service-to-service và integration test ở giai đoạn tiếp.
- Chưa có kiểm thử gọi API thật; chỉ chạy khi có khóa và ngân sách được cấu hình.

## Kiểm thử

```powershell
uv run --no-sync pytest -q
uv run --no-sync ruff check app tests
```

Tham khảo chính thức:
- https://github.com/google/adk-docs/blob/main/docs/agents/llm-agents.md
- https://developers.google.com/maps/documentation/places/web-service/text-search
- https://open-meteo.com/en/docs

## Tìm khách sạn, nhà hàng, điểm tham quan

Trong Swagger tại `/docs`, dùng `POST /api/v1/places/search`:

```json
{
  "destination": "Da Nang, Vietnam",
  "category": "hotel",
  "limit": 5
}
```

`category` nhận `hotel`, `restaurant` hoặc `attraction`. Mỗi yêu cầu live gọi
Google Places một lần, tối đa 20 kết quả; không tự phân trang hoặc retry có phí.
Danh mục là mục tiêu tìm kiếm bằng từ khóa, không phải bộ lọc loại hình tuyệt đối.
Trường `types` là các loại hình do nhà cung cấp trả về, `fetched_at` là thời điểm
máy chủ lấy dữ liệu (UTC), không khẳng định dữ liệu tại nguồn vừa được cập nhật.
Giá chưa có vẫn là `null`, không phải 0. Tìm được khách sạn không chứng minh còn
phòng hoặc có giá phòng cho ngày đi. Demo trả dữ liệu giả lập có nhãn rõ ràng.

Kết quả trùng ID được loại bỏ; bản ghi lỗi bị bỏ qua kèm cảnh báo. Lỗi dịch vụ trả
502, hết thời gian trả 504, đầu vào sai trả 422. Endpoint áp dụng cùng API token
với endpoint tạo lịch trình; chưa có rate limit để mở public.
