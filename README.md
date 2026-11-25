# Travel Planning Multi-Agent (TravelMate)

Hệ thống lập kế hoạch du lịch nhiều agent: trợ lý chat, lập lịch từng ngày, chi phí so với
ngân sách, hướng dẫn viên có nguồn. Dữ liệu thật từ OpenStreetMap và Open-Meteo, model Gemini.

## Cấu trúc thư mục

```text
travel-planning-multi-agent/
├─ README.md            Bạn đang đọc: bản đồ dự án
├─ travelmate/          TOÀN BỘ ỨNG DỤNG (chạy, test, đóng gói Docker đều từ đây)
│  ├─ app/              Backend Python (FastAPI)
│  │  ├─ agents/        Các agent: lễ tân Trợ lý AI, lập lịch, chi phí, hướng dẫn viên, tự kiểm tra…
│  │  ├─ specialists/   Chuyên gia đơn lẻ (thời tiết, chi phí, gợi ý, lập lịch) chạy riêng được qua API
│  │  ├─ tools/         Gọi dữ liệu ngoài: địa điểm (OpenStreetMap), thời tiết, giá
│  │  ├─ data/          Dữ liệu có nguồn: giá vé, bảng chi phí, tỉnh thành
│  │  ├─ memory/        Database (SQLite/PostgreSQL): chuyến đi, đánh giá, sở thích
│  │  ├─ trust/         Tài khoản, mật khẩu, gửi email đặt lại mật khẩu
│  │  ├─ api/           Các đường dẫn /api/v1/… và trang web
│  │  ├─ core/          Nền chung: lớp cơ sở của agent, kết nối LLM, kiểu dữ liệu, theo dõi
│  │  └─ protocols/     MCP và A2A cho ứng dụng khác gọi vào
│  ├─ frontend/         Giao diện web (travelmate-v2 là trang chính)
│  ├─ tests/            Kiểm thử tự động (pytest, có test giao diện trên trình duyệt)
│  ├─ scripts/          Chạy đánh giá, kiểm tra trang thật, khởi động Place Agent
│  ├─ evaluation/       Kết quả các lần đánh giá đã chạy (báo cáo, số liệu)
│  ├─ examples/         Ví dụ yêu cầu/kết quả JSON
│  ├─ Dockerfile        Đóng gói để chạy trên máy chủ
│  └─ pyproject.toml    Thư viện cần cài (uv)
├─ docs/                Tài liệu, mục lục ở docs/README.md
│  ├─ kien-truc/        Từng pattern agent: multi-agent, planning, RAG, metacognition, MCP/A2A
│  ├─ san-pham/         Chức năng, quy tắc nghiệp vụ, bảo mật
│  └─ trien-khai/       Đưa lên Internet: AWS (chính), Render (dự phòng)
├─ deploy/aws/          Script cài máy chủ AWS EC2 (Docker + Caddy)
├─ render.yaml          Cấu hình Render (phải nằm ở thư mục gốc)
└─ .github/workflows/   CI: test mỗi PR, đóng gói image, canh trang đang chạy
```

Muốn hiểu dự án: đọc [docs/README.md](docs/README.md). Muốn sửa code: đọc [travelmate/README.md](travelmate/README.md).

## Chạy

```powershell
cd travelmate
uv sync --extra dev --extra ai --extra maf --extra postgres
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Mở http://127.0.0.1:8000/. Cấu hình (khoá Gemini, PostgreSQL) đặt trong `travelmate/.env`,
xem `travelmate/.env.example`. Không commit `.env`.

Hướng dẫn đầy đủ và sơ đồ từng thư mục: [travelmate/README.md](travelmate/README.md).
