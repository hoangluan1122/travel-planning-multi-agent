# Travel Planning Multi-Agent

Mã nguồn đang phát triển nằm trong [`travelmate/`](travelmate/). Xem
[hướng dẫn chạy](travelmate/README.md).

Thư mục `backend/` và `docker-compose.yml` ở gốc là phiên bản khởi tạo trước đó.

## Chạy Place Agent

```powershell
cd travelmate
uv sync --extra dev --extra ai --extra browser
uv run uvicorn app.live_place_api:create_app --factory --host 127.0.0.1 --port 8001
```

Mở http://127.0.0.1:8001/. Dữ liệu địa điểm lấy từ nguồn mạng thật.

## Trạng thái ngày 23/10/2026

- 513 kiểm thử Python đạt; kiểm tra giao diện đạt.
- 14/15 lượt kiểm tra nguồn thật có kết quả trong 5 km. Lượt khách sạn Fansipan
  có kết quả khi người dùng mở rộng lên 10 km.
- Chưa hoàn tất xác minh mọi địa danh Việt Nam, tích hợp multi-agent và sản phẩm.
- Bằng chứng kiểm thử nằm trong `travelmate/evaluation/`.

