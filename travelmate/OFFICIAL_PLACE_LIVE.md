# Đọc dữ liệu địa điểm thật từ website chính thức

## Kết quả đã chạy trực tiếp

Ngày 22/10/2026, chạy `app.official_place` từ dự án đã nhận HTTP 200 và trích xuất
tên, địa chỉ, điện thoại từ trang https://www.hoteldelacoupole.com/vi/find-us/.
Kết quả lưu tại `evaluation/official-place-live.json`, có thời điểm lấy UTC,
URL nguồn, bằng chứng cho từng trường và SHA-256 nội dung phản hồi.
Tên, địa chỉ và điện thoại không được ghi cứng trong adapter.

```powershell
uv run --no-sync python -X utf8 -m app.official_place --source-id coupole-sapa --output evaluation/official-place-live.json
```

API trên specialist workbench: `POST /api/v1/tools/places/official`, dùng Bearer
token như các endpoint khác. Body:

```json
{"source_id":"coupole-sapa"}
```

Không cần khóa Gemini hoặc Google Maps cho tool này. Tool kiểm tra robots.txt,
không theo redirect, giới hạn kích thước và thời gian, không trả dữ liệu giả khi
nguồn bị lỗi. Chỉ chấp nhận ID nguồn đã cấu hình trên server, không nhận URL tùy ý.

## Phạm vi và giới hạn

- Đây là adapter đọc chi tiết **một website đã kiểm tra**, chưa phải bộ tìm kiếm
  địa điểm bất kỳ và không thay thế nguồn OSM bằng một danh sách viết cứng.
- Test tự động dùng HTTP giả lập để kiểm tra lỗi; JSON trong evaluation ở trên
  là kết quả của lần chạy HTTP thật, không lấy từ test fixture.
- Tọa độ và giá để null. Chưa có dữ liệu phòng trống, giờ mở cửa, ảnh có quyền sử dụng.
- Địa chỉ giữ nguyên văn bản nguồn; không tự đổi tên đơn vị hành chính.
- Không tự chuyển kết quả này thành Place có tọa độ bắt buộc, không đưa vào
  Planner khi chưa xác minh tọa độ. Chưa kết nối vào frontend hoặc vòng LLM PlaceAssistant.
- OSM/Overpass vẫn chưa hoạt động thành công ở môi trường này: lần kiểm tra mới
  trả 406 ở máy chủ chính và timeout ở private.coffee.
- Bước còn lại để có tìm kiếm thật tổng quát: bộ khám phá URL, kiểm tra danh tính
  địa điểm, adapter nhiều nguồn, xác minh tọa độ, sau đó tích hợp PlaceAssistant.
  Cần kiểm tra điều khoản nguồn, tải và chính sách truy cập trước khi mở rộng thu thập.
