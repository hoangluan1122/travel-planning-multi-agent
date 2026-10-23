# Place Agent — tìm trên phạm vi Việt Nam

## Sử dụng

Chạy `.\start-live-place.ps1` tại thư mục travelmate rồi mở http://127.0.0.1:8001/.

1. **Tự nhận diện:** nhập tên. Tên tỉnh/thành khớp danh mục sẽ yêu cầu xác nhận
   phạm vi; địa danh cụ thể được phân giải qua GeoNames/Open-Meteo hoặc Photon.
2. **Quanh địa danh:** tìm trong bán kính 250 m–10 km, ví dụ Sa Pa, Cát Bà, Vĩnh Yên.
   Tọa độ trung tâm được ghi trong resolved_location, không giả làm tọa độ POI.
3. **Trong tỉnh/thành hoặc khu vực cũ:** chọn từ danh mục hoặc nhập tên. Xác nhận
   đúng bản ranh giới. Không sử dụng bán kính; POI được lọc theo polygon tham chiếu.
4. **Cả Việt Nam:** lấy tập ứng viên giới hạn từ nhiều ô không gian, kiểm tra quốc
   gia VN và thuộc hợp của các polygon tỉnh/thành trong bộ tham chiếu.

Chọn lưu trú, ăn uống hoặc tham quan; để trống từ khóa lần đầu. Có thể lọc bằng tên
địa điểm, đổi số bản ghi mỗi trang, chuyển trang, xem nguồn và tải JSON.

### Trường hợp Vĩnh Phúc

Nhập Vĩnh Phúc → chọn `Vinh Phuc (khu vực cũ, ranh giới 2020)` → chạy lại.
Không còn chỉ gợi ý các khu dân cư trùng tên ở Gia Lai/Bắc Ninh/Hà Tĩnh.
Đây là phạm vi địa lý lịch sử, không tuyên bố là đơn vị hành chính hiện hành.
Không tự thay Vĩnh Phúc bằng toàn bộ Phú Thọ. Có thể chọn bản tham chiếu Phú Thọ
nếu người dùng thật sự muốn tìm trên phạm vi rộng hơn đó.

Với Đà Nẵng/Hà Nội/Cà Mau…, danh mục có thể có cả ranh giới mới và cũ mang cùng tên.
Chúng không nhất thiết trùng phạm vi. Nếu chỉ muốn gần trung tâm thành phố, chọn
**Quanh địa danh**, không chọn tìm toàn tỉnh/thành.

## Bao phủ nghĩa là gì?

- Có danh mục **34 tỉnh/thành** từ snapshot GIS 2026 và **63 khu vực lịch sử** từ
  snapshot 2020, tra tên không dấu và có dấu, ID/phiên bản rõ ràng.
- Hỗ trợ tìm địa danh cụ thể ở Việt Nam, có nguồn phân giải dự phòng và không chọn
  đại khi trùng tên. Địa danh không có trong nguồn vẫn có thể chưa phân giải được.
- POI lấy từ Photon/OSM lúc truy vấn, có cache tối đa 5 phút, không dùng dữ liệu mẫu.
- **Không có nghĩa đã thu thập hay xác minh 100% địa điểm Việt Nam.** Nguồn cộng đồng
  và chỉ mục có thể thiếu, không cập nhật, gắn tên/tag chưa đúng hoặc thiếu địa chỉ.
- Ranh giới là tham chiếu có phiên bản, có đơn giản hóa; không dùng thay dữ liệu pháp
  lý/cadastral hoặc xác minh địa chỉ hành chính hiện hành. Điểm sát ranh/ven biển
  có thể bị ảnh hưởng bởi sai số của dữ liệu.

## Tìm vùng khác tìm quanh một điểm

Tìm vùng chia bbox tỉnh thành 2×2 ô (cả nước 2×3 ô), tối đa 50 ứng viên/ô. Sau đó
lọc từng tọa độ theo polygon thật và loại trùng. Bbox chỉ giúp giảm phạm vi truy vấn;
không được coi là ranh giới. Polygon có hỗ trợ MultiPolygon và lỗ bên trong.

Các ô có thể chồng kết quả; ID và dấu vân tay tên/địa chỉ/tọa độ được loại trùng.
Tìm tỉnh sắp xếp theo khoảng cách tới điểm tham chiếu hình học; tìm cả nước xen kẽ
các nhóm ô để không chỉ hiện địa điểm gần tâm quốc gia. Đây không phải xếp hạng chất lượng.
Từ khóa dùng một truy vấn bbox toàn vùng, vẫn lọc polygon. Nếu bỏ từ khóa để mở rộng,
trả partial và cảnh báo.

Giới hạn: tối đa 200 ứng viên trước lọc cho tỉnh, 300 cho cả nước khi không có từ
khóa; thực tế có thể ít hơn. Phân trang chỉ duyệt tập ứng viên đã lấy, không có
cơ chế “trang tiếp” để quét hết chỉ mục. candidate_count KHÔNG phải tổng số cơ sở.
retrieval_exhaustive luôn false. Không thiết kế thành bộ cào hàng loạt public Photon.

Nếu một ô lỗi nhưng có bản ghi ở các ô khác: partial, coverage_partial=true. Nếu
không có bản ghi và có ô lỗi: source_error, không suy ra không có địa điểm.

## API

GET `/api/v1/places/regions`: 97 mục có ID, phiên bản, historical, bbox, source và
attribution. Không xuất geometry lớn hoặc các POI giả lập.

POST `/api/v1/places/live`:

```json
{"destination":"Vĩnh Phúc","search_scope":"area","category":"hotel","limit":5}
```

Nhận needs_location với location_options; gửi lại cùng request và location_id đã
chọn. ID phải thuộc các lựa chọn của chính tên và chế độ đó; không tái dùng ID của
tỉnh khác. Phạm vi hợp lệ: auto / nearby / area / country.

```json
{"destination":"Việt Nam","search_scope":"country","category":"attraction","limit":10,"offset":0}
```

Đầu ra kế thừa schema trong LIVE_PLACE_AGENT.md, thêm:

- resolved_location.scope: nearby / area / country.
- boundary_version, historical, bbox, attribution cho khu vực.
- place_metadata.spatial_filter: radius hoặc reference_polygon.
- coverage_partial: có ô nguồn bị lỗi.
- retrieval_exhaustive=false: không được khẳng định đã lấy đủ POI trong vùng.

Chế độ mặc định vẫn là tool_workflow (không gọi LLM); adk_llm là tùy chọn có khóa
Gemini. Provider khóa phạm vi và kiểm tra toàn bộ output với evidence store. Chưa
gọi Gemini thật ở lần kiểm chứng này; không gọi workflow xác định là phiên LLM.

## Kiểm chứng

299 unit/integration tests đạt sau nâng cấp, gồm tất cả tên trong danh mục 34,
legacy Vĩnh Phúc, từ chối ID tỉnh khác, lọc polygon/hole/biên, cache, lỗi từng ô,
quốc gia, nguồn dự phòng, schema API và bộ hồi quy agent trước đó.

Đã chạy mạng thật ngày 23/10/2026 UTC+7, 5 bản ghi/lượt:

| Phạm vi | Loại | Ứng viên hợp lệ của lần truy vấn |
| --- | --- | --- |
| Vĩnh Phúc, ranh giới 2020 | Lưu trú | 19 |
| Đà Nẵng, bộ ranh giới 2026 | Tham quan | 54 |
| Cà Mau, bộ ranh giới 2026 | Ăn uống | 34 |
| Việt Nam, hợp polygon 34 tỉnh/thành | Lưu trú | 130 |

Số liệu là ảnh chụp truy vấn, không là thống kê toàn vùng. JSON và ảnh UI trong
evaluation/place-national/. Đã kiểm tra trên trình duyệt: nhập Vĩnh Phúc → chọn
đúng khu vực cũ → nhận 5 cards có nguồn; viewport desktop/mobile, không lỗi JS,
không tràn ngang ở 390 px. Không kiểm thử mạng thật tất cả 97 phạm vi.

Chạy kiểm thử offline bằng `uv run --no-sync pytest -q`.
Probe tùy chọn: `uv run --no-sync python scripts/verify_national_place.py` khi server
8001 đã chạy; không chạy lặp liên tục hoặc trong CI mỗi commit.

## Nguồn, phiên bản và triển khai

Boundary catalog 3,6 MB được nhập qua scripts/import_vietnam_boundaries.py từ URL
commit cố định; ghi SHA-256 và acquisition timestamp. Tải một lần, không tải lại
toàn bộ polygon trong mỗi request. Đây là dữ liệu địa lý tham chiếu, không là seed POI.

- Bộ 34: [vietnamese-provinces-database](https://github.com/thanglequoc/vietnamese-provinces-database),
  commit 8b78ba5118715e1fa81769286724db79346abf52. GIS có nguồn Bando.com.vn; README
  yêu cầu kiểm tra điều khoản Bando trước khi sử dụng. Không coi MIT phần mềm là
  giấy phép riêng không hạn chế cho GIS. Cần rà soát quyền trước khi public/thương mại.
- Bộ 63: Government of Viet Nam/HDX qua [geoBoundaries gbHumanitarian](https://www.geoboundaries.org/api/current/gbHumanitarian/VNM/ADM1/),
  phiên bản 2020, CC BY 3.0 IGO, hình học được đơn giản hóa upstream.
- POI: [Photon](https://github.com/komoot/photon) / OpenStreetMap, quy thuộc ODbL trong
  mỗi bản ghi. include categories phải là danh sách cách bằng dấu phẩy để OR, không
  lặp include vì lặp có nghĩa AND.

Thông tin nguồn/giấy phép đầy đủ: app/data/README.md. Snapshot không tự cập nhật khi
có đổi địa giới; phải import bản mới có kiểm tra/migration ID và chạy lại kiểm thử.

Trước khi vận hành nhiều người dùng: managed/self-hosted Photon, nguồn có điều khoản
phù hợp, auth/quota, database/cache bền vững, cập nhật dữ liệu, giám sát và kiểm thử tải.
Chưa hoàn tất giá theo ngày, phòng trống, ảnh được cấp quyền hay đặt phòng. Những
phần đó cần nguồn riêng; không thể suy ra từ một polygon hoặc tên địa điểm.
