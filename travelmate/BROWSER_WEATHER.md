# Browser Weather Tool — Cốc Cốc

Tool mở trang tìm kiếm Cốc Cốc bằng Playwright trong browser context riêng, chọn
ngày và từng giờ trên bảng thời tiết rồi đọc DOM đang hiển thị. Không gọi API
Open-Meteo/OpenWeather, không cần Gemini key, không đọc forecast từ snippet tìm kiếm.
LLM có thể gọi tool này sau đó; bản thân tool không sinh số liệu bằng LLM.

## Chạy thử

Tại thư mục travelmate:

```powershell
uv sync --extra dev --extra ai --extra browser
uv run --no-sync python -m app.browser_weather --input examples/weather-browser-sapa.json --output evaluation/browser-weather-sapa.json --evidence-dir evaluation/browser-weather-evidence
```

Sửa ngày trong file mẫu theo ngày cần đi. Mặc định Windows dùng Edge cài sẵn để
mở website coccoc.com; không mở profile cá nhân hay cần đăng nhập Cốc Cốc.
Thêm `--headed` để xem cửa sổ chạy, `--channel chrome` nếu muốn dùng Chrome.
Linux mặc định dùng Chromium; cài browser bằng `uv run --no-sync playwright install chromium`.
Tham khảo [Playwright browser channels](https://playwright.dev/python/docs/browsers).

## Hợp đồng đầu vào

Xem examples/weather-browser-sapa.json:

- location.name, province: địa danh và tỉnh; country_code chỉ nhận VN.
- scope: locality, province hoặc point_of_interest. province luôn yêu cầu làm rõ.
- Nếu name giống hệt province (ví dụ Lào Cai/Lào Cai), tool yêu cầu địa danh cụ thể;
  có thể nhập tên đầy đủ Phường Lào Cai khi thực sự cần khu vực này.
- latitude/longitude tùy chọn, phải có cả cặp; adapter không thể xác minh tọa độ
  vì bảng hiện tại không hiển thị chúng. Không biến tọa độ đầu vào thành bằng chứng.
- date + start_time/end_time: cùng một ngày, theo Asia/Ho_Chi_Minh.
- Khoảng [08:00,11:00) đọc mốc 08,09,10; [08:30,10:30) đọc 08,09,10, không nội suy.

## Kiểm tra và bằng chứng

1. Tối đa 3 truy vấn: tên địa danh trước, thêm tỉnh/quốc gia khi chưa khớp.
2. So khớp toàn bộ tên khu vực và tỉnh trên tiêu đề bảng, hỗ trợ Sa Pa/Sapa,
   bỏ dấu và tiền tố hành chính. Không dùng phép tìm chuỗi con hoặc đổi Fansipan
   thành Sa Pa. Chưa hỗ trợ từ điển alias/tên hành chính cũ ngoài quy tắc này.
3. Lấy ngày đầy đủ từ header; kiểm tra ngày + thứ trên dải ngày để suy ra tháng/năm,
   bao gồm thời điểm qua tháng/năm. Từ chối widget cũ quá một ngày hoặc đề ngày tương lai.
4. Sau click ngày/giờ, kiểm tra lại header và tên địa điểm. Khi trang không đổi
   đúng thời gian, không nhận giá trị đó.
5. Chỉ đọc nhiệt độ có °C, gió km/h, mưa mm, xác suất/độ ẩm %. Đơn vị khác để null.
   Không lấy chỉ số AQI hoặc nhiệt độ min/max cả ngày làm giá trị theo giờ.
6. Mỗi mẫu có evidence_index trỏ đến URL, tên địa điểm, thời gian, nội dung DOM,
   thời điểm truy xuất. Validator kiểm tra liên kết mẫu–bằng chứng và giờ bị thiếu.
7. Ảnh tùy chọn ghi trạng thái cuối cùng của bảng; nội dung DOM lưu riêng từng giờ.

Các trạng thái: ok, partial, needs_location, location_mismatch, outside_forecast,
blocked, source_error, timeout. `ok` nghĩa là trích xuất đủ nhiệt độ, xác suất mưa,
gió cho các mốc giờ yêu cầu; không có nghĩa dự báo chính xác ngoài thực tế.

## API và ADK

Endpoint đã đăng ký trong specialist API:

    POST /api/v1/tools/weather/browser

Chạy `uv run --no-sync uvicorn app.specialist_api:create_app --factory --host 127.0.0.1 --port 8002`.
TRAVELMATE_API_TOKEN bắt buộc như các endpoint khác; xem /docs để thử.
Không cần GOOGLE_API_KEY cho endpoint browser này.

Hàm đăng ký vào tools của ADK:

```python
from app.browser_weather.tool import get_weather_from_browser

# Khi xây Weather LlmAgent: tools=[get_weather_from_browser]
# Tool nhận request_json theo schema; không nhận URL tùy ý.
```

Chưa gắn tool vào orchestration/frontend. API Weather dựa trên Open-Meteo vẫn
được giữ riêng; không fallback âm thầm sang nguồn đó khi browser lỗi.

## Giới hạn vận hành

- Chỉ có adapter bảng Cốc Cốc được kiểm tra; CSS selector có thể đổi. Khi không
  nhận diện được layout, trả lỗi/partial thay vì đoán dữ liệu.
- Dùng browser không vượt CAPTCHA, không stealth, không đăng nhập, không lấy
  session trình duyệt cá nhân. Main-frame navigation giới hạn coccoc.com/search.
- Tool có ngân sách 55 giây, caller nên cấp 60 giây. Endpoint dùng giới hạn đồng
  thời của specialist API. Không retry vô hạn, không tự tạo tác vụ nền.
- Chưa cache để tránh dùng lại dữ liệu sai thời điểm. Mỗi lần gọi mở context mới.
- Nhà cung cấp khí tượng gốc chưa hiển thị rõ trên card; data_provider=null.
- Không xác minh tọa độ/độ cao, độ phân giải mô hình hay dự báo vi khí hậu.
- Lượng mưa giữ đơn vị mm nhưng khoảng tích lũy chưa được trang nêu rõ.
- Chưa có benchmark độ chính xác thời tiết tại Việt Nam, hay xác nhận quyền tái
  phân phối dữ liệu thương mại. Đây là bản tích hợp thử nghiệm cho đồ án.

## Kiểm chứng ngày 22/10/2026

Chạy browser thật đọc Phường Sa Pa, Lào Cai, dự báo 23/10 từ 08:00 đến 11:00.
Kết quả tại evaluation/browser-weather-sapa.json có ba mốc giờ và bằng chứng.
Đây là kiểm tra trích xuất thành công, không phải xác nhận dự báo sẽ đúng.

Các test tại tests/test_browser_weather.py kiểm tra đúng/sai địa danh, retry truy
vấn, CAPTCHA, thiếu giờ, timeout/cleanup, stale widget, đơn vị, đổi tháng/năm,
không nhầm hiện tại với tương lai, liên kết bằng chứng và auth/schema API.
