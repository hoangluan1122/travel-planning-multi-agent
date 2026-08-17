# Travel Planning Multi-Agent

Nền tảng lập kế hoạch du lịch sử dụng kiến trúc Multi-Agent. `PlannerAgent` điều phối các agent chuyên trách về địa điểm, thời tiết, ngân sách và ghi nhớ sở thích để tạo lịch trình theo ngày.

## Thành phần hiện có

- FastAPI REST API và tài liệu Swagger tại `/docs`.
- `PlannerAgent`: điều phối các agent và phân bổ hoạt động theo ngày.
- `PlaceAgent`, `WeatherAgent`, `BudgetAgent`, `MemoryAgent`: các agent nền tảng với dữ liệu mô phỏng, sẵn sàng thay bằng API thật.
- Endpoint `POST /api/v1/trips/plan` để tạo lịch trình.
- Docker Compose để chạy backend.

## Chạy nhanh

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Mở `http://localhost:8000/docs` để thử API.

## Ví dụ request

```json
{
  "destination": "Đà Nẵng",
  "start_date": "2026-09-10",
  "end_date": "2026-09-12",
  "budget": 5000000,
  "interests": ["ẩm thực", "biển", "văn hóa"],
  "traveler_id": "demo-user"
}
```

## Hướng phát triển

1. Thay dữ liệu mô phỏng bằng Google Places/Maps API và Weather API.
2. Tích hợp Gemini cho Recommendation Agent.
3. Lưu người dùng, lịch trình và sở thích vào PostgreSQL.
4. Bổ sung giao diện React/Next.js và xác thực JWT.

