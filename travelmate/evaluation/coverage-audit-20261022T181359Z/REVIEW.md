# Kết luận kiểm thử Place Agent — 23/10/2026 (UTC+7)

## Kết luận sử dụng

**Đã có dữ liệu mạng thật cho nhiều điểm đến, nhưng chưa đủ cơ sở gọi Place Agent
là hoàn chỉnh cho mọi địa danh/khu du lịch Việt Nam.** Có lỗi phân giải sai địa danh
và loại mất một số loại điểm du lịch. Đây là kết quả kiểm tra, chưa triển khai sửa.

## Phạm vi đã kiểm tra

| Lớp kiểm tra | Kết quả | Ý nghĩa chính xác |
|---|---:|---|
| Unit/integration toàn repo sau khi bổ sung kiểm tra | 495 passed | Logic theo bộ ca, không là xác minh dữ liệu thực tế |
| Danh mục ranh giới qua API | 97/97 đạt | 34 mục tham chiếu mới + 63 lịch sử; kiểm tra cục bộ, không gọi POI mạng thật ở mọi vùng |
| Ca mạng thật | 40/40 đã chạy | Một điểm đại diện cho mỗi mục trong danh mục 34 và 6 điểm du lịch bổ sung |
| Loại được thử | 14 lưu trú / 13 ăn uống / 13 tham quan | Luân phiên theo điểm đến, KHÔNG thử đủ ba loại tại từng nơi |
| Lượt HTTP nguồn thật | 75 | 40 GeoNames/Open-Meteo + 35 Photon/OSM; có URL, timestamp, nội dung và SHA-256 |
| Bản ghi trả về | 128 | Tổng của các ca có kết quả, không phải danh bạ đầy đủ Việt Nam |

Chạy đúng FastAPI handlers → LivePlaceAgent → GeoPlaceService → HTTP nguồn thật.
API được gọi in-process qua ASGI; không dùng MockTransport/mẫu POI, không gọi Gemini.
Một lượt harness ban đầu lỗi giải nén đã được đánh dấu INVALID_RUN và loại khỏi số
liệu; kết luận này chỉ dùng thư mục coverage-audit-20261022T181359Z.

## Kết quả 40 ca

| Nhóm | Số ca | Diễn giải |
|---|---:|---|
| Có bản ghi đạt kiểm tra kỹ thuật nguồn/phạm vi | 28 | Không khẳng định đang mở, còn phòng, giá đúng hoặc chất lượng thực tế |
| Chờ chọn địa danh cụ thể | 8 | Cơ chế an toàn; không phải 8 lỗi nguồn. Chưa kiểm tra POI sau lựa chọn thủ công cho các ca này |
| Nguồn trả rỗng trong phạm vi thử | 1 | Tam Đảo / ăn uống / bán kính 5 km |
| Không phân giải được địa danh | 1 | Vườn quốc gia Cúc Phương |
| Không khớp polygon tỉnh tham chiếu | 2 | Tràng An là sai mục tiêu rõ; Sầm Sơn cần xét sai số ranh giới |

### Những nơi đã có bản ghi nguồn dùng được ở mức kỹ thuật

Hà Nội, Cao Bằng, Sa Pa, Điện Biên Phủ, Lai Châu, Mộc Châu, Bắc Kạn, Lạng Sơn,
Hạ Long, Bắc Giang, Cát Bà, Thái Bình, Cửa Lò, Thiên Cầm, Phong Nha, Huế, Lý Sơn,
Nha Trang, Quy Nhơn, Tuy Hòa, Tây Ninh, Đồng Xoài, Vũng Tàu, Bến Tre, Bạc Liêu,
Côn Đảo, Mũi Né và Thánh địa Mỹ Sơn.

### Những nơi cần xác nhận lựa chọn trong lượt thử

Đồng Văn, Hội An, Đà Lạt, Mỹ Tho, Phú Quốc, Sóc Trăng, Bà Nà Hills và Fansipan.
Không chọn đại ứng viên đầu tiên để tăng tỷ lệ đạt. Đây là giới hạn của kết quả
audit: chúng chưa được đánh giá là có POI dùng được sau thao tác chọn.

Ví dụ: Hội An có nhiều nơi cùng tên trong phạm vi rộng; Fansipan trả cả trạm cáp
treo, đỉnh núi, nhà hàng/khách sạn trùng tên. Cần xác định người dùng muốn thực thể
nào. Tên Đà Lạt trong GeoNames có ký tự Ð (U+00D0), khác Đ (U+0110); chuẩn hóa hiện
tại chưa xử lý tốt khác biệt này, làm giảm khả năng ghép tên tự động.

## Các vấn đề cần ưu tiên

### 1. Cao — Tràng An bị tự nhận sang Bắc Ninh

- Thử: destination=Tràng An, category=attraction, nearby, radius=5000.
- Agent tự chọn geonames:9871516, tọa độ 21.20106, 106.20681; nguồn ghi Bắc Ninh.
- Mục tiêu của ca là khu du lịch Tràng An tại Ninh Bình. Đây là sai ý định địa lý,
  không phải bằng chứng Ninh Bình không có điểm tham quan.
- Bằng chứng: [api/15-final.json](api/15-final.json).
- Mã liên quan: app/geo_places.py:245 và :258. Nguồn dự phòng chỉ được hỏi khi danh
  sách đầu rỗng; một tên khu dân cư khớp duy nhất có thể được chấp nhận mà không
  so sánh với thực thể du lịch nổi tiếng ở nguồn khác.
- Hướng sửa: phân giải đa nguồn có loại thực thể, ràng buộc khu vực/ý định du lịch,
  trả lựa chọn khi có xung đột; không tự chấp nhận chỉ vì tên khớp.

### 2. Cao — Có dữ liệu Cúc Phương nhưng agent loại mất

- Nguồn Photon trả hai feature tên Vườn quốc gia Cúc Phương:
  boundary:national_park và leisure:nature_reserve.
- Bộ lọc địa danh dự phòng chỉ cho osm_key trong place/tourism/natural, vì vậy loại
  cả hai. Đây không phải trường hợp nguồn hoàn toàn không có dữ liệu.
- Bằng chứng: [api/40-final.json](api/40-final.json), HTTP nguồn số 75 trong
  [network-log.json](network-log.json), body nén gốc network/075.bin.
- Mã liên quan: app/geo_places.py:285. Bộ tag POI tham quan cũng cần rà soát để
  hỗ trợ công viên quốc gia, khu bảo tồn, trạm cáp treo… theo vai trò thích hợp.
- Hướng sửa: bổ sung các loại thực thể và kiểm tra tọa độ đại diện/phạm vi. Với
  một khu du lịch lớn, phải phân biệt tâm hình học, cửa vào và khu dịch vụ.

### 3. Trung bình — Tam Đảo chưa có nhà hàng trong phạm vi thử

- Agent chọn geonames:1567178, 21.39324, 105.61441, rồi nhận no_results ở bán kính 5 km.
- Bằng chứng: [api/11-final.json](api/11-final.json).
- Chưa đủ chứng cứ để kết luận nguyên nhân là thiếu chỉ mục hay chọn tâm hành chính
  thay vì khu du lịch. Cần đối chiếu vị trí thị trấn/khu du lịch và hỏi lại người dùng;
  không được suy ra Tam Đảo không có nhà hàng.

### 4. Cần đối chiếu — Sầm Sơn sát ranh giới tham chiếu

- API có 5 khách sạn, tọa độ tham chiếu 19.73333, 105.9 và nguồn ghi Thanh Hóa.
- Kiểm tra polygon tham chiếu hiện tại đánh dấu điểm ngoài vùng. Tính khoảng cách
  phẳng cục bộ tới đoạn ranh gần nhất cho kết quả khoảng 142,4 m.
- Bằng chứng: [api/16-final.json](api/16-final.json).
- Không gộp ca này với lỗi chọn nhầm tỉnh như Tràng An. Cần kiểm tra độ chính xác
  vùng ven biển/ranh đơn giản hóa và tọa độ nguồn trước khi quy lỗi cho agent.
- Không tự nới ranh 2 km để biến kiểm thử thành đạt; giữ nguyên kết quả kiểm tra
  gốc và ghi rõ phần cần thẩm định.

## Giới hạn của kết luận

- Ranh giới tỉnh là oracle địa lý tham chiếu, không phải xác nhận pháp lý. Một tên
  và tọa độ trong đúng tỉnh vẫn chưa chứng minh đúng điểm du lịch người dùng muốn.
- Các ca usable_sourced_records chỉ kiểm tra schema, tên/ID, nguồn từng trường,
  tuổi dữ liệu, khoảng cách và tỉnh tham chiếu. Không đi thực địa hoặc xác minh
  độc lập tất cả thông tin mà OSM công bố. Nguồn có thể có tag/tên sai.
- Chưa kiểm thử mọi địa điểm Việt Nam, mọi loại tại từng tỉnh, giá, ảnh được cấp
  quyền, phòng trống, giờ hoạt động hiện tại, tải lớn hay LLM thật.
- Public Photon chỉ cho mức sử dụng hợp lý. Lượt này giãn 2,5 giây, có hard cap và
  circuit breaker, không song song hàng loạt. Quét toàn bộ/tái chạy thường xuyên
  cần endpoint riêng hoặc dịch vụ có quota phù hợp, không tiếp tục quét demo public.

## File để đọc và sử dụng

- [REPORT.md](REPORT.md): bảng chi tiết đủ 40 ca, trạng thái gốc.
- [cases.csv](cases.csv): mở bằng Excel để lọc theo tỉnh/trạng thái.
- [results.json](results.json): toàn bộ kết quả, có cả ca chưa có dữ liệu.
- [api/](api/): phản hồi ban đầu/cuối, ID yêu cầu, URL nguồn và thời điểm lấy.
- [network-log.json](network-log.json): URL, HTTP status, hash, content-encoding.
- network/*.bin là bytes HTTP gốc (có thể nén gzip), không phải văn bản UTF-8 trực tiếp.

**Ưu tiên tiếp theo:** sửa phân giải thực thể du lịch và kiểm tra chéo địa danh,
bổ sung loại công viên/khu bảo tồn, rồi chạy hồi quy chính các ca lỗi này trước khi
mở rộng khẳng định sản phẩm. Không cần tăng số dòng mã hay tăng số test để thay
thế việc xử lý các lỗi dữ liệu thực tế đã quan sát.
