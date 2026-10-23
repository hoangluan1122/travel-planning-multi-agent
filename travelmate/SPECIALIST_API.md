# Kiểm tra từng agent qua API

Server này gọi từng specialist độc lập, chưa phải A2A hoặc orchestration.
Không cần Maps key để khởi động. Recommendation và Planner nhận danh sách địa điểm
do caller cung cấp và cần Gemini key; chúng không tự tra cứu địa điểm.

## Khởi động

Chạy tại thư mục travelmate. Cài đủ dependencies:

    uv sync --extra dev --extra ai

Cấu hình trong `.env` (tự đặt token đủ mạnh, không commit file):

    TRAVELMATE_API_TOKEN=<token riêng cho backend>
    GOOGLE_API_KEY=<Gemini key>
    GEMINI_MODEL=gemini-3.5-flash-lite
    SPECIALIST_MEMORY_USER=<UUID của người vận hành local>
    SPECIALIST_MEMORY_DB=agent-memory.sqlite3
    SPECIALIST_TIMEOUT=60
    SPECIALIST_CONCURRENCY=2

GOOGLE_API_KEY chỉ cần khi gọi Recommendation/Planner. SPECIALIST_MEMORY_USER chỉ
cần khi gọi Memory. Token backend bắt buộc cho tất cả endpoint agent.

    uv run --no-sync uvicorn app.specialist_api:create_app --factory --host 127.0.0.1 --port 8002

Mở http://127.0.0.1:8002/docs, chọn Authorize và nhập token backend.
Mỗi endpoint có schema request/response để thử trực tiếp.

| Endpoint POST | Dữ liệu đầu vào | Đầu ra / xử lý |
|---|---|---|
| /api/v1/agents/weather | Tọa độ, múi giờ, ngày đầu/cuối | Open-Meteo, ngày thiếu dự báo, mưa và cờ rủi ro |
| /api/v1/agents/budget | Ngân sách, đơn giá, số lượng, nguồn từng khoản | Tổng Decimal, khoản chưa biết giá, nhóm thiếu, trạng thái ngân sách |
| /api/v1/agents/memory | read/save/forget, xác nhận, expected_version | Sở thích, phiên bản và hạn lưu SQLite |
| /api/v1/agents/recommendation | candidates, interests, limit | Gemini dùng inspect_candidates + submit_ranking; chỉ trả ID đã cung cấp |
| /api/v1/agents/planner | trip, places, weather | Gemini dùng tool kiểm tra/lưu lịch trình; kiểm tra ngày, địa điểm và chồng giờ |

Ví dụ JSON có sẵn tại examples/budget.json, weather.json, memory-read.json,
memory-save.json, recommendation.json và planner.json. Cập nhật ngày trước khi thử.
Thêm notes trong trip nếu có yêu cầu bổ sung.

## Hợp đồng lỗi

- 401: thiếu/sai token.
- 409: Memory version đã cũ; đọc lại trước khi sửa.
- 422: sai schema hoặc ghi/xóa Memory chưa confirmed=true.
- 429: đã đầy số tác vụ đồng thời; Retry-After chỉ là thời gian gợi ý.
- 502: agent/provider không trả được kết quả hợp lệ. Không lộ thông báo lỗi chứa key.
- 503: thiếu cấu hình hoặc thư viện AI.
- 504: vượt thời gian chờ. Sau ghi Memory timeout phải đọc lại vì thread SQLite có thể đã commit.

X-Request-ID được trả với kết quả thành công và lỗi thực thi 502 để đối chiếu log.
Log chỉ ghi tên agent, request ID và loại exception; không ghi prompt hoặc key.

## Ranh giới triển khai

Đây là workbench local cho một người vận hành. Token ánh xạ đến danh tính Memory
cấu hình tại server; không có JWT đa người dùng. Không đưa server này lên mạng
như hệ thống nhiều tài khoản. Giới hạn đồng thời áp dụng trên từng process, không
phải quota phân tán hoặc giới hạn chi phí Gemini theo ngày.

Weather/Budget/Memory dùng logic xác định. Recommendation/Planner dùng ADK LlmAgent,
Runner, tool calling và session riêng từng request. Các adapter này chưa thay thế
luồng preview của frontend; cần bước tích hợp multi-agent riêng sau khi chốt hợp đồng.

Kiểm thử: tests/test_specialist_api.py cộng các test specialist/ADK hiện có.
Test API không gọi Gemini tính phí; test vòng tool dùng scripted model thật qua ADK.
