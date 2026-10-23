# Tối ưu tuyến đường — tiến độ và bằng chứng

**Cập nhật 22/10/2026:** xem [ROAD_ROUTING.md](ROAD_ROUTING.md) cho quãng đường,
GeoJSON, lịch hẹn cố định, điểm cuối riêng, đệm di chuyển, API và kết quả chạy mới.
Các phần dưới đây ghi lại những đợt thử trước.

## Phạm vi đã chạy

RouteSpecialist chạy độc lập, chưa tự sửa lịch trình của Planner. Một ngày có tối
đa 8 điểm, gốc xuất phát cố định, tùy chọn quay về gốc. Duyệt toàn bộ thứ tự để
tìm thời gian di chuyển nhỏ nhất trong các lịch thỏa cửa sổ tham quan và giờ kết
thúc; nếu bằng nhau chọn giờ kết thúc sớm hơn. Ma trận có hướng, không giả định
đường đi và về giống nhau. Đường không tới được giữ null, không thay bằng 0.

Nguồn giao thức: https://project-osrm.org/docs/v5.24.0/api/#table-service
Đơn vị ma trận là giây. Không dùng khoảng cách đường chim bay để giả làm đường xe.
Profile demo là driving, không được sử dụng như dự báo đi bộ hoặc xe máy.

```powershell
uv run --no-sync python -m app.specialists route --input examples/route.json
```

## Smoke test live 21/10/2026

Nguồn: https://router.project-osrm.org, fetched_at 2026-10-21T02:32:55.151620Z.
Điểm thử là tọa độ khu vực ở Đà Nẵng; không xác nhận là cửa vào điểm tham quan.
Thời lượng mỗi lượt dừng 45 phút là giả định thử nghiệm, không phải dữ liệu nguồn.

Thứ tự ma trận: danang-central, south-riverside, north-riverside, east-coast.

```json
[[0,253.1,134.9,322.1],[204.7,0,237.9,229.7],[183.8,325.2,0,394.2],[309.2,283.6,342.4,0]]
```

- Baseline thứ tự đầu vào: 1194.4 giây lái xe.
- Tối ưu: north-riverside → south-riverside → east-coast → gốc: 999 giây.
- Giảm 195.4 giây (~16.36%) trên cùng ma trận, duyệt 6 hoán vị.
- Đây là một smoke test mạng thật, không phải benchmark đại diện hay thực nghiệm ngoài đường.

## Chưa đủ bằng chứng hoàn thành mục tiêu

- Đã tích hợp hậu kiểm theo ngày trong RoutedPlannerSpecialist; chưa chạy Gemini thật end-to-end.
- Đã có ba bộ tọa độ/6 ca và baseline ngẫu nhiên, nearest-neighbor; chưa đủ đa dạng để đại diện thực tế.
- Chưa kiểm chứng vị trí vào cửa, thời lượng tham quan, giờ hoạt động thực tế.
- Chưa có giao thông động, vận tải công cộng, chia điểm qua nhiều ngày.
- Chưa có đánh giá Gemini thật/human review; thiếu API key ở lần kiểm tra gần nhất.
- Cần lưu báo cáo thực nghiệm tái lập gồm snapshot đầu vào, ma trận, metric và lỗi,
  đồng thời phân biệt chất lượng tối ưu trên ma trận với chất lượng chuyến đi thực tế.

Weather/Budget/Memory vẫn là specialist xác định. Không coi việc thêm LLM là một
chỉ số chất lượng; phép tính, phân quyền và tính hợp lệ cần được kiểm tra bằng mã.

## Đợt đánh giá mở rộng

Snapshot `evaluation/routes-live-2026-10-21.json` lưu input, nguồn, thời điểm,
ma trận, lịch đầu ra và các baseline. Test replay không gọi mạng.

| Bộ tọa độ | Thứ tự đầu vào (giây) | Nearest-neighbor | Tối ưu | Trung bình 20 thứ tự ngẫu nhiên |
| --- | ---: | ---: | ---: | ---: |
| Đà Nẵng | 1194.4 | 999.0 | 999.0 | 1085.52 |
| Hà Nội | 983.8 | 970.9 | 857.5 | 1077.115 |
| TP.HCM | 553.9 | 553.9 | 428.9 | 545.23 |

Ba ca khung ngày 10 phút đều báo infeasible (riêng thời lượng tham quan giả định
đã là 135 phút). Đây là kiểm tra biên rõ ràng, không phải tình huống khó hay kiểm
chứng độ chính xác thời gian đường đi. Seed ngẫu nhiên cố định 42; các mẫu có thể trùng.

Chạy lại live: `uv run --no-sync python -m app.evaluate_routes`.

## Planner đã nối tuyến

`RoutedPlannerSpecialist` lấy bản nháp từ LLM rồi gọi provider và bộ tối ưu xác
định, không yêu cầu LLM tính thời gian đi đường. Input là PlannerInput cộng
`route_days`: date, origin, departure_minute, finish_by_minute, return_to_origin,
và windows theo place ID (opens_minute, closes_minute, source).
Đầu ra `days[].route.schedule` dùng giây từ đầu ngày và là lịch sau tối ưu;
`original_draft` giữ nguyên để đối chiếu, không dùng làm lịch đã xác minh.
Nếu không khả thi, trả trạng thái infeasible, không xóa điểm để làm kết quả đẹp.
Chưa xác minh window do caller cung cấp; window thiếu được liệt kê rõ ràng.

Chạy: `uv run --no-sync python -m app.specialists routed-planner --input examples/routed-planner.json`.
Cần GOOGLE_API_KEY; ví dụ dùng dữ liệu giả lập có nhãn. Chưa hoàn tất đánh giá LLM
thật, chất lượng địa điểm, thời lượng tham quan, giờ mở cửa hoặc khảo sát người dùng.
