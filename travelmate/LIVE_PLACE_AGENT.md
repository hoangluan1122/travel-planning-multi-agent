# Place Agent — tra cứu nhiều địa điểm có nguồn

> **Cập nhật tìm toàn quốc:** xem [NATIONAL_PLACE_AGENT.md](NATIONAL_PLACE_AGENT.md).
> Giao diện hiện tại đã có tìm theo polygon tỉnh/thành, khu vực cũ và cả nước.
> Nội dung bên dưới ghi phạm vi/kiểm chứng v2 trước khi thêm chế độ khu vực.

## Chạy ứng dụng

Tại thư mục `travelmate` có `pyproject.toml`:

```powershell
.\start-live-place.ps1
```

Mở [Place Agent](http://127.0.0.1:8001/). Nhập địa danh, chọn loại địa điểm,
bán kính, số bản ghi và bấm chạy. Không sử dụng examples/evaluation làm dữ liệu trả
về. Đây là ứng dụng độc lập, không phải demo lịch trình ở cổng 8000.

## Chức năng đã triển khai

- Ba nhóm: lưu trú (hotel/hostel/guest house…), ăn uống (nhà hàng/café…), tham quan
  (điểm tham quan/bãi biển/bảo tàng/công viên…). Phân loại bằng tag nguồn.
- Phân giải khu dân cư tại Việt Nam từ GeoNames qua Open-Meteo. Tên tỉnh không
  mặc nhiên được coi là một điểm đến; địa danh mơ hồ cần người dùng xác nhận.
- Tra Photon/OpenStreetMap trong bán kính 250 m–10 km quanh tâm khu dân cư đã chọn.
  Mỗi truy vấn lấy tối đa 50 ứng viên từ chỉ mục, không phải toàn bộ địa điểm.
- Kiểm tra quốc gia, loại, tên, OSM ID, tọa độ và bán kính; loại trùng ID hoặc
  tên/địa chỉ/tọa độ tương đương. Sắp xếp khoảng cách đường chim bay tăng dần.
- Trả 1–20 bản ghi/trang, chuyển trang bằng offset; cache tối đa 5 phút giúp giảm
  tải và ổn định phân trang. Kết quả có thể thay đổi sau khi cache hết hạn.
- Có URL nguồn, nguồn từng trường, thời điểm lấy, loại tọa độ và quy thuộc. Chỉ
  giữ website, số điện thoại, giờ mở cửa thô khi có trong nguồn.
- Giao diện desktop/mobile, chọn địa danh, trace, API/Swagger và tải JSON.
- Bằng chứng riêng từng invocation; không chấp nhận ID/nội dung do LLM tự bịa.

Adapter MGallery cũ vẫn có thể dùng riêng qua dependency injection và các kiểm thử
hồi quy. Nó không còn là nguồn duy nhất của giao diện, không tự trộn với OSM.
Không scrape tùy tiện mọi website.

## Kiến trúc và hai chế độ

`UI → API → LivePlaceAgent → GeoGroundedProvider → GeoPlaceService`

- `app/geo_places.py`: công cụ phân giải địa danh và tra POI, parser, cache bounded
  128 mục, timeout, giới hạn 1 MB/phản hồi, tối thiểu 1,1 giây giữa truy vấn mạng.
  HTTP 429 kích hoạt cooldown. Cache giữ nguyên thời điểm thực sự nhận dữ liệu.
- `app/live_place_agent.py`: input/output, vòng công cụ, kiểm tra bằng chứng.
- `app/place_agent.py`: ADK LlmAgent/Runner, tools search/details/submit, session riêng.
- `app/live_place_api.py`: cấu hình, shared source cache, same-origin, API local.
- `frontend/place-agent-live/`: giao diện desktop/mobile.

**tool_workflow, mặc định:** công cụ xác định, không gọi Gemini. Tối đa hai lần tìm.
Nếu từ khóa không có kết quả, bỏ từ khóa một lần trong cùng khu vực; kết quả mở rộng
trả partial/cảnh báo, không giả vờ đã thỏa từ khóa ban đầu.

**adk_llm:** Gemini quyết định gọi search, refresh details và submit ID quan sát được.
Provider khóa địa danh, loại và bán kính; tối đa hai lần tìm, hai lần refresh, tám
lượt model. Dữ liệu cuối từ evidence store, không lấy các trường do model tự viết.

Cấu hình GOOGLE_API_KEY và GEMINI_MODEL trên server, rồi:

```powershell
.\start-live-place.ps1 -Mode adk_llm
```

Thiếu khóa sẽ báo lỗi cấu hình, không ngầm chuyển chế độ. Không đưa khóa vào frontend.
ADK có kiểm thử Runner/tools bằng ScriptedModel; chưa kiểm chứng gọi Gemini thật
trong lần nâng cấp này vì môi trường chưa có khóa. Các kiểm chứng mạng bên dưới
chạy ở chế độ tool_workflow, không đánh đồng với LLM.

## API

POST `/api/v1/places/live`:

```json
{"destination":"Cát Bà","category":"restaurant","keyword":"","needs":"","limit":5,"radius_m":3000,"location_id":null,"offset":0}
```

Nếu needs_location, người dùng chọn từ location_options rồi gửi lại đúng ID
`geonames:...` cùng destination. Server kiểm tra ID thuộc kết quả phân giải hiện tại.
Có thể nhập `Tên địa danh, tỉnh/thành` để lọc thêm theo tên hành chính của nguồn.
GeoNames và OSM có thể khác nhau do lịch sử cập nhật; không coi nhãn nguồn là ranh
giới hành chính hiện hành đã được xác minh.

Đầu ra có resolved_location, places, place_metadata, candidate_count, has_more,
offset, sources, trace, warnings, missing_fields, execution_mode và request_id.
candidate_count là số ứng viên hợp lệ của truy vấn, không là tổng toàn vùng.

| status | Ý nghĩa | HTTP |
| --- | --- | --- |
| success | Có bản ghi từ nguồn; chưa xác nhận đang mở hay đáp ứng mọi nhu cầu | 200 |
| partial | Có bản ghi nhưng needs chưa xác minh hoặc truy vấn đã mở rộng | 200 |
| needs_location | Chờ xác nhận địa danh; chưa tra POI | 200 |
| no_results | Nguồn đã trả nhưng không có bản ghi khớp ở trang/phạm vi này | 200 |
| source_error | Nguồn/model lỗi; không phải bằng chứng không có địa điểm | 502 |
| blocked | Adapter báo bị chặn | 503 |
| timeout | Hết thời gian truy cập/thực thi | 504 |

GET `/health` trả mode, providers, supported_categories và thời điểm thành công.
GET `/docs` cung cấp Swagger. Một request xử lý tại một thời điểm; cạnh tranh nhận
429. POST khác origin bị từ chối. Bind 127.0.0.1, chưa là dịch vụ public. Nếu có
TRAVELMATE_API_TOKEN, frontend yêu cầu token API local.

## Kiểm chứng mạng/UI ngày 23/10/2026 (UTC+7)

Bán kính 3 km, trả 5 địa điểm mỗi lượt:

| Địa danh | Nhóm | Ứng viên hợp lệ đã lấy | Một số tên thực sự nhận |
| --- | --- | --- | --- |
| Cát Bà | Lưu trú | 44 | May Hostel, Chu Long, Nhật Anh Hotel 2 |
| Cát Bà | Ăn uống | 46 | Com No 368, 8x Café & Bistro, My Way |
| Cát Bà | Tham quan | 8 | Bãi biển Tùng Thu, Bãi biển Cát Cỏ 1, Bãi biển Cát Cỏ 2 |
| Sa Pa | Lưu trú | 41 | A Lử Homestay, Sapa Warm Hotel, Himalaya Hostel |
| Đà Nẵng | Ăn uống | 43 | Goom Vegan, Bánh bèo 291 Nguyễn Chí Thanh |

Đây là ảnh chụp truy vấn tại thời điểm kiểm tra, không phải seed hay cam kết số lượng.
Artifact trong `evaluation/place-v2/`: năm JSON địa danh/loại, ui-export.json,
desktop.png, mobile.png. Đã kiểm tra 5 cards, trang tiếp không trùng ID, file tải
trùng request ID phản hồi API, không lỗi JS và không tràn ngang viewport 390 px.

Kiểm thử offline:

Bộ kiểm thử sau nâng cấp: **289 passed**, một cảnh báo deprecation từ thư viện
TestClient; kiểm tra Ruff không phát hiện lỗi. Bao gồm parser, địa danh mơ hồ,
phân trang/cache, sai quốc gia/bán kính, chống sửa evidence, lỗi nguồn, auth/origin
và ADK tools search/details/submit với ID giả bị từ chối.

```powershell
uv run --no-sync pytest -q
```

Probe mạng tùy chọn khi server 8001 đã chạy, không chạy liên tục/trong CI mỗi commit:

```powershell
uv run --no-sync python scripts/verify_live_place.py
```

CLI hỗ trợ ba nhóm, bán kính và explicit location ID:

```powershell
uv run --no-sync python -m app.live_place_agent --destination "Cát Bà" --category attraction --radius-m 3000 --limit 5 --output evaluation/catba.json
```

## Giới hạn và nguồn

Photon là chỉ mục OSM, có thể thiếu/chậm cập nhật. fetched_at là lúc tải từ chỉ mục,
không phải lúc chủ cơ sở xác nhận. Địa chỉ khu vực là locality_only, thiếu địa chỉ
là missing. Điểm way/relation là tâm hình học, không chắc là cửa vào; khoảng cách
không là tuyến đường. Tên nguồn có thể chưa chuẩn hóa tiếng Việt.

Chưa có: giá/phòng trống theo ngày, xác nhận hoạt động, ảnh có quyền dùng, đặt phòng,
tìm món trong menu, lưu database sản phẩm hoặc orchestration. Không điền giá 0 khi
thiếu dữ liệu. “Gia đình”, “yên tĩnh”… không được coi là đã kiểm chứng bởi tên/tag/LLM.

Public Photon dành cho mức dùng hợp lý, không bảo đảm dịch vụ. Khi mở cho nhiều
người dùng cần managed/self-hosted endpoint, điều khoản/quota phù hợp, bảo mật,
persistence, quan sát vận hành và kiểm thử tải. GeoPlaceService cho phép cấu hình
endpoint bằng constructor, không nhận URL tùy ý từ frontend.

- [Photon API](https://github.com/komoot/photon/blob/master/docs/api-v1.md)
- [Photon demo và điều kiện sử dụng](https://github.com/komoot/photon)
- [Open-Meteo Geocoding / GeoNames](https://open-meteo.com/en/docs/geocoding-api)
- [OpenStreetMap copyright / ODbL](https://www.openstreetmap.org/copyright)
