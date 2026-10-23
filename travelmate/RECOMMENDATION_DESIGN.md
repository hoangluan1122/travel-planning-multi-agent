# Recommendation của TravelMate

## Bài toán

Nhận tập địa điểm có ID từ Place, sở thích người dùng và ngữ cảnh chuyến đi để chọn
tối đa limit địa điểm. Giữ các điểm bắt buộc, loại các điểm không được chọn, trả
điểm theo từng tiêu chí, nguồn bằng chứng và những nhu cầu chưa thể xác nhận.

Đây là content-based ranking theo taxonomy/bằng chứng được cung cấp, có baseline
chấm điểm cố định và một chế độ LLM được giới hạn bằng tools. Chưa có mô hình học
từ lịch sử hành vi, embedding, collaborative filtering hoặc benchmark hài lòng.

Mã:

- `app/specialists/recommendation_scoring.py`: schema bằng chứng, điều kiện và công thức.
- `app/specialists/recommendation.py`: RecommendationRanker và RecommendationSpecialist dùng ADK.
- `app/evaluate_recommendations.py`: chạy lại trên snapshot Place đã lấy từ nguồn thật.

## Đầu vào và bằng chứng

`RecommendationRequest` giữ các trường candidates, interests, limit,
excluded_place_ids, required_place_ids; thêm context tùy chọn nên đầu vào cũ vẫn dùng được.

| Trường context | Ý nghĩa |
| --- | --- |
| origin | Tọa độ làm mốc khi so khoảng cách |
| max_distance_m | Ngưỡng lọc khoảng cách đường chim bay, phải có origin |
| proximity_scale_m | Khoảng cách mà điểm proximity giảm về 0, mặc định 5.000 m |
| max_price_vnd / price_basis | Mức trần và đơn vị so sánh giá |
| prices | Khoảng giá, đơn vị, nguồn, thời điểm quan sát và hạn giá theo candidate ID |
| features | Các thuộc tính true/false có nguồn theo candidate ID |
| required_features | Thuộc tính bắt buộc như wheelchair_accessible, quiet, family_friendly |
| unknown_policy | keep_with_warning mặc định, hoặc exclude khi điều kiện lọc chưa được chứng minh |
| weather_risk / weather_source | Ngữ cảnh thời tiết do caller cung cấp; low/elevated bắt buộc có nguồn |
| weights | Trọng số interests/proximity/affordability/weather |

Giá có 4 đơn vị: per_person_visit, per_person_meal, per_room_night, per_group.
Không dùng giá/bữa để chứng minh phù hợp trần giá vé, hoặc giá/phòng để chứng minh
ngân sách cả đoàn. Giá hết hạn, thời điểm quan sát ở tương lai hoặc sai đơn vị
được xem là không dùng được; phản hồi ghi price_unavailable_reason.

FeatureEvidence yêu cầu boolean đúng kiểu và nguồn không rỗng. Không suy ra
family_friendly, quiet hay wheelchair_accessible từ tên cơ sở hoặc số sao.
Taxonomy type museum/gallery → culture, restaurant/cafe → food, hotel → lodging
chỉ là ánh xạ chủ đề; không xác nhận chất lượng dịch vụ. Feature có khai báo tường
minh được ưu tiên hơn taxonomy. Không nhận hai giá trị cho cùng một feature/địa điểm.

Nguồn ở đây là dữ liệu đầu vào, chưa được recommender tự truy cập/xác thực.
Caller phải dùng bằng chứng đúng địa điểm, thời điểm, ngày đi và nhu cầu.

## Lọc trước khi xếp hạng

1. Loại excluded_place_ids.
2. Loại điểm nằm ngoài max_distance_m nếu có. Đây là Haversine theo tọa độ, không
   phải khoảng cách đường xe; Route kiểm tra tiếp ở bước sau.
3. Nếu có max_price_vnd, giá min vượt trần sẽ bị loại. Nếu khoảng giá cắt qua
   trần hoặc thiếu giá, mặc định giữ kèm cảnh báo; unknown_policy=exclude sẽ loại.
4. Thuộc tính bắt buộc có giá trị false sẽ bị loại. Thuộc tính chưa có bằng chứng
   được giữ kèm cảnh báo hoặc loại theo unknown_policy.
5. Nếu một required_place_id bị loại, trả needs_resolution, danh sách xung đột,
   và không nộp tập địa điểm như thể yêu cầu đã được đáp ứng.

Mặc định keep_with_warning hỗ trợ khảo sát khi nguồn thiếu dữ liệu. Trong trường
hợp điều kiện là ràng buộc cứng phải được xác nhận, caller cần dùng exclude.
Không tự nới trần giá, tăng bán kính hoặc cho điểm bắt buộc vượt qua bộ lọc.

## Công thức điểm có thể kiểm tra

Các trọng số mặc định: sở thích 0,5; gần 0,2; phù hợp giá 0,2; thời tiết 0,1.
Chỉ kích hoạt tiêu chí có ngữ cảnh: có interests; có origin; có trần giá;
hoặc weather_risk=elevated. Chuẩn hóa trọng số một lần cho toàn bộ ứng viên
trên các tiêu chí đang hoạt động. Thiếu dữ liệu ở một ứng viên không tự làm
tăng trọng số các tiêu chí còn lại của ứng viên đó.

| Tiêu chí | Điểm trong khoảng 0–1 |
| --- | --- |
| interests | Số sở thích khớp taxonomy/bằng chứng true chia số sở thích đầu vào |
| proximity | max(0, 1 − khoảng cách / proximity_scale_m) |
| affordability | max(0, 1 − giá max / trần), thiếu giá dùng được thì 0 và có cảnh báo |
| weather | Khi elevated: indoor true, outdoor chưa true → 1; cả hai true → 0,5; còn lại → 0 |

Tổng = 100 × tổng(trọng số chuẩn hóa × điểm tiêu chí).
Tổng điểm là độ khớp của công thức, không phải sao cộng đồng, điểm an toàn,
độ tin cậy hoặc xác suất hài lòng. Giá bằng trần vẫn có thể đủ điều kiện dù điểm
affordability bằng 0; đây là điểm khuyến khích còn dư ngân sách, khác điều kiện lọc.
Weather chỉ ưu tiên có bằng chứng trong nhà, không chứng minh an toàn khi có mưa.

Các sở thích dùng bảng alias tiếng Việt/Anh tường minh như văn hóa/culture,
bảo tàng/museums, thiên nhiên/nature, yên tĩnh/quiet. Chuỗi ngoài bảng được ghi
unresolved_interests, không suy đoán đáp ứng từ tên địa điểm. Chưa có phân tích
ngữ nghĩa tự do trong baseline chấm điểm.

Baseline chọn các ID bắt buộc trước để giữ chỗ trong limit, lấy các ID còn lại
theo điểm giảm dần rồi hiển thị toàn bộ tập đã chọn theo điểm. Nếu bằng điểm,
ưu tiên ít trường thiếu hơn rồi ID để kết quả ổn định.

## ADK và kết quả

RecommendationSpecialist vẫn dùng LlmAgent, Runner và session riêng mỗi request.
Model gọi inspect_candidates để xem các điểm đủ điều kiện, điểm công thức và dữ
liệu thiếu, rồi submit_ranking bằng ID. Submit không nhận thông tin cơ sở/giá hay
điểm số do model tự viết. Phần kết quả lấy lại nguyên Place gốc và điểm từ công cụ.
LLM không thể nộp ID đã bị lọc, ID tự tạo, ID trùng hoặc thiếu ID bắt buộc.

Mặc định tối đa 6 model calls, 2 lượt đọc, 3 lần nộp. Có thể sửa submission sai
trong hạn mức. Xung đột bắt buộc/không còn ứng viên được trả trước khi gọi model.
Thứ tự LLM có thể khác điểm baseline, method và warnings nói rõ điều này.

| status | Ý nghĩa |
| --- | --- |
| ranked | Có kết quả và không còn cờ thiếu trong các tiêu chí/điều kiện đang xét |
| partial | Có kết quả nhưng một số sở thích, giá hoặc điều kiện chưa được xác nhận |
| no_eligible | Không còn ứng viên sau bộ lọc |
| needs_resolution | Điểm bắt buộc xung đột với điều kiện lọc |

Đầu ra giữ places để tương thích; items chứa place_id, score, criteria và nguồn,
matched_interests, unresolved_interests, missing_evidence, distance_m và cờ bắt buộc.
rejected ghi ID, mã lý do và các nguồn có liên quan.

## Chạy và API

Chế độ tính điểm không cần Gemini key hoặc truy cập mạng:

```powershell
uv run --no-sync python -m app.specialists recommendation-score --input examples/recommendation-evidence.json --output evaluation/recommendation-example.json
```

File ví dụ trên chứa địa điểm, giá và thời tiết **giả lập có nhãn**, dùng để kiểm
tra công thức và so sánh thứ hạng. Không dùng làm gợi ý du lịch thật.

Chế độ LLM cần GOOGLE_API_KEY và model được cấu hình:

```powershell
uv run --no-sync python -m app.specialists recommendation --input examples/recommendation-evidence.json
```

Specialist API (có Bearer token TRAVELMATE_API_TOKEN):

- `POST /api/v1/agents/recommendation/score`: baseline xác định, không cần Gemini.
- `POST /api/v1/agents/recommendation`: ADK/LLM cùng bộ lọc và bằng chứng.
- Callable để agent ADK khác dùng: rank_recommendations(request_json: str).

## Kiểm tra bằng dữ liệu Place thật

```powershell
uv run --no-sync python -m app.evaluate_recommendations --place-snapshot evaluation/browser-places-sapa-live.json --output evaluation/recommendation-real-place-replay.json
```

Lần replay ngày 22/10/2026 dùng bản ghi Hotel de la Coupole đã lấy từ website
MGallery: giữ nguyên tên, nguồn và tọa độ; taxonomy xác nhận chủ đề lodging.
Yêu cầu thử có sở thích khách sạn/gia đình và trần 1.500.000 VND/phòng/đêm.
Kết quả partial vì chưa có giá và chưa có bằng chứng family_friendly. Không lấy
snippet 1.700.000 đồng từ tìm kiếm để điền vào, không tự khẳng định phù hợp gia đình.

Đây là replay từ snapshot nguồn thật đã lưu, không phải tìm kiếm trực tiếp mới,
không phải thử Gemini thật, cũng chưa chứng minh chất lượng xếp hạng giữa nhiều
địa điểm thực tế. Các test ADK dùng ScriptedModel với Runner/tool thực.

## Phạm vi tích hợp

Places từ kết quả có thể được đưa vào PlannerInput.places; Route cần kiểm tra lại
tuyến và thời gian; Budget cần tính tổng chi phí toàn chuyến. Trần trong Recommendation
chỉ là trần đơn giá cùng đơn vị, không thay phép tính ngân sách đoàn.
Chưa tự lấy sở thích từ Memory, không tự truy cập lại giá, không tự gọi Weather,
Route hoặc Budget. Chưa ghép workflow đa agent, A2A hoặc frontend trong thay đổi này.
Những giới hạn này tách khỏi việc agent xếp hạng đã được triển khai và kiểm thử.
