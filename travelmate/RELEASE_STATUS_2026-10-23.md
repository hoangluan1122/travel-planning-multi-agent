# Trạng thái bản mã ngày 23/10/2026 (UTC+7)

## Phạm vi mã nguồn

Phiên bản phát triển TravelMate gồm backend FastAPI, agent và công cụ chuyên trách,
giao diện thử nghiệm, kiểm thử tự động và bằng chứng truy vấn mạng thật.
Place Agent mặc định chạy workflow công cụ; tích hợp ADK/LLM là chế độ tùy chọn.
Các phiên kiểm thử Place dưới đây không gọi Gemini.

## Kiểm tra gần nhất

- Toàn bộ kiểm thử Python: **513 passed**, 1 cảnh báo deprecation của TestClient.
- Ruff trên các tệp sửa trong lượt khắc phục địa danh: đạt.
- Kiểm tra trình duyệt bằng Playwright: đạt thao tác mở rộng bán kính có xác nhận,
  giữ đúng ID địa danh, nhãn đỉnh núi/trạm cáp treo, xóa lựa chọn cũ,
  màn hình điện thoại 390 px và không có lỗi JavaScript.
  Đây là kiểm tra giao diện dùng phản hồi đã ghi, không tính thành truy vấn mạng thật.
- Danh mục trước đó: 97/97 khu vực tham chiếu đạt kiểm tra API cục bộ
  (34 mục tham chiếu mới và 63 mục lịch sử).

## Sửa lỗi Place Agent

- Đối chiếu GeoNames với Photon ngay cả khi có một khu dân cư khớp tên duy nhất;
  yêu cầu xác nhận khi có nhiều thực thể hoặc nguồn đối chiếu không truy cập được.
- Hỗ trợ địa danh vườn quốc gia, khu bảo tồn, đỉnh núi và trạm cáp treo theo loại;
  loại khách sạn, quầy thông tin và trạm xe buýt khỏi ứng viên làm tâm địa danh.
- Lọc nhiễu tìm kiếm theo tên và kiểm tra thông tin tỉnh/thành người dùng cung cấp.
- Chuẩn hóa ký tự Ð/ð trong tên nguồn về cùng dạng với Đ/đ của tiếng Việt.
- Ghi rõ điểm nguồn là tâm hình học; không coi đó là cửa vào khu du lịch.
- Trả `applied_radius_m` và `suggested_radius_m`; giao diện chỉ chạy lại với
  bán kính rộng hơn sau khi người dùng bấm nút.

## Bằng chứng dữ liệu thật sau sửa

Thư mục `evaluation/fix-verification-20261022T182826Z/` lưu 15 lượt thử:
Tam Đảo, Cúc Phương, Đà Lạt, Bà Nà Hills, Fansipan, mỗi nơi thử lưu trú,
ăn uống và tham quan. Kịch bản chọn ID địa danh tường minh theo thực thể đã quan sát
ở nguồn; không tự chọn ID đầu tiên hoặc đưa bản ghi mẫu vào ứng dụng.

- **14/15 lượt** có bản ghi đủ kiểm tra nguồn trong bán kính **5 km**.
- Lượt khách sạn quanh trạm cáp treo trên Fansipan trả `no_results` trong 5 km.
  Kết quả rỗng này được giữ nguyên, không chuyển thành pass.
- Lượt kiểm tra bổ sung có yêu cầu **10 km** trả 5 bản ghi khách sạn:
  `evaluation/fix-verification-20261022T183050Z/`.
- Các thư mục có phản hồi API, URL nguồn, thời gian lấy, bytes HTTP và SHA-256.

## Phần cần tiếp tục

- Chưa xác minh hết mọi địa điểm Việt Nam. Bộ test đạt toàn bộ không chứng minh
  nguồn có đủ khách sạn/nhà hàng/điểm tham quan ở mọi nơi.
- Tràng An: đã chặn tự nhận sai khu dân cư ở tỉnh khác; vẫn cần rà soát khả năng
  tìm chính xác quần thể du lịch và nguồn bổ sung thay vì coi công viên trùng tên
  là toàn bộ khu danh thắng.
- Sầm Sơn: điểm nguồn sát ranh giới tham chiếu, cần kiểm tra chất lượng geometry;
  không nới polygon chỉ để làm kiểm thử đạt.
- 40 ca khảo sát ban đầu nằm trong
  `evaluation/coverage-audit-20261022T181359Z/REVIEW.md`; chưa chạy lại đủ 40 ca sau
  bản sửa. Các lượt lỗi/hạn chế vẫn được giữ trong bằng chứng.
- Giá, phòng trống, ảnh được cấp quyền và tình trạng cơ sở đang hoạt động chưa
  được xác minh. Ranh giới tham chiếu có nguồn và điều kiện sử dụng riêng trong
  `app/data/README.md`.

Không công bố trạng thái hoàn chỉnh 100% cho mọi điểm đến.
