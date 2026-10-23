# Place discovery bằng trình duyệt và nguồn chính thức

## Đã thực hiện

- Tìm kiếm Cốc Cốc bằng trình duyệt Edge riêng, không dùng hồ sơ cá nhân.
- Chỉ đọc card kết quả thường, không lấy card quảng cáo, không vượt CAPTCHA.
- Đọc Location header của liên kết chuyển hướng Cốc Cốc, không theo chuyển hướng
  tới host bất kỳ. Giới hạn tối đa 5 nguồn/lần, 55 giây nội bộ.
- Khi tìm khách sạn mà không có keyword, dùng thêm một truy vấn giới hạn vào
  MGallery để tìm URL phù hợp với adapter đã kiểm tra. Không gắn sẵn tên hay ID khách sạn.
- Chỉ tự mở các URL khách sạn MGallery đúng mẫu đã duyệt; đọc JSON-LD Hotel,
  kiểm tra URL danh tính, địa danh khớp chính xác sau chuẩn hóa, quốc gia Việt Nam,
  tên, địa chỉ và tọa độ hợp lệ. Kiểm tra robots, không theo redirect, giới hạn response.
- Kết quả có `sources` (nguồn tìm thấy) tách biệt với `places` (bản ghi từ nguồn
  chính thức có tọa độ). Một trang tổng hợp nhiều khách sạn không trở thành một Place.
- `official_details` hỗ trợ adapter liên hệ Hotel De La Coupole trước đây khi
  domain của khách sạn thực sự xuất hiện trong tìm kiếm.
- Đã nối vào PlaceAssistant qua cấu hình browser, giữ chế độ OSM/Google cũ.

## Chạy tool không cần Gemini/Maps key

Trong thư mục travelmate, với extras browser đã cài và Edge sẵn có:

```powershell
uv run --no-sync python -X utf8 -m app.browser_places --destination "Sa Pa" --output evaluation/browser-places-sapa-live.json
uv run --no-sync python -X utf8 -m app.browser_places --destination "Sa Pa" --keyword "Hotel de la Coupole" --output evaluation/browser-places-coupole-live.json
```

Specialist API: `POST /api/v1/tools/places/browser`, Bearer token cấu hình trên
server. Body ví dụ:

```json
{"destination":"Sa Pa","category":"hotel","keyword":"","limit":5}
```

## Chạy với LLM PlaceAssistant

Đặt `PLACE_PROVIDER=browser` cùng `GOOGLE_API_KEY` và `TRAVELMATE_API_TOKEN` trong
cấu hình server. Không đưa key vào request hoặc frontend. Chạy:

```powershell
uv run --no-sync uvicorn app.place_api:create_app --factory --host 127.0.0.1 --port 8001
```

Gửi `POST /api/v1/agent/places` có Bearer token, body như trên, thêm `needs` nếu cần.
LLM gọi search tool; khi tool hoàn tất, ứng dụng trả dữ liệu đã kiểm tra và dừng,
không cho LLM viết lại tọa độ/giá hoặc biến snippet thành sự thật. Chế độ này trả
`partial`, trường `places` chỉ có bản ghi chính thức, còn `web_discovery.sources`
chứa các nguồn chưa đủ dữ liệu. Không thay đổi provider mặc định OSM tự động.

## Bằng chứng và giới hạn

`evaluation/browser-places-coupole-live.json` được tạo từ lần chạy mạng thật
22/10/2026, không từ fixture: tìm thấy trang MGallery rồi đọc tên, địa chỉ và tọa độ
22.334686, 103.840433 từ JSON-LD Hotel tại chính URL tìm được.
`evaluation/browser-places-sapa-live.json` ghi kết quả thử nhập chỉ tên địa danh.
Các artifact là snapshot có thời điểm, không đảm bảo dữ liệu không đổi về sau.

- Adapter MGallery hoạt động theo mẫu URL chung, không phải chỉ ID A5V2; tuy vậy
  lần chạy thật hiện chỉ xác minh khách sạn Sa Pa nêu trên. Chưa phủ toàn bộ nguồn Việt Nam.
- Nhà hàng/điểm tham quan hiện mới tìm nguồn, chưa có adapter tạo Place chính thức.
- Tọa độ là tuyên bố của website khách sạn, không phải đo/kiểm chứng thực địa.
- Không xác nhận giá, tồn phòng, giờ mở cửa, giấy phép ảnh. Giá luôn null nếu chưa có nguồn hợp lệ.
- Không lọc theo bán kính/location_id trong chế độ browser. Địa danh mơ hồ hoặc
  tên tỉnh không được tự thay bằng địa danh của khách sạn.
- Lỗi/không đọc được kết quả là source_error/blocked/timeout, không phải bằng chứng
  không có khách sạn. Không dùng dữ liệu demo dự phòng.
- Chưa nối frontend hoặc orchestration đa agent. Chưa chạy Gemini thật trong đợt
  xác minh này; tích hợp ADK được kiểm thử bằng ScriptedModel và tool kiểm thử riêng.
- Đây là thử nghiệm giới hạn, chưa có cache/rate-limit phân tán cho sản xuất.
  Không mở API công khai hoặc tăng crawl hàng loạt; cần kiểm tra điều khoản nguồn và tải trước triển khai.
- UI phải escape title/snippet như văn bản, không render HTML từ nguồn. Chỉ dùng
  trường places cho dữ liệu địa điểm; không coi sources là danh sách địa điểm đã xác minh.
