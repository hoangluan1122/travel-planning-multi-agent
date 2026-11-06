# Travel Planning Multi-Agent (TravelMate)

Hệ thống lập kế hoạch du lịch nhiều agent: trợ lý chat, lập lịch từng ngày, chi phí so với
ngân sách, hướng dẫn viên có nguồn. Dữ liệu thật từ OpenStreetMap và Open-Meteo, model Gemini.

```text
travel-planning-multi-agent/
├─ travelmate/        Mã nguồn: backend, agent, giao diện, test (xem travelmate/README.md)
│  ├─ app/            Backend, chia theo core · agents · memory · tools · trust · protocols
│  ├─ frontend/       Giao diện web
│  ├─ tests/          Kiểm thử tự động
│  └─ scripts/        Đánh giá, nhập dữ liệu, gọi thử MCP/A2A
└─ docs/              Giải thích từng pattern: multi-agent, planning, RAG, MCP/A2A, metacognition
```

## Chạy

```powershell
cd travelmate
uv sync --extra dev --extra ai --extra maf --extra postgres
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Mở http://127.0.0.1:8000/. Cấu hình (khoá Gemini, PostgreSQL) đặt trong `travelmate/.env`,
xem `travelmate/.env.example`. Không commit `.env`.

Hướng dẫn đầy đủ và sơ đồ từng thư mục: [travelmate/README.md](travelmate/README.md).
