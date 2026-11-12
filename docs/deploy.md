# Đưa TravelMate lên Internet (miễn phí)

Hướng dẫn này đưa TravelMate lên một địa chỉ công khai `https://…onrender.com` bằng các dịch vụ
miễn phí, không cần thẻ:

| Phần | Dịch vụ | Gói miễn phí |
|---|---|---|
| Máy chủ web | [Render](https://render.com) — chạy `travelmate/Dockerfile` | 512 MB RAM, 750 giờ/tháng; **ngủ sau 15 phút không có ai truy cập**, lần mở đầu tiên sau đó chờ khoảng 1 phút |
| Cơ sở dữ liệu | [Neon](https://neon.com) — PostgreSQL | 1 GB, tự tạm dừng khi rảnh, bật lại trong chưa tới một giây |
| AI | Gemini API của Google ([Google AI Studio](https://aistudio.google.com/apikey)) | Hạn mức miễn phí theo ngày của Google |
| Địa điểm, thời tiết | OpenStreetMap (Photon, Overpass), Open-Meteo | Không cần khoá |

Không dùng PostgreSQL miễn phí của Render: nó bị xoá sau 30 ngày.

## 1. Tạo cơ sở dữ liệu trên Neon

1. Đăng ký tại <https://console.neon.tech> (có thể dùng tài khoản GitHub).
2. **Create project** → đặt tên `travelmate`, chọn vùng gần Việt Nam nhất có trong danh sách (ví dụ Singapore).
3. Ở **Connection string**, chọn dạng `postgresql://…` và sao chép. Chuỗi này chứa mật khẩu: chỉ dán vào Render,
   không gửi cho ai và không đưa vào mã nguồn.

TravelMate tự tạo bảng ở lần chạy đầu tiên.

## 2. Tạo dịch vụ trên Render

1. Đăng ký tại <https://dashboard.render.com> bằng tài khoản GitHub chứa repo này.
2. **New → Blueprint**, chọn repo `travel-planning-multi-agent`. Render đọc `render.yaml` ở thư mục gốc.
3. Render hỏi các biến chưa có giá trị:

| Biến | Điền gì |
|---|---|
| `GOOGLE_API_KEY` | Khoá Gemini từ Google AI Studio |
| `TRAVELMATE_DATABASE_URL` | Chuỗi kết nối Neon ở bước 1 |
| `TRAVELMATE_ADMIN_EMAIL` | Email bạn sẽ dùng để đăng ký: tài khoản đăng ký bằng email này thành quản trị viên |
| `TRAVELMATE_PUBLIC_URL` | Để trống lần đầu; điền sau khi biết địa chỉ (bước 3) |
| `TRAVELMATE_OPERATOR_NAME` | Tên cá nhân/đơn vị vận hành, hiện trên trang Điều khoản và Bảo mật (có thể để trống) |
| `TRAVELMATE_CONTACT_EMAIL` | Email nhận liên hệ, hiện công khai trên trang Liên hệ (có thể để trống: khách vẫn gửi được qua biểu mẫu) |

4. **Apply**. Lần build đầu mất vài phút. `TRAVELMATE_API_TOKEN` được Render tạo ngẫu nhiên: khách
   phải đăng nhập mới dùng được AI, nên hạn mức theo tài khoản luôn có hiệu lực.

## 3. Sau khi chạy

1. Mở địa chỉ Render cấp (dạng `https://travelmate-xxxx.onrender.com`), kiểm tra `…/health` trả `"status":"ok"` và `"database":"postgresql"`.
   Nếu deploy thất bại với `Live mode requires GOOGLE_API_KEY and TRAVELMATE_API_TOKEN` trong **Logs**,
   khoá Gemini chưa được điền: thêm `GOOGLE_API_KEY` ở **Environment** rồi deploy lại.
2. Vào **Environment** của dịch vụ, điền `TRAVELMATE_PUBLIC_URL` bằng địa chỉ đó (không có `/` ở cuối) rồi lưu.
   Địa chỉ này được dùng trong link đặt lại mật khẩu, `sitemap.xml` và ảnh xem trước khi chia sẻ link.
3. Đăng ký tài khoản bằng `TRAVELMATE_ADMIN_EMAIL`; mục **Quản trị** hiện trên menu.
4. Lập thử một chuyến đi và gửi thử một tin nhắn ở trang **Liên hệ**; tin nhắn hiện ở **Quản trị → Liên hệ**.

### Tên miền riêng (tuỳ chọn)

Render cho gắn tên miền riêng miễn phí (Settings → Custom Domains) và tự cấp HTTPS; bạn chỉ trả tiền mua tên miền.
Sau khi gắn, đổi `TRAVELMATE_PUBLIC_URL` sang tên miền mới.

### Báo cho Google biết trang web

Vào [Google Search Console](https://search.google.com/search-console), thêm địa chỉ trang và gửi
`https://<địa chỉ>/sitemap.xml`. Chỉ các trang công khai (trang chủ, Khám phá, Trợ lý AI, Tạo chuyến đi,
Giới thiệu, Bảng giá, Liên hệ, Điều khoản, Bảo mật) có trong sitemap; trang cá nhân có `noindex`.

## Giới hạn của gói miễn phí và cách xử lý

| Giới hạn | Ảnh hưởng | Cách xử lý |
|---|---|---|
| Render ngủ sau 15 phút | Người đầu tiên chờ khoảng 1 phút | Chấp nhận, hoặc nâng gói Render khi có người dùng thường xuyên |
| Render chặn cổng SMTP (25, 465, 587) | Email đặt lại mật khẩu **không gửi được** | Người dùng quên mật khẩu nhắn qua trang Liên hệ; quản trị viên vào **Quản trị → Người dùng → Tạo link đặt lại** rồi gửi link cho họ. Không cần điền các biến `TRAVELMATE_SMTP_*` |
| Hạn mức Gemini miễn phí theo ngày | Hết hạn mức thì lập lịch chuyển sang xếp lịch theo luật (vẫn có lịch, có ghi chú) | Giữ `TRAVELMATE_DAILY_PLANS` / `TRAVELMATE_DAILY_CHATS` ở mức vừa phải |
| 512 MB RAM, 0,1 CPU | Lập lịch chậm hơn máy cá nhân | Đủ cho một máy chủ nhỏ |

## Hạn mức AI cho mỗi tài khoản

Mỗi tài khoản (trừ quản trị viên) được `TRAVELMATE_DAILY_PLANS` lượt lập lịch và `TRAVELMATE_DAILY_CHATS`
tin nhắn với Trợ lý AI mỗi ngày, làm mới lúc 0 giờ giờ Việt Nam. Lượt lập lịch lỗi không bị tính. Người dùng
xem số lượt còn lại trong **Tài khoản**; trang **Bảng giá** và **Điều khoản** hiện đúng con số đang cấu hình.
Đặt `0` để bỏ giới hạn.

## CI/CD

- **CI** (`.github/workflows/ci.yml`, GitHub Actions, miễn phí cho repo công khai) chạy cho mỗi PR và mỗi commit lên `main`:
  - **Lint and tests**: `ruff` và toàn bộ test, gồm cả bản chạy trên PostgreSQL (một database dùng một lần trong CI) và test trình duyệt.
  - **Docker image**: build đúng image Render dùng, khởi động nó và kiểm tra `/health`, trang chủ, container không chạy bằng root.
- **CD**: `render.yaml` đặt `autoDeployTrigger: checksPass`, nên Render chỉ deploy commit mới trên `main` **sau khi cả hai
  job CI đều qua**. CI đỏ thì trang đang chạy giữ nguyên bản cũ.
- Kiểm tra trên Render: **Settings → Build & Deploy → Auto-Deploy** phải là *After CI Checks Pass*. Blueprint tự đồng bộ
  thiết lập này sau lần đẩy `render.yaml` mới lên `main`; nếu chưa, chọn tay.
- Deploy tay khi cần: **Manual Deploy → Deploy latest commit** trên trang dịch vụ.

## Chạy image Docker trên máy

```bash
docker build -t travelmate travelmate
docker run --rm -p 8000:8000 --env-file travelmate/.env travelmate
```

Mở <http://127.0.0.1:8000>. Image không chứa `.env`, file SQLite hay thư mục test (`travelmate/.dockerignore`).

## Trước khi mở cho mọi người

- Đọc lại [Điều khoản sử dụng](../travelmate/frontend/travelmate-v2/site.js) và Chính sách bảo mật (cùng file),
  sửa cho đúng đơn vị vận hành của bạn. Hai trang này được viết theo đúng những gì mã nguồn đang làm, nhưng
  không thay cho tư vấn pháp lý.
- Phần Guardrails (lọc nội dung, chống prompt injection) chưa làm; Trợ lý AI có thể trả lời sai hoặc lạc đề.
