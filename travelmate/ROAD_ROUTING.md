# Tuyến đường theo ngày của TravelMate

## Hành vi đã triển khai

Nhận tọa độ nơi xuất phát, tối đa 8 điểm dừng, thời lượng và khung giờ mỗi điểm,
giờ kết thúc ngày. Tìm thứ tự có tổng thời gian lái xe nhỏ nhất trong những lịch
thỏa ràng buộc. Nếu bằng nhau, chọn lịch kết thúc sớm hơn.

Mã chính: `app/specialists/routing.py`. Tích hợp lịch trình:
`app/specialists/routed_planner.py`. Không cần Gemini/Maps key để tính tuyến độc lập.

## Đầu vào

| Trường | Ý nghĩa |
| --- | --- |
| origin | ID và tọa độ nơi xuất phát |
| visits | ID, tọa độ, thời lượng dừng và giờ nhận khách/kết thúc cho mỗi lượt |
| departure_minute / finish_by_minute | Giới hạn ngày, đơn vị phút từ 00:00 theo giờ địa phương do caller cung cấp |
| return_to_origin | Kết thúc về nơi xuất phát; mặc định true |
| destination | Điểm kết thúc riêng, ví dụ ga/sân bay, khi return_to_origin=false |
| travel_buffer_minutes | Đệm mỗi chặng, bao gồm chặng về/đến điểm cuối |
| fixed_start_minute | Bắt đầu hoạt động đúng giờ này, không đẩy lịch hẹn sang giờ khác khi đến trễ |
| precedence | Các cặp before_id/after_id phải giữ thứ tự; từ chối ID lạ và chu trình |
| optimize_order | false để giữ đúng thứ tự người dùng đã nhập và chỉ kiểm tra tính khả thi |
| include_geometry | Lấy thêm đường GeoJSON sau khi đã chọn được thứ tự; mặc định false |

Mỗi ID phải duy nhất. Một điểm kết thúc riêng phải có ID khác các điểm trước.
Nếu muốn quay về gốc thì dùng return_to_origin, không nhập destination trùng ID.
Mô hình hiện không biểu diễn hai lần ghé cùng ID trong một ngày; cần ID lượt ghé
riêng hoặc bổ sung mô hình lượt ghé trước khi hỗ trợ tình huống đó.

## Thuật toán và phép tính

1. Gọi OSRM Table với annotations=duration,distance, radiuses=200 m.
   Tọa độ gửi theo thứ tự longitude,latitude; ma trận có hướng, đơn vị giây/mét.
2. Kiểm tra kích thước, giá trị số, null, kết quả bám đường và ID điểm.
   Null nghĩa không có đường đi, không được thay bằng 0 hoặc đường chim bay.
3. Duyệt tối đa 8! = 40.320 thứ tự. Bỏ các thứ tự vi phạm precedence.
4. Với mỗi chặng, giờ đến = giờ rời điểm trước + thời gian lái xe + đệm.
   Giờ hoạt động bắt đầu = max(giờ đến, giờ mở), hoặc fixed_start_minute nếu có.
   Đến sau lịch hẹn làm thứ tự đó không khả thi. Thời lượng dừng phải nằm trọn
   trong cửa sổ và trong thời hạn ngày; chặng về/đến điểm cuối cũng phải kịp hạn.
5. Chọn thứ tự khả thi có tổng driving_seconds nhỏ nhất; khi bằng nhau chọn
   finish_second sớm hơn. Mục tiêu không phải kết thúc sớm nhất bằng mọi giá.
6. Trả từng chặng, lịch chờ, đệm, tổng quãng đường, baseline và số thứ tự đã xét.
   Nếu không có thứ tự nào phù hợp, trả infeasible và lý do; không tự bỏ điểm.
7. Nếu cần đường vẽ, gọi OSRM Route theo đúng thứ tự vừa chọn. Kiểm tra danh tính
   waypoint, số chặng, tổng thời gian/quãng đường và GeoJSON. So từng thời gian
   chặng với ma trận, dung sai max(2 giây, 5% thời gian chặng).

Nếu geometry lỗi hoặc thời gian không khớp, lịch ma trận vẫn được trả, nhưng path
để null và geometry_status ghi unavailable/mismatch. Không tạo đường thay thế.
geometry_status=available nghĩa lấy được đường từ nguồn và phù hợp phép kiểm tra
này, không xác nhận độ chính xác thời gian ngoài đường.

Các tổng `travel_seconds`, `waiting_seconds`, `buffer_seconds` được trả riêng.
Thời gian cả ngày còn bao gồm thời gian tham quan/dừng, vì vậy không dùng
travel_seconds làm toàn bộ thời lượng chuyến đi. schedule/legs dùng giây từ 00:00.
Không hỗ trợ lịch qua nửa đêm trong một RouteRequest.

## Nguồn dữ liệu và vận hành

Nguồn [OSRM API](https://project-osrm.org/docs/v5.24.0/api/), sử dụng Table và Route,
profile driving. Chưa cung cấp chế độ đi bộ, xe máy, xe đạp hoặc giao thông realtime.
Đổi chữ profile trên URL không đủ để khẳng định server có dữ liệu của chế độ khác.

Provider dùng User-Agent nhận diện ứng dụng, cache 60 giây tối đa 64 mục, một
yêu cầu đang chạy và cách nhau tối thiểu 1,1 giây trong cùng instance. Cache giữ
fetched_at gốc. Khi 429, cooldown 30 giây; không retry hàng loạt. Timeout và kích
thước response đều có giới hạn. Rate limit này chỉ trong một process, không phải
hạn mức phân tán cho nhiều worker. Nguồn mặc định là server demo, chưa có SLA.
Tham khảo [chính sách OSRM](https://github.com/Project-OSRM/osrm-backend/wiki/Api-usage-policy).
Server triển khai được cấu hình qua OSRM_URL, không nhận URL provider từ request.

Khoảng lệch về đường được nguồn trả trong matrix.snapped_points. Bám đường dưới
200 m không chứng minh đó là cổng vào địa điểm, có bãi đỗ xe hay có thể tiếp cận
bằng ô tô. Caller vẫn phải xác minh tọa độ và cửa vào phù hợp.

## Chạy thử và kết quả thật

```powershell
uv run --no-sync python -m app.specialists route --input examples/route-day.json --output evaluation/route-day-live-2026-10-22.json
uv run --no-sync python -m app.render_route --input evaluation/route-day-live-2026-10-22.json --output evaluation/route-day-preview.html
```

Lần chạy mạng thật 22/10/2026 với ba tọa độ thử nghiệm ở Đà Nẵng:

- Nguồn https://router.project-osrm.org, có ma trận thời gian/quãng đường và GeoJSON thật.
- Tuyến tối ưu north-riverside → south-riverside → east-coast → gốc.
- Quãng đường 12.922,6 m, lái xe 999 giây; baseline 1.194,4 giây.
- Giảm 195,4 giây lái xe trên cùng ma trận, duyệt 6 thứ tự.
- Đệm 5 phút × 4 chặng = 20 phút; chờ lịch hẹn 12:00 khoảng 63,5 phút.
- Kết thúc khoảng 12:55:10, gồm lái xe, đệm, chờ và 135 phút hoạt động.
- Đây là thử nghiệm nguồn tuyến theo tọa độ. Điểm dừng, thời lượng 45 phút và
  lịch hẹn là giả định thử nghiệm, chưa xác nhận đó là điểm tham quan thực tế.

File HTML hiển thị sơ đồ đường theo tọa độ bằng SVG, không tải nền bản đồ hay tile.
Frontend có thể đưa path.geometry vào lớp GeoJSON của bản đồ khi tích hợp.

## API và tích hợp Planner

- `POST /api/v1/agents/routes`: RouteRequest → RouteReport; token của specialist API,
  không cần Gemini key. Body như examples/route-day.json.
- `POST /api/v1/agents/planner/routed`: RoutedPlannerInput → RoutedPlan; cần Gemini
  key vì có bước tạo bản nháp trước khi tính tuyến.
- RoutedPlanner route_days hỗ trợ destination, travel_buffer_minutes,
  include_geometry, optimize_order, fixed_starts theo ID và precedence.
- Route giữ các giới hạn chung của Planner và thời lượng hoạt động. Lịch sau tính
  nằm trong days[].route.schedule; original_draft là bản trước tính tuyến.
- Lịch hẹn bắt buộc phải xuất hiện đúng ngày trong bản nháp, nếu bị bỏ thì trả lỗi.
  Hệ thống chưa tự biến yêu cầu tự nhiên thành các ràng buộc này.
- Tool callable cho ADK: plan_road_route(request_json: str). Chưa ghép thành A2A
  hay tự gọi Weather/Budget trong bước thay đổi này.

Đã có tuyến để Planner sử dụng và quãng đường cho bước ước tính chi phí, nhưng
chưa tự suy ra giá taxi, nhiên liệu, phí cầu đường hoặc cước xe từ số km.
Budget cần đơn giá và quy tắc tính phí có nguồn trước khi đưa khoản đó vào tổng.

## Kiểm thử

tests/test_routing_extended.py kiểm tra điểm cuối, lịch hẹn, thời gian đệm, chờ,
precedence, thứ tự khóa, dữ liệu nguồn hỏng, cache/cooldown, đường không khớp,
kiểm tra API và phát lại snapshot mạng thật. Các test cũ tiếp tục chạy.
Snapshot và replay không thay thế việc đánh giá thời gian di chuyển ngoài thực tế.
