# TravelMate

Backend FastAPI, các agent và giao diện thử nghiệm cho hệ thống lập kế hoạch du lịch.

## Cài đặt

Chạy các lệnh sau trong thư mục `travelmate`:

```powershell
uv sync --extra dev --extra ai --extra browser
```

Chỉ tạo `.env` từ `.env.example` khi cần cấu hình khóa API; không commit `.env`.

## Place Agent — dữ liệu thật

```powershell
uv run uvicorn app.live_place_api:create_app --factory --host 127.0.0.1 --port 8001
```

Mở http://127.0.0.1:8001/. Hỗ trợ tìm lưu trú, ăn uống và tham quan qua
GeoNames/Open-Meteo và Photon/OpenStreetMap; chọn địa danh, bán kính, khu vực,
phân trang và tải JSON. Không cần khóa Google Maps cho giao diện này.

Khi tên trùng nhau, chọn đúng địa danh và loại thực thể. Với khu du lịch lớn,
điểm nguồn có thể là tâm hình học. Nút mở rộng bán kính cần người dùng bấm xác nhận.
Mặc định chạy workflow công cụ; ADK/LLM là chế độ tùy chọn cần cấu hình riêng.

## API lịch trình thử nghiệm

```powershell
uv run uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

Mở http://127.0.0.1:8000/docs. `.env.example` mặc định `TRAVELMATE_MODE=demo`:
endpoint demo dùng dữ liệu giả lập có nhãn. Cấu hình `live` cần khóa API tương ứng.

## Cấu trúc

- `app/`: API, schema, agent, provider và công cụ.
- `frontend/`: các giao diện thử nghiệm.
- `tests/`: kiểm thử tự động và fixture hồi quy.
- `scripts/`: nhập dữ liệu tham chiếu và kiểm tra nguồn thật.
- `evaluation/`: phản hồi API, bằng chứng HTTP và kết quả kiểm thử.
- `examples/`: đầu vào/ví dụ chạy thử.

## Kiểm thử

```powershell
uv run --no-sync pytest -q
```

Lần kiểm tra ngày 23/10/2026: **513 passed**, 1 cảnh báo deprecation TestClient.
Kiểm tra giao diện đạt. 15 lượt thử dữ liệu thật sau sửa có 14 lượt trả bản ghi
trong 5 km; khách sạn Fansipan trả rỗng trong 5 km và có 5 bản ghi khi thử 10 km.

Bằng chứng: `evaluation/fix-verification-20261022T182826Z/` và
`evaluation/fix-verification-20261022T183050Z/`.

Chưa xác minh mọi điểm đến Việt Nam. Tràng An còn cần kiểm tra nguồn đúng quần thể
khu du lịch; Sầm Sơn cần kiểm tra sai số polygon tham chiếu. Giá, phòng trống,
ảnh được cấp quyền và trạng thái đang hoạt động chưa được xác minh đầy đủ.
Tích hợp workflow multi-agent và sản phẩm hoàn chỉnh vẫn đang phát triển.

## Nguồn dữ liệu

Thông tin nguồn, phiên bản ranh giới và điều kiện sử dụng được giữ trong
[`app/data/README.md`](app/data/README.md). Dữ liệu OpenStreetMap thuộc các cộng tác viên,
được cung cấp theo [ODbL](https://www.openstreetmap.org/copyright).
