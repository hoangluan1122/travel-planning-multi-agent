# Tổng hợp quy tắc và cách tính của các agent TravelMate

Tài liệu phục vụ báo cáo ngày 23/10/2026, theo mã đã kiểm tra ngày 22/10/2026.

## 1. Nguyên tắc thiết kế chung

TravelMate tách hai nhóm công việc:

- LLM hỗ trợ tìm kiếm/chọn ứng viên, đề xuất thứ tự phù hợp và tạo bản nháp lịch trình.
- Mã xác định kiểm tra điều kiện, tính tiền, tính tuyến, xử lý thời tiết và quyền bộ nhớ.

Place, Recommendation và Planner có triển khai ADK LlmAgent và function tools.
Weather, Budget, Memory và bộ tính Route không bắt buộc có LLM để chạy nghiệp vụ.
Recommendation cũng có baseline chấm điểm chạy độc lập, không cần Gemini.

Mỗi thành phần có schema đầu vào/đầu ra, timeout, request ID và kiểm tra dữ liệu.
BaseAgent kiểm tra lại cả đối tượng đã được tạo trước đó để phát hiện dữ liệu bị
sửa, đồng thời cô lập dữ liệu của mỗi lần gọi. Registry không nhận tên agent trùng.
Không biến lỗi nguồn thành dữ liệu thành công hoặc ngầm thay bằng dữ liệu demo.

Các nguyên tắc dữ liệu:

1. Thiếu giá không có nghĩa miễn phí; null khác 0.
2. Lỗi dịch vụ không có nghĩa không có địa điểm hoặc thời tiết tốt.
3. ID do LLM nộp phải nằm trong dữ liệu được phép sử dụng.
4. Không lấy giá, tọa độ, giờ mở cửa hay đánh giá do LLM tự viết thành dữ liệu nguồn.
5. Giữ nguồn và thời điểm lấy dữ liệu khi công cụ có cung cấp.
6. Văn bản người dùng và website là dữ liệu, không được thay chỉ dẫn hệ thống.
7. Có kiểm tra kỹ thuật không đồng nghĩa xác minh mọi thông tin ngoài thực tế.

## 2. Place Agent — tìm địa điểm

**Mục tiêu:** cung cấp ứng viên địa điểm cho các bước Recommendation và Planner.

**Đầu vào:** địa danh, loại hình hotel/restaurant/attraction, từ khóa, số kết quả;
với OSM còn có ID địa danh và bán kính.

**Cách xử lý đã có:**

- Cập nhật Place v2 ngày 23/10: GeoNames/Open-Meteo phân giải khu dân cư và yêu cầu
  chọn khi mơ hồ; Photon/OSM lấy POI lưu trú, ăn uống, tham quan trong bán kính.
  Kiểm tra tên, loại, quốc gia, tọa độ, khoảng cách, ID và nguồn; có phân trang,
  cache 5 phút, xuất JSON, giao diện desktop/mobile. Xem [LIVE_PLACE_AGENT.md](LIVE_PLACE_AGENT.md).

- Nhánh browser tìm nguồn bằng Cốc Cốc, đọc liên kết kết quả thường và truy cập
  các nguồn chi tiết có adapter đã kiểm tra.
- Adapter MGallery đọc dữ liệu Hotel có cấu trúc trên website chính thức: URL,
  tên, địa chỉ, quốc gia, địa danh và tọa độ. Địa danh phải khớp sau chuẩn hóa.
- Nguồn tìm thấy nhưng chưa có đủ thông tin nằm riêng trong sources; không tự
  biến một trang tổng hợp nhiều khách sạn thành một Place.
- Giá hoặc dữ liệu chưa xác minh vẫn để null. Không lấy giá từ snippet để coi là
  báo giá theo ngày lưu trú.
- Nhánh OSM phân giải địa danh, yêu cầu chọn nếu trùng, tìm trong bán kính, loại
  ID trùng, bản ghi lỗi và ứng viên nằm ngoài bán kính.
- Google Places có adapter riêng nhưng cần Maps API key khi sử dụng.

**Trong vòng LLM:** destination/category được khóa theo request; model có thể
tinh chỉnh keyword. Với nhánh provider thông thường, tối đa 3 search, 3 detail,
3 submit, mặc định 10 model calls. Chi tiết chỉ được lấy cho ID đã tìm thấy.
Chế độ browser hiện nhận kết quả tool và dừng, chưa có vòng tinh chỉnh browser nhiều lượt.

**Đầu ra:** bản ghi Place có ID, tên, địa chỉ, tọa độ, loại hình, nguồn và thời điểm;
các nguồn ứng viên chưa xác minh có trạng thái riêng.

**Hiện trạng cập nhật:** giao diện v2 đã gọi mạng thật qua Photon/OSM, tại Cát Bà
nhận 44 ứng viên lưu trú, 46 ăn uống và 8 tham quan trong bán kính 3 km; mỗi lượt
hiển thị 5. Sa Pa nhận 41 ứng viên lưu trú, Đà Nẵng nhận 43 ăn uống. Đây là số tại
thời điểm kiểm tra, không là tổng toàn vùng. Bằng chứng JSON/UI trong evaluation/place-v2/.
Nguồn Overpass cũ từng timeout; không đánh đồng với Photon đã kiểm chứng. Nhánh
MGallery từng lấy được Hotel de la Coupole nhưng không còn là nguồn duy nhất.
Luồng live hiện chạy tool_workflow, không gọi LLM; ADK có kiểm thử tools bằng
ScriptedModel, chưa kiểm chứng Gemini thật. Chưa có giá/phòng trống/ảnh xác minh.

## 3. Weather — tra cứu và phân loại thời tiết

**Mục tiêu:** cung cấp dữ liệu thời tiết đúng địa điểm/thời gian và cờ hỗ trợ
đánh giá hoạt động ngoài trời.

### Nhánh Open-Meteo theo tọa độ

Đầu vào gồm latitude, longitude, múi giờ IANA, ngày bắt đầu/kết thúc. Mỗi request
nhận 1–14 ngày; chỉ lấy các ngày thuộc phạm vi hôm nay đến hôm nay + 15 ngày.
Không tự tạo dự báo ngoài phạm vi.

Quy tắc outdoor_risk trong mã, theo từng ngày:

- unknown nếu mã thời tiết chưa được nhận biết hoặc thiếu xác suất mưa.
- elevated nếu xác suất mưa >= 70%, hoặc weather_code thuộc tập
  {65, 67, 75, 77, 82, 85, 86, 95, 96, 99}.
- not_flagged cho các trường hợp dữ liệu được nhận biết còn lại.

Đây là ngưỡng do ứng dụng thiết kế, không phải chuẩn đánh giá an toàn chính thức.
not_flagged không chứng minh có thể tham quan an toàn. Xác suất mưa không phải
phần trăm thời gian chắc chắn sẽ mưa.

Kiểm tra ngày trùng, độ dài mảng, kiểu số và xác suất 0–100. Có retry có giới hạn
cho lỗi kết nối/timeout/502/503/504; không retry 429 hàng loạt.

### Nhánh Browser Weather

Nhận tên khu vực cụ thể, tỉnh, ngày và khoảng giờ. Đọc bảng dự báo Cốc Cốc theo
tên địa danh, đối chiếu ngày/giờ sau thao tác chọn, lưu bằng chứng và giờ thiếu.
Nếu chỉ có tên tỉnh rộng, yêu cầu địa danh cụ thể. Chưa xác minh tọa độ hoặc vi
khí hậu tại từng điểm tham quan, và chưa xác định nhà cung cấp khí tượng gốc của bảng.

Nhánh browser đọc các giá trị theo giờ; không được coi là đã tự dùng cùng bộ
phân loại rủi ro daily của Open-Meteo. Hai đầu ra cần được chuyển đổi/ghép rõ ràng
khi xây dựng workflow chung.

**Ví dụ:** mã nhận biết hợp lệ và xác suất mưa 80% → elevated theo quy tắc ứng dụng.

**Hiện trạng:** đã gọi Open-Meteo thật và đọc bảng thời tiết Sa Pa thật; đây là
kiểm tra kết nối/trích xuất, không xác nhận độ chính xác dự báo ngoài thực tế.

## 4. Recommendation — xếp hạng độ phù hợp

**Mục tiêu:** chọn tối đa limit địa điểm từ tập Place, theo sở thích và ngữ cảnh.
Giữ nguyên bản ghi nguồn, trả điểm và lý do cho các tiêu chí có thể tính.

### Kiểm tra điều kiện trước khi chấm

- Loại ID người dùng không muốn, điểm quá xa và mức giá min vượt trần cùng đơn vị.
- Thuộc tính bắt buộc có bằng chứng false sẽ bị loại.
- Khi thiếu giá, thiếu thuộc tính hoặc khoảng giá cắt qua trần:
  keep_with_warning giữ ứng viên kèm cảnh báo; exclude loại ứng viên đó.
- Nếu điểm bắt buộc bị loại, trả needs_resolution, không tự nới điều kiện.

### Công thức

Điểm = 100 × tổng(trọng số chuẩn hóa × giá trị tiêu chí).

| Tiêu chí | Trọng số mặc định | Giá trị 0–1 |
| --- | ---: | --- |
| Sở thích | 0,5 | Số sở thích khớp taxonomy/bằng chứng true / số sở thích đầu vào |
| Khoảng cách | 0,2 | max(0, 1 − khoảng cách đường chim bay / 5.000 m) |
| Phù hợp giá | 0,2 | max(0, 1 − giá max / trần giá cùng đơn vị) |
| Thời tiết | 0,1 | Khi elevated: indoor true và outdoor chưa true → 1; cả hai true → 0,5; còn lại → 0 |

Tiêu chí không có ngữ cảnh được tắt và chuẩn hóa lại trọng số trên các tiêu chí
còn hoạt động. Với một ứng viên thiếu bằng chứng ở tiêu chí đang dùng, tiêu chí
đó nhận 0 và có cờ thiếu; không phân bổ lại trọng số riêng để tăng điểm ứng viên.

Các thuộc tính như phù hợp gia đình, yên tĩnh hoặc tiếp cận xe lăn cần bằng chứng
có nguồn. Không suy ra từ tên cơ sở hoặc số sao. Mức giá/bữa, giá vé và giá/phòng
là các đơn vị khác nhau; không tự quy đổi khi thiếu dữ liệu.

**Ví dụ:** khớp sở thích hoàn toàn, cách 1 km, giá max 100.000 với trần 200.000,
có bằng chứng trong nhà khi thời tiết elevated:
50 + 16 + 10 + 10 = 86 điểm.

Điểm này là độ khớp của công thức, không phải sao cộng đồng hoặc xác suất hài lòng.
Trọng số là lựa chọn thiết kế ban đầu, chưa được hiệu chỉnh bằng khảo sát người dùng.
Baseline ưu tiên giữ chỗ cho các ID bắt buộc, sau đó chọn theo điểm; hòa điểm thì
ưu tiên ít dữ liệu thiếu hơn, tiếp theo là ID để kết quả ổn định.

**Vai trò LLM:** có thể đề xuất thứ tự từ các ID đủ điều kiện sau khi đọc tool;
không sửa điểm, nguồn hay dữ liệu gốc. Thứ tự LLM có thể khác baseline và được ghi
method rõ ràng. Giới hạn mặc định 6 model calls, 2 lần đọc và 3 lần nộp.

**Hiện trạng:** có baseline và vòng ADK đã kiểm thử; replay bản ghi khách sạn thật
ở Sa Pa trả partial do thiếu giá và bằng chứng gia đình. Chưa có benchmark chất
lượng xếp hạng nhiều địa điểm thực tế hoặc thử Gemini thật cho phiên bản mới này.

## 5. Planner Agent — tạo bản nháp lịch trình

**Đầu vào:** chuyến đi, tập Place, thời tiết đã cung cấp và ràng buộc lịch.
LLM không tự tìm địa điểm, gọi Weather hay tự tính thời gian đường đi trong
PlannerSpecialist độc lập.

**Vòng xử lý:** đọc dữ liệu bằng inspect_trip → tạo bản nháp → nộp bằng
submit_itinerary → validator chấp nhận hoặc trả lỗi để model sửa.

Các điều kiện kiểm tra:

- Có đầy đủ ngày của chuyến đi, đúng thứ tự; ID địa điểm phải có trong đầu vào.
- Không chọn ID bị loại, phải có các ID bắt buộc.
- Không trùng địa điểm trong cùng ngày tham quan, không chồng giờ hoạt động.
- Giữ giờ bắt đầu/kết thúc ngày, số hoạt động tối đa và thời lượng tối thiểu.
- Hoạt động phải nằm trong visit_window được cung cấp.

Mặc định tối đa 8 model calls, 3 lần đọc và 3 lần nộp. Chỉ nhận JSON đã được kiểm
tra; văn bản do model trả về chưa qua submit không được coi là lịch hợp lệ.

Ví dụ: nếu hoạt động A kết thúc 11:00 nhưng B bắt đầu 10:45, bản nháp bị từ chối.
Tuy vậy, A kết thúc 11:00 và B bắt đầu 11:00 mới chỉ không chồng giờ, chưa chứng
minh kịp di chuyển; bước Route phải kiểm tra và tính lại.

**Hiện trạng:** Planner tạo/kiểm tra bản nháp; RoutedPlanner có hậu kiểm tuyến
theo ngày, giữ tập điểm và thời lượng. Chưa hoàn thiện việc tự ghép khách sạn,
bữa ăn, điểm tham quan và xử lý mọi nguyện vọng tự do thành ràng buộc cứng.

## 6. Route — tính và tối ưu tuyến

Đây là bộ tính xác định hỗ trợ Planner, không bắt buộc là một LLM Agent riêng.

**Đầu vào:** nơi xuất phát, tối đa 8 lượt dừng, tọa độ, thời lượng, cửa sổ giờ,
giờ hẹn cố định nếu có, thời gian đệm, thứ tự bắt buộc và điểm kết thúc.

**Cách tính:**

1. OSRM trả ma trận thời gian/quãng đường có hướng. Thời gian đi và về có thể khác.
2. Xét tối đa 8! = 40.320 thứ tự, chỉ giữ thứ tự đáp ứng các điều kiện.
3. Giờ đến = giờ rời điểm trước + thời gian lái xe + thời gian đệm.
4. Giờ bắt đầu = max(giờ đến, giờ mở), hoặc đúng giờ hẹn đã nhập. Đến sau giờ hẹn
   làm thứ tự đó không khả thi; không tự dời lịch hẹn.
5. Giờ kết thúc hoạt động = giờ bắt đầu + thời lượng dừng.
6. Kiểm tra giờ đóng và hạn cuối ngày, gồm cả chặng về hoặc chặng đến điểm cuối.
7. Chọn thứ tự có tổng thời gian lái xe nhỏ nhất; nếu bằng nhau, kết thúc sớm hơn.

Nếu khóa thứ tự bằng optimize_order=false, chỉ kiểm tra đúng thứ tự đã nhập.
Nếu không có thứ tự phù hợp, trả infeasible; không bỏ điểm để làm lịch có vẻ hợp lệ.

Tổng thời lượng ngày = lái xe + đệm + chờ + hoạt động. Các phần được trả riêng.
Khi yêu cầu GeoJSON, lấy đường theo thứ tự đã chọn và kiểm tra thời gian các chặng
so với ma trận. Nếu không khớp hoặc lỗi nguồn, trả cờ riêng, không tạo đường thay thế.

**Ví dụ đã gọi nguồn thật:** bộ tọa độ thử ở Đà Nẵng dài 12.922,6 m, lái xe 999 giây;
baseline 1.194,4 giây. Tiết kiệm 195,4 giây trên cùng ma trận. Đệm 5 phút mỗi chặng
và lịch hẹn 12:00 vẫn được giữ trong lịch đầu ra.

Nguồn là OSRM profile ô tô, chưa có kẹt xe realtime hoặc hỗ trợ đi bộ/xe máy.
Tọa độ thử và thời lượng dừng không chứng minh cửa vào địa điểm thực tế. Quãng
đường không tự trở thành giá taxi, tiền xăng hay phí đường nếu chưa có đơn giá.

## 7. Budget — đánh giá ngân sách chuyến đi

**Đầu vào:** ngày đi/về, số người, số phòng/sức chứa, ngân sách đoàn hoặc theo
người, các khoản chi có khoảng giá và nguồn, phương án thay thế đã chấp nhận.

**Công thức:**

- Số ngày = ngày về − ngày đi + 1; số đêm = ngày về − ngày đi.
- Số phòng mặc định = làm tròn lên(số người / sức chứa phòng).
- Ngân sách đoàn = ngân sách mỗi người × số người, nếu nhập theo người.
- Số lượng khoản = số người/phòng/đoàn × số lần × số đơn vị mỗi lần.
- Khoản min/max = đơn giá min/max × số lượng; làm tròn lên từng khoản tới đồng VND.
- Tổng đã biết = cộng các khoản có giá còn dùng được.
- Dự phòng = làm tròn lên(tổng max đã biết × phần trăm dự phòng).
- Tổng để so trần = tổng max đã biết + dự phòng.
- Số dư = ngân sách đoàn − tổng để so trần.

Dùng Decimal khi tính tiền. Đơn giá đầu vào phải gồm thuế/phí bắt buộc; công cụ
không tự áp thuế, đổi ngoại tệ hoặc lấy giá thị trường.

Giá có quoted/estimated/unknown; quoted cần nguồn và thời điểm quan sát. Giá hết
hạn, quan sát ở tương lai hoặc không phủ ngày dịch vụ không được dùng để khẳng
định ngân sách đủ. Khoản thiếu giữ null, có ID và lý do, không tính như giá 0.

| status | Điều kiện theo thứ tự ưu tiên |
| --- | --- |
| over_budget | Tổng min đã biết đã vượt ngân sách |
| incomplete | Chưa vượt ở min nhưng thiếu giá/nhóm bắt buộc hoặc không có khoản áp dụng |
| at_risk | Đủ theo đầu vào, min chưa vượt nhưng max cộng dự phòng vượt trần |
| within_estimate | Đủ theo đầu vào và max cộng dự phòng không vượt trần |

Đề xuất giảm tiền chỉ chọn từ các options đầu vào đã đáp ứng nhu cầu của cùng
khoản. So tổng max, ưu tiên mức tiết kiệm lớn nhất trước; tính lại dự phòng.
Chỉ được đề xuất bỏ khoản tùy chọn nếu caller bật cờ cho phép. Trả applied=false,
không sửa lịch trình đã lưu. Giả định các khoản độc lập; đổi địa điểm làm đổi giá
di chuyển hoặc giá combo cần được tính lại cùng Planner.

**Ví dụ:** 2 người, 3 ngày 2 đêm: phòng 1.000.000 + ăn 1.800.000 + xe 500.000 +
vé 400.000 = 3.700.000. Dự phòng 10% thành 4.070.000 so ngân sách 4.000.000 →
at_risk. Đổi phương án phòng 500.000 sang 400.000/đêm còn 3.850.000 gồm dự phòng.
Toàn bộ giá ví dụ là giả định, không phải báo giá thị trường.

## 8. Memory — lưu sở thích

**Đầu vào:** thao tác read/save/forget, sở thích, xác nhận, expected_version và TTL.
Danh tính người dùng do host cung cấp, không nhận từ model hoặc body để tự chọn tài khoản.

**Quy tắc:**

- Read không cần confirmed. Save/forget cần confirmed=true đúng kiểu boolean.
- Sở thích được trim; chuỗi rỗng bị từ chối; sở thích trùng được loại bỏ.
- Chỉ ghi khi expected_version bằng version hiện tại; sau ghi tăng version thêm 1.
- Hai yêu cầu ghi cùng version chỉ một được chấp nhận; yêu cầu còn lại phải đọc lại.
- Hạn dữ liệu = thời điểm lưu + ttl_days × 86.400 giây. Mặc định 90 ngày.
- Hết hạn trả empty và xóa payload khi truy cập, giữ version để chống ghi cũ.
- Forget xóa nội dung logic, không khẳng định xóa vật lý khỏi backup hoặc thiết bị.

**Hiện trạng:** dùng SQLite local có transaction. Chưa chuyển sang PostgreSQL,
chưa có semantic retrieval/vector database hoặc bộ nhớ đầy đủ lịch sử hội thoại.

## 9. Phân biệt hiện trạng và luồng tích hợp dự kiến

Luồng hướng tới: Memory cung cấp sở thích; Place và Weather cung cấp bằng chứng;
Recommendation chọn ứng viên; Planner tạo lịch; Route kiểm tra tuyến; Budget đánh
giá chi phí. Khi thay địa điểm hoặc thời gian, các kết quả liên quan cần tính lại.

Đây chưa phải toàn bộ luồng mới đã ghép xong. Trong code hiện có:

- Có workflow preview cũ với các agent phiên bản cũ.
- Các specialist mới chạy độc lập qua CLI/API.
- Planner đã có nhánh RoutedPlanner kết hợp bộ tính tuyến.
- Các specialist mới chưa đồng loạt thay thế workflow cũ, chưa có giao tiếp A2A
  hoàn chỉnh và chưa nối đầy đủ giao diện.

Giới hạn schema hiện cũng cần đồng bộ khi tích hợp: Planner/Weather nhận chuyến
đi tối đa 14 ngày; Budget theo chuyến có thể tính tối đa 31 ngày lịch.

## 10. Kết quả kiểm thử và cách trình bày khi báo cáo

Lần chạy gần nhất: **256 bài kiểm thử đạt**, gồm kiểm thử đơn vị, tích hợp API/ADK
và replay snapshot. Không gọi tất cả là unit test, và số bài đạt không đo được
độ hài lòng người dùng hoặc chứng minh sản phẩm đã hoàn chỉnh.

Các kết quả có bằng chứng chạy nguồn thật gồm Place/MGallery ở Sa Pa, Weather và
OSRM. Recommendation mới đã replay trên dữ liệu Place thật đã lưu; kiểm thử vòng
ADK của Recommendation dùng ScriptedModel. Đã từng có smoke test Planner với
Gemini thật và OSRM trên điểm đầu vào mẫu; không coi đó là benchmark toàn hệ thống.

Các câu trả lời cần nắm:

- Vì sao không dùng LLM cho mọi phép tính? Vì tiền, quyền truy cập và tính hợp lệ
  cần kết quả xác định, có thể kiểm thử; LLM hỗ trợ đề xuất trong ranh giới đó.
- Điểm Recommendation từ đâu? Từ công thức trọng số thiết kế ban đầu và bằng chứng;
  chưa phải mô hình được huấn luyện/hiệu chỉnh bằng khảo sát người dùng.
- Route tối ưu đến đâu? Tối ưu chính xác thứ tự tối đa 8 lượt dừng trên ma trận
  tĩnh đã nhận và các ràng buộc đã nhập, không tối ưu toàn bộ chuyến đi ngoài đời.
- Budget có giá thật không? Bộ tính nhận giá có nguồn; chưa tự tra đầy đủ báo giá
  dịch vụ. Đơn giá ví dụ là giả định và được ghi nhãn.
- Hệ thống Multi-Agent đã xong chưa? Có nền tảng và các thành phần đã kiểm thử;
  ghép workflow mới, A2A, dữ liệu đủ rộng và frontend vẫn là các bước còn lại.

## Các tệp nên mở khi trình bày

| Nội dung | Tệp |
| --- | --- |
| Nguyên tắc agent | AGENT_CONTRACTS.md |
| Place browser | BROWSER_PLACES.md |
| Weather browser | BROWSER_WEATHER.md |
| Recommendation | RECOMMENDATION_DESIGN.md |
| Tuyến đường | ROAD_ROUTING.md |
| Budget | BUDGET_DESIGN.md |
| Kết quả tuyến trực quan | evaluation/route-day-preview.html |
| Kết quả Budget mẫu | evaluation/trip-budget-example.json |
| Recommendation với Place thật đã lưu | evaluation/recommendation-real-place-replay.json |
