# Place Agent — nguồn OSM không cần Maps key

Ngày cập nhật: 22/10/2026.

## Phần đã triển khai

- Provider OSM qua Overpass, cắm vào PlaceAssistant hiện có; vẫn giữ provider Google
  để có thể chọn bằng PLACE_PROVIDER=google.
- Tách xác định địa danh và tìm POI. Chỉ nhận city/town/village/suburb trong Việt Nam;
  không dùng tâm tỉnh như địa điểm du lịch. Không tự chọn khi có nhiều địa danh trùng tên.
- Trả location_options và needs_location; caller gửi location_id đã chọn trong lần kế tiếp.
  LLM không được sửa destination/location_id/radius hoặc tự chọn địa danh cho người dùng.
- Tìm hotel, restaurant, attraction trong bán kính 100–10000 m; mặc định 3000 m.
- ID ổn định theo loại OSM: osm:node/123, osm:way/123, osm:relation/123.
- Chuẩn hóa tên, địa chỉ từ addr tags, tọa độ, loại điểm, source_url, attribution,
  fetched_at và field_sources. Node là point; way/relation là geometry_center,
  không được coi tâm hình học là cổng vào.
- Dữ liệu có thì giữ opening_hours_raw, website_url, image_reference. Không tự
  diễn giải giờ đang mở, không tải ảnh hoặc khẳng định quyền sử dụng ảnh.
- Không có giá từ nguồn hiện tại: estimated_visit_cost_vnd=null. Không suy ra giá
  phòng/giá món ăn từ tên khách sạn/nhà hàng, không báo còn phòng.
- Gộp ID lặp; gộp thận trọng tên+địa chỉ+tọa độ gần như trùng. Không gộp hai chi
  nhánh ở địa điểm khác. Sắp xếp theo khoảng cách trong tập ứng viên giới hạn.
- Cache cùng truy vấn 10 phút (tối đa 128 entry), serialize yêu cầu trong cùng
  instance, cách nhau ít nhất một giây, cooldown 30 giây sau 429/406. Không tự retry
  hoặc đổi máy chủ để vượt hạn mức. Giữ fetched_at của lần lấy dữ liệu gốc khi cache hit.

## Cấu hình và chạy

### Chạy riêng tool, không cần bất kỳ API key nào

```powershell
uv run --no-sync python -m app.place_search --resolve "Sa Pa"
uv run --no-sync python -m app.place_search --input examples/places-osm-sapa.json
```

Có thể thêm `--endpoint https://your-overpass-server/api/interpreter` và
`--output evaluation/place-result.json`. Endpoint chỉ do người vận hành cấu hình,
không nhận từ request body/LLM. Tên địa danh cần khớp tên trong OSM; bản đầu chỉ
có alias Sa Pa/Sapa, Đà Nẵng/Da Nang, chưa có geocoder semantic hoặc tìm lỗi chính tả.

### Gọi qua API

Specialist API (port 8002):

- POST /api/v1/tools/places/locations với `{"destination":"Sa Pa"}`.
- POST /api/v1/tools/places/search với JSON trong examples/places-osm-sapa.json.

Cần TRAVELMATE_API_TOKEN; hai tool không cần Gemini. Khi nhiều địa danh trùng tên,
chọn từ kết quả locations rồi truyền location_id vào search.

### Chạy Place Agent có Gemini

Trong .env:

```dotenv
PLACE_PROVIDER=osm
GOOGLE_API_KEY=<Gemini key>
TRAVELMATE_API_TOKEN=<backend token>
OVERPASS_URL=https://overpass-api.de/api/interpreter
```

```powershell
uv run --no-sync uvicorn app.place_api:create_app --factory --host 127.0.0.1 --port 8001
```

POST /api/v1/agent/places. GOOGLE_MAPS_API_KEY không cần khi PLACE_PROVIDER=osm.
Provider Google vẫn cần Maps key. Không tự chuyển sang dữ liệu mẫu khi nguồn lỗi.

## Giới hạn dữ liệu và vận hành

OSM là dữ liệu cộng đồng, không phải danh bạ đầy đủ hay dữ liệu tình trạng dịch vụ
realtime. fetched_at là thời điểm đọc nguồn, không phải ngày doanh nghiệp cập nhật.
Địa chỉ có thể rỗng, ảnh/giờ hoạt động có thể thiếu; luôn giữ nguồn để người dùng kiểm tra.
Keyword là bộ lọc chuỗi literal sau tìm kiếm; không chứng minh nhu cầu như
"phù hợp gia đình". Nhận tối đa 101 POI từ nguồn, dùng 100; cảnh báo nếu bị giới hạn.
Không cam kết kết quả là gần nhất trong mọi địa điểm ngoài đời.

Chỉ node địa danh được resolver hỗ trợ. Thiếu locality trong OSM hoặc tên đầu vào
quá rộng phải trả needs_location, không dựng tọa độ giả. Không tự lấy ranh giới
tỉnh/huyện hoặc dịch địa danh theo suy đoán LLM. Bán kính là quanh tâm locality,
không phải toàn bộ địa giới. Bộ lọc Việt Nam dựa trên area country của nguồn.

Default public endpoint chỉ dùng cho thử nghiệm nhỏ có giới hạn. Cần đổi sang
dịch vụ phù hợp hoặc máy chủ riêng trước khi triển khai nhiều người dùng. Cache
và rate limit hiện theo process, không phải quota phân tán; chạy một process
cho thử nghiệm. Không chạy thu thập toàn bộ tỉnh/thành hay nhiều worker đồng thời.

Nguồn chính thức:
- [Overpass — sử dụng tài nguyên công cộng](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html)
- [Danh sách endpoint và quy định từng máy chủ](https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances)
- [Ghi công và giấy phép OSM](https://www.openstreetmap.org/copyright)

Provider này không gọi public Nominatim. Luôn hiển thị attribution trong dữ liệu
kết quả khi đưa lên giao diện; ảnh tham chiếu có thể có giấy phép riêng.

## Kiểm chứng ngày 22/10/2026

Unit/integration tests dùng HTTP MockTransport và ADK Runner thật với scripted
model. Bao gồm lựa chọn locality, chống injection truy vấn, loại dữ liệu hỏng,
dedup, cache/concurrency, cooldown, nguồn từng trường, thiếu giá, auth API và
luồng model dừng hỏi người dùng khi địa danh mơ hồ.

Thử live từ máy hiện tại: overpass-api.de và overpass.private.coffee bị timeout;
maps.mail.ru trả HTTP 504. Chưa lấy được danh sách khách sạn Sa Pa thật trong lần
này, chưa xác minh truy vấn trên server thành công và chưa gọi Gemini thật với OSM.
Không có file kết quả địa điểm thật để dùng làm bằng chứng. Không thay kết quả
live lỗi bằng fixture để báo thành công.

Frontend/multi-agent chưa được chuyển sang provider này trong bước triển khai agent độc lập.
