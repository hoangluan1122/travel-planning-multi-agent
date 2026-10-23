# Báo cáo kiểm tra Place Agent trên phạm vi Việt Nam

Thời điểm UTC: 2026-10-22T18:13:55.175264+00:00

## Phạm vi và cách đọc kết quả

- Danh mục: 97 khu vực kiểm tra cục bộ qua API; đây KHÔNG phải kiểm thử POI mạng thật của 97 vùng.
- Dữ liệu thật: 9/40 ca chạy FastAPI → agent → HTTP thật; không mock dữ liệu nguồn, không gọi Gemini.
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
| source_error | 9 |
| Chưa chạy | 31 |

## Chi tiết dữ liệu thật

| STT | Tỉnh tham chiếu | Điểm thử | Loại | Kết quả | Bản ghi | Giây |
|---:|---|---|---|---|---:|---:|
| 1 | Hà Nội | Hà Nội | hotel | source_error | 0 | 3.97 |
| 2 | Cao Bằng | Cao Bằng | restaurant | source_error | 0 | 4.66 |
| 3 | Tuyên Quang | Đồng Văn | attraction | source_error | 0 | 6.8 |
| 4 | Lào Cai | Sa Pa | hotel | source_error | 0 | 5.17 |
| 5 | Điện Biên | Điện Biên Phủ | restaurant | source_error | 0 | 3.58 |
| 6 | Lai Châu | Lai Châu | attraction | source_error | 0 | 5.08 |
| 7 | Sơn La | Mộc Châu | hotel | source_error | 0 | 4.88 |
| 8 | Thái Nguyên | Bắc Kạn | restaurant | source_error | 0 | 7.48 |
| 9 | Lạng Sơn | Lạng Sơn | attraction | source_error | 0 | 3.62 |

## Bằng chứng

- api/: phản hồi ban đầu và cuối của từng lượt, có URL và thời điểm lấy nguồn.
- network/: nội dung HTTP thực nhận; network-log.json ghi URL, status, SHA-256, số byte và thời gian.
- results.json và cases.csv: kết quả máy đọc được, giữ cả ca lỗi/không phân giải được.
- Kiểm tra danh mục có dấu/không dấu, ID được chọn và geometry được thực hiện riêng; không dùng nguồn giả làm live.

Nguồn công cộng có giới hạn sử dụng: [Photon demo policy](https://github.com/komoot/photon#demo-server). Muốn kiểm thử quét diện rộng/lặp lại cần endpoint riêng hoặc có quota phù hợp.
