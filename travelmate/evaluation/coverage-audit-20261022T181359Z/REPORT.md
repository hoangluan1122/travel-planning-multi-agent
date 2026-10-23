# Báo cáo kiểm tra Place Agent trên phạm vi Việt Nam

Thời điểm UTC: 2026-10-22T18:17:20.220359+00:00

## Phạm vi và cách đọc kết quả

- Danh mục: 97 khu vực kiểm tra cục bộ qua API; đây KHÔNG phải kiểm thử POI mạng thật của 97 vùng.
- Dữ liệu thật: 40/40 ca chạy FastAPI → agent → HTTP thật; không mock dữ liệu nguồn, không gọi Gemini.
- Bộ ca có một điểm đại diện cho mỗi tỉnh/thành trong danh mục 34, thêm 6 khu du lịch; loại lưu trú/ăn uống/tham quan được luân phiên, không phải đủ ba loại cho mỗi nơi.
- Với địa danh trùng, chỉ chọn khi có đúng một tên khớp trong polygon tỉnh tham chiếu. Những lựa chọn khác được giữ ở needs_manual_choice, không chọn đại để làm đẹp tỷ lệ.
- usable_sourced_records nghĩa là đúng phạm vi kiểm tra, có bản ghi hợp schema và bằng chứng nguồn. KHÔNG xác nhận cơ sở có thật đang mở, giá/phòng trống, hoặc dữ liệu nguồn chính xác hoàn toàn.
- geographic_mismatch: tọa độ mà hệ thống tự nhận nằm ngoài tỉnh tham chiếu dự kiến; phải xem lại phân giải địa danh.
- Chỉ đánh giá theo ranh giới tham chiếu có phiên bản, có thể có sai số; không xác nhận pháp lý địa giới.
- Dữ liệu POI thiếu không chứng minh ngoài thực tế không có địa điểm; không có cam kết bao phủ mọi POI Việt Nam.
- Giới hạn: tối đa 60 request Photon, 45 request geocoding; giãn 2,5 giây; dừng nếu 403/429. Dừng do: không.

## Tổng hợp

| Kết quả | Số ca |
|---|---:|
| geographic_mismatch | 2 |
| needs_manual_choice | 8 |
| no_indexed_results | 1 |
| unresolved_locality | 1 |
| usable_sourced_records | 28 |
| Chưa chạy | 0 |

## Chi tiết dữ liệu thật

| STT | Tỉnh tham chiếu | Điểm thử | Loại | Kết quả | Bản ghi | Giây |
|---:|---|---|---|---|---:|---:|
| 1 | Hà Nội | Hà Nội | hotel | usable_sourced_records | 5 | 6.58 |
| 2 | Cao Bằng | Cao Bằng | restaurant | usable_sourced_records | 5 | 3.67 |
| 3 | Tuyên Quang | Đồng Văn | attraction | needs_manual_choice | 0 | 2.22 |
| 4 | Lào Cai | Sa Pa | hotel | usable_sourced_records | 5 | 5.2 |
| 5 | Điện Biên | Điện Biên Phủ | restaurant | usable_sourced_records | 5 | 5.77 |
| 6 | Lai Châu | Lai Châu | attraction | usable_sourced_records | 5 | 4.25 |
| 7 | Sơn La | Mộc Châu | hotel | usable_sourced_records | 5 | 5.2 |
| 8 | Thái Nguyên | Bắc Kạn | restaurant | usable_sourced_records | 4 | 4.83 |
| 9 | Lạng Sơn | Lạng Sơn | attraction | usable_sourced_records | 1 | 6.69 |
| 10 | Quảng Ninh | Hạ Long | hotel | usable_sourced_records | 5 | 4.66 |
| 11 | Phú Thọ | Tam Đảo | restaurant | no_indexed_results | 0 | 3.98 |
| 12 | Bắc Ninh | Bắc Giang | attraction | usable_sourced_records | 5 | 5.8 |
| 13 | Hải Phòng | Cát Bà | hotel | usable_sourced_records | 5 | 10.88 |
| 14 | Hưng Yên | Thái Bình | restaurant | usable_sourced_records | 5 | 6.91 |
| 15 | Ninh Bình | Tràng An | attraction | geographic_mismatch | 0 | 3.72 |
| 16 | Thanh Hóa | Sầm Sơn | hotel | geographic_mismatch | 5 | 5.81 |
| 17 | Nghệ An | Cửa Lò | restaurant | usable_sourced_records | 2 | 5.33 |
| 18 | Hà Tĩnh | Thiên Cầm | attraction | usable_sourced_records | 1 | 5.2 |
| 19 | Quảng Trị | Phong Nha | hotel | usable_sourced_records | 5 | 4.0 |
| 20 | Huế | Huế | restaurant | usable_sourced_records | 5 | 7.3 |
| 21 | Đà Nẵng | Hội An | attraction | needs_manual_choice | 0 | 0.86 |
| 22 | Quảng Ngãi | Lý Sơn | hotel | usable_sourced_records | 5 | 6.7 |
| 23 | Khánh Hòa | Nha Trang | restaurant | usable_sourced_records | 5 | 3.81 |
| 24 | Gia Lai | Quy Nhơn | attraction | usable_sourced_records | 5 | 4.91 |
| 25 | Đắk Lắk | Tuy Hòa | hotel | usable_sourced_records | 5 | 7.66 |
| 26 | Lâm Đồng | Đà Lạt | restaurant | needs_manual_choice | 0 | 0.88 |
| 27 | Tây Ninh | Tây Ninh | attraction | usable_sourced_records | 5 | 5.77 |
| 28 | Đồng Nai | Đồng Xoài | hotel | usable_sourced_records | 4 | 5.48 |
| 29 | Hồ Chí Minh | Vũng Tàu | restaurant | usable_sourced_records | 5 | 4.05 |
| 30 | Vĩnh Long | Bến Tre | attraction | usable_sourced_records | 5 | 6.97 |
| 31 | Đồng Tháp | Mỹ Tho | hotel | needs_manual_choice | 0 | 0.84 |
| 32 | An Giang | Phú Quốc | restaurant | needs_manual_choice | 0 | 2.53 |
| 33 | Cần Thơ | Sóc Trăng | attraction | needs_manual_choice | 0 | 2.53 |
| 34 | Cà Mau | Bạc Liêu | hotel | usable_sourced_records | 4 | 5.95 |
| 35 | Đà Nẵng | Bà Nà Hills | restaurant | needs_manual_choice | 0 | 5.56 |
| 36 | Lào Cai | Fansipan | attraction | needs_manual_choice | 0 | 4.98 |
| 37 | Hồ Chí Minh | Côn Đảo | hotel | usable_sourced_records | 5 | 4.95 |
| 38 | Lâm Đồng | Mũi Né | restaurant | usable_sourced_records | 5 | 4.67 |
| 39 | Đà Nẵng | Thánh địa Mỹ Sơn | attraction | usable_sourced_records | 2 | 7.61 |
| 40 | Ninh Bình | Vườn quốc gia Cúc Phương | hotel | unresolved_locality | 0 | 4.83 |

## Bằng chứng

- api/: phản hồi ban đầu và cuối của từng lượt, có URL và thời điểm lấy nguồn.
- network/: nội dung HTTP thực nhận; network-log.json ghi URL, status, SHA-256, số byte và thời gian.
- results.json và cases.csv: kết quả máy đọc được, giữ cả ca lỗi/không phân giải được.
- Kiểm tra danh mục có dấu/không dấu, ID được chọn và geometry được thực hiện riêng; không dùng nguồn giả làm live.

Nguồn công cộng có giới hạn sử dụng: [Photon demo policy](https://github.com/komoot/photon#demo-server). Muốn kiểm thử quét diện rộng/lặp lại cần endpoint riêng hoặc có quota phù hợp.
