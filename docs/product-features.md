# Nghiệp vụ sản phẩm TravelMate

Tất cả màn hình trong thiết kế đã nối với backend thật. Không còn màn hình “đang chờ kết nối”.

| Màn hình | Đường dẫn | Chức năng |
|---|---|---|
| Đăng ký / Đăng nhập | `?view=signup`, `?view=login` | Tạo tài khoản, đăng nhập; phiên lưu trên trình duyệt |
| Quên mật khẩu | `?view=forgot` | Tạo link đặt lại (30 phút), đặt mật khẩu mới qua `?view=forgot&reset=…` |
| Tài khoản | `?view=profile` | Sửa tên, sở thích (điền sẵn khi tạo chuyến), đổi mật khẩu, xem đánh giá của mình, đăng xuất, xoá tài khoản |
| Chuyến đi của tôi | `?view=saved` | Danh sách chuyến đã lưu: mở, đổi tên, chỉnh sửa, xoá |
| Lịch trình | `?view=plan` | Lịch tạo khi đã đăng nhập được tự lưu vào tài khoản; chưa lưu thì có nút “Lưu vào tài khoản”. Khung chi phí: tổng ước tính, đủ/sát/vượt ngân sách, biểu đồ theo khoản, nguồn giá, gợi ý tiết kiệm |
| Chỉnh sửa lịch trình | `?view=edit&id=…` | Đổi giờ, bỏ hoạt động, thêm địa điểm yêu thích, đổi tên, **dời cả chuyến sang ngày khác**, **xếp lại tự động**, **nhập chi phí lưu trú/ăn uống/di chuyển**, **đổi mức chi tiêu**; chi phí được tính lại và lịch được tự kiểm tra |
| Trợ lý AI | `?view=chat` | Hỏi nhiều việc trong một câu (“lên lịch và báo thời tiết”); khi đăng nhập, cuộc trò chuyện được lưu (mở lại, xoá) và lịch tạo trong chat tự vào “Chuyến đi của tôi” |
| Chi tiết địa điểm | `?view=place&id=…` | Ảnh, giá vé có nguồn, giờ mở cửa, bản đồ, ghi chú của quản trị, điểm và đánh giá TravelMate, ♡ yêu thích, báo cáo đánh giá |
| Viết đánh giá | `?view=review&id=…` | 1–5 sao và nội dung; sửa hoặc xoá đánh giá của mình |
| Yêu thích | `?view=favorites` | Địa điểm đã ♡, bỏ yêu thích |
| Quản trị · Tổng quan | `?view=admin` | Số liệu hệ thống và hoạt động gần đây (audit log) |
| Quản trị · Người dùng | `?view=admin-users` | Tìm, đổi quyền, khoá/mở khoá, cấp link đặt lại mật khẩu |
| Quản trị · Địa điểm | `?view=admin-places` | Ẩn/hiện địa điểm, ghi chú hiển thị cho người dùng (ví dụ “đang trùng tu”) |
| Kiểm duyệt | `?view=moderation` | Duyệt/từ chối đánh giá mới; giữ lại hoặc ẩn đánh giá bị báo cáo, kèm ghi chú cho người viết |

## Quy tắc nghiệp vụ

- **Tài khoản:**
  - Email không trùng; mật khẩu 8–128 ký tự.
  - Sai mật khẩu và email không tồn tại cho cùng thông báo, cùng thời gian xử lý.
  - Đăng nhập, đăng ký và quên mật khẩu bị giới hạn 8 lần/15 phút cho mỗi IP và email.
  - Đổi mật khẩu thì đăng xuất các thiết bị khác. Đặt lại mật khẩu hoặc bị khoá thì đăng xuất mọi thiết bị.
- **Quản trị viên:**
  - Tài khoản đăng ký bằng `TRAVELMATE_ADMIN_EMAIL` là admin; admin có thể cấp quyền cho người khác.
  - Admin không tự hạ quyền hay tự khoá mình được.
- **Phiên đăng nhập mở khoá API:** người dùng đã đăng nhập không cần nhập `TRAVELMATE_API_TOKEN`.
- **Chuyến đi:**
  - Chỉ chủ tài khoản xem và sửa được.
  - Khi sửa, không đổi được ngày. Mỗi ngày cần ít nhất một hoạt động, giờ không chồng nhau, một địa
    điểm không lặp trong ngày.
  - Chỉ thêm được địa điểm của chuyến đó hoặc trong danh sách yêu thích.
  - Chi phí tính lại bằng Budget Agent, kể cả khi đổi mức chi tiêu.
- **Chi phí (Budget Agent):**
  - Tổng chuyến = vé tham quan có nguồn + lưu trú, ăn uống, đi lại theo bảng giá tham khảo
    (`app/data/cost_reference.json`) cho mức tiết kiệm / vừa phải / cao cấp. Mỗi số ghi nguồn.
  - Lưu trú tính theo phòng (2 người/phòng) × số đêm; ăn uống và đi lại theo người × số ngày.
    Đi trong ngày thì không tính lưu trú. Giá quán ăn trong lịch đã nằm trong khoản ăn uống, không cộng hai lần.
  - Kết luận so với ngân sách: **đủ** (cả mức cao vẫn vừa), **sát** (chỉ mức thấp vừa), **vượt**.
  - Khi sát hoặc vượt: gợi ý tiết kiệm kèm số tiền bớt được (hạ mức chi tiêu, chỉ hạ chỗ ở, bỏ một điểm
    có vé). Chỉ gợi ý thay bằng địa điểm mà nguồn ghi là miễn phí. Không gợi ý nào tự áp dụng.
  - Chi phí bạn tự nhập thay cho giá tham khảo của khoản đó.
  - Giá riêng cho 11 điểm đến: Huế, Hội An, Hà Nội, TP.HCM, Đà Nẵng, Nha Trang, Đà Lạt, Sa Pa, Phú Quốc,
    Hạ Long, Ninh Bình. Khoản nào thành phố chưa có số riêng, và mọi nơi khác, dùng **mức chung toàn
    quốc**; câu trả lời và bảng chi phí ghi rõ khoản nào dùng mức chung.
  - Vé tham quan có nguồn cho hơn 40 địa danh (Đại Nội, Văn Miếu, Dinh Độc Lập, Bà Nà, Fansipan, Tràng An,
    động Phong Nha, VinWonders…); nơi miễn phí ghi “miễn phí”.
  - Trợ lý AI trả lời “có đủ không”, “tốn bao nhiêu” và câu hỏi “nếu…”: giá phòng mỗi đêm
    (“khách sạn 500k/đêm”), số người, mức chi tiêu, ngân sách khác. Đây là tính thử, lịch đã lưu không đổi.
- **Địa điểm:** được ghi nhận khi xuất hiện trong tìm kiếm, lịch trình hoặc Trợ lý AI. Địa điểm bị ẩn
  không còn trong tìm kiếm, Trợ lý AI, yêu thích và trang chi tiết; quản trị viên vẫn xem được.
- **Đánh giá:**
  - Mỗi người một đánh giá cho mỗi địa điểm, 10–1000 ký tự.
  - Đánh giá mới hoặc vừa sửa ở trạng thái “Chờ duyệt” và chỉ người viết thấy. Duyệt xong mới công
    khai và tính vào điểm trung bình.
  - Không báo cáo được đánh giá của chính mình. Mỗi người báo cáo một đánh giá một lần.
  - Kiểm duyệt xong thì đóng các báo cáo liên quan.
- **Quên mật khẩu:** bản demo chưa có dịch vụ email. Link đặt lại được ghi vào log máy chủ, hoặc quản
  trị viên cấp trong trang Người dùng để gửi cho người dùng.

## Database: PostgreSQL hoặc SQLite

- **PostgreSQL** (khuyên dùng):
  1. Tạo database một lần: `psql -U postgres -c "CREATE DATABASE travelmate"`.
  2. Cài driver: `uv sync --extra postgres`.
  3. Đặt trong `.env`: `TRAVELMATE_DATABASE_URL=postgresql://postgres:<mật khẩu>@localhost:5432/travelmate`.

  Server tự tạo bảng khi khởi động. `/health` cho biết đang dùng `"database": "postgresql"`.
- **SQLite:** để trống `TRAVELMATE_DATABASE_URL` thì dùng file `TRAVELMATE_DB`
  (mặc định `travelmate.sqlite3`).
- Câu lệnh SQL viết một lần, chạy được trên cả hai (`app/memory/store.py`, lớp `Db`). Test nghiệp vụ chạy trên
  SQLite, và chạy cả trên PostgreSQL khi đặt `TRAVELMATE_TEST_DATABASE_URL` trỏ tới một database dùng
  riêng cho test. Bảng của database đó sẽ bị **xoá** trước mỗi test, nên đừng trỏ vào database thật.
- Chuỗi kết nối chứa mật khẩu: chỉ đặt trong `.env` (không commit), không bao giờ được ghi log hay trả về.

## Khi Gemini lỗi hoặc hết hạn mức

Lịch vẫn được tạo. Bộ xếp lịch theo luật (`app/agents/rule_scheduler.py`) làm thay phần AI: ưu tiên địa điểm
khớp mong muốn, có bữa trưa trong 10:30–14:30, ngày mưa tối đa một điểm ngoài trời, không lặp địa
điểm. Lịch có cảnh báo ghi rõ là xếp bằng luật, và phần tự kiểm tra ghi `scheduled_by: rules`.

## Tìm theo từ khoá

Tìm có phân biệt dấu tiếng Việt: “lăng” không còn ra “Làng…”, “chay” không ra “cháy”, “phở” không ra
“Phong Nha”. Ngoài kết quả của Photon, hệ thống còn:
- lọc danh sách địa điểm quanh khu vực (cả di tích trong 15 km với điểm tham quan) theo tên hoặc loại,
  ví dụ “lăng” khớp loại `tomb`;
- thử thêm từ tiếng Anh tương ứng (chay → vegetarian), vì nhiều tên trong OSM là tiếng Anh.

## Bảo mật

- Trên trình duyệt, phiên đăng nhập nằm trong cookie `HttpOnly`, `SameSite=Strict`; trang web không đọc
  được token. Mọi thao tác ghi bằng cookie phải kèm header `X-Requested-With: travelmate` (chống CSRF).
  Ứng dụng khác vẫn dùng `Authorization: Bearer`.
- Email đặt lại mật khẩu gửi qua SMTP khi đặt `TRAVELMATE_SMTP_*` (miễn phí với app password Gmail).
  Không cấu hình thì link nằm trong log máy chủ. Câu trả lời không tiết lộ email có tài khoản hay không.
- MCP qua HTTP bắt buộc `Authorization: Bearer <TRAVELMATE_API_TOKEN>`.
- Mật khẩu băm bằng scrypt có salt riêng. Token phiên và token đặt lại là chuỗi ngẫu nhiên 32 byte;
  trong DB chỉ lưu SHA-256 của chúng.
- Mọi truy vấn SQL dùng tham số. Mọi nội dung người dùng được escape khi hiển thị.

## Kiểm thử (05/11/2026)

- 747 test đều qua. Test nghiệp vụ chạy trên cả SQLite và PostgreSQL 18 (cụm tạm).
- `tests/test_ui_e2e.py`: test giao diện tự động trên trình duyệt thật (Edge qua Playwright), đi hết các
  luồng chính:
  - Admin và thành viên đăng ký. Token không còn nằm trong `localStorage`.
  - Tạo chuyến đi và tự lưu. Mở trang địa điểm, ♡, viết đánh giá.
  - Sửa lịch, thêm chi phí tự nhập.
  - Chat câu hỏi ghép, được hai chuyên gia trả lời; lịch sử chat được lưu.
  - Admin duyệt đánh giá; điểm 5/5 hiện trên trang địa điểm.

## Giới hạn còn lại

- Chưa đăng nhập bằng Google/Facebook, chưa xác minh email khi đăng ký.
- Bảng giá vé có nguồn mới có Huế và Hội An. Thêm thành phố cần tra và ghi nguồn từng giá.
- Dự báo thời tiết chỉ có cho khoảng 14 ngày tới.
- Hướng dẫn viên tìm theo từ trùng (chưa có embedding).
- Sửa lịch chưa nhờ AI lập lại một ngày; “Xếp lại tự động” dùng luật.
- Với SQLite: một tiến trình, một file, phù hợp demo. Chạy nhiều máy chủ thì dùng PostgreSQL.
