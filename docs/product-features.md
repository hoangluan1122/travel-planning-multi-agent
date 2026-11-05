# Nghiệp vụ sản phẩm TravelMate

Tất cả màn hình trong thiết kế đã nối với backend thật. Không còn màn hình “đang chờ kết nối”.

| Màn hình | Đường dẫn | Chức năng |
|---|---|---|
| Đăng ký / Đăng nhập | `?view=signup`, `?view=login` | Tạo tài khoản, đăng nhập; phiên lưu trên trình duyệt |
| Quên mật khẩu | `?view=forgot` | Tạo link đặt lại (30 phút), đặt mật khẩu mới qua `?view=forgot&reset=…` |
| Tài khoản | `?view=profile` | Sửa tên, sở thích (điền sẵn khi tạo chuyến), đổi mật khẩu, xem đánh giá của mình, đăng xuất, xoá tài khoản |
| Chuyến đi của tôi | `?view=saved` | Danh sách chuyến đã lưu: mở, đổi tên, chỉnh sửa, xoá |
| Lịch trình | `?view=plan` | Lịch tạo khi đã đăng nhập được tự lưu vào tài khoản; chưa lưu thì có nút “Lưu vào tài khoản” |
| Chỉnh sửa lịch trình | `?view=edit&id=…` | Đổi giờ, bỏ hoạt động, thêm địa điểm yêu thích, đổi tên; chi phí được tính lại |
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
  - Chi phí tính lại bằng Budget Agent. Phần tự kiểm tra của AI được gỡ vì lịch đã sửa tay.
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

## Bảo mật

- Mật khẩu băm bằng scrypt có salt riêng. Token phiên và token đặt lại là chuỗi ngẫu nhiên 32 byte;
  trong DB chỉ lưu SHA-256 của chúng.
- Mọi truy vấn SQL dùng tham số. Mọi nội dung người dùng được escape khi hiển thị.
- Dữ liệu nằm trong `travelmate.sqlite3`, đã có trong `.gitignore`.

## Kiểm thử (05/11/2026)

- 731 test đều qua (thêm 18 test nghiệp vụ trong `tests/test_accounts.py`).
- Đã chạy thử trên trình duyệt (chế độ demo, database tạm):
  - Đăng ký tài khoản admin, tạo chuyến đi và tự lưu vào tài khoản.
  - Mở trang địa điểm từ lịch, ♡ yêu thích, viết đánh giá (chờ duyệt).
  - Sửa lịch: đổi giờ và tên, chi phí tính lại.
  - Duyệt đánh giá; xem tổng quan, danh sách người dùng và địa điểm quản trị.
  - Lưu sở thích; đăng xuất, đăng nhập sai rồi đúng.
  - Quên mật khẩu: link xuất hiện trong log.

## Giới hạn

- Chưa gửi email, chưa đăng nhập bằng Google/Facebook, chưa xác minh email.
- Phiên lưu trong `localStorage` của trình duyệt. Nếu đưa lên mạng, nên chuyển sang cookie
  HttpOnly và bật HTTPS.
- Địa điểm bị ẩn chưa bị loại khỏi lịch do AI lập; mới bị loại khỏi tìm kiếm, Trợ lý AI và yêu thích.
- Một tiến trình, một file SQLite: phù hợp demo, chưa dành cho nhiều máy chủ.
