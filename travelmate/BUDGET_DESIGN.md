# Bài toán và triển khai Budget cho TravelMate

## Mục tiêu

Budget nhận thông tin chuyến đi và các khoản chi để trả lời: tổng chi phí của đoàn
là bao nhiêu, còn thiếu khoản nào, ngân sách có đủ theo khoảng giá đầu vào không,
và có thể thay những lựa chọn nào để giảm chi phí. Đây là tính toán xác định,
không cần gọi LLM hay dịch vụ ngoài. LLM/Planner có thể gọi công cụ tính toán.

Mã chính: `app/specialists/trip_budget.py`. Bộ tính `BudgetSpecialist` cũ vẫn được
giữ tương thích cho đầu vào đơn giá × số lượng. Bản mới có hợp đồng riêng để tránh
hiểu sai số người, số phòng hoặc số đêm.

## Quy tắc tính

1. Ngày đi và ngày về là hai ngày lịch được tính bao gồm cả hai đầu:
   số ngày = ngày về − ngày đi + 1; số đêm = ngày về − ngày đi.
2. Ngân sách nhập có phạm vi `group` hoặc `per_person`. Nếu theo người:
   ngân sách đoàn = ngân sách/người × số người.
3. Số phòng mặc định = làm tròn lên(số người / sức chứa một phòng). Có thể cung
   cấp số phòng khác, nhưng tổng sức chứa phải đủ. Mô hình hiện giả định phòng có
   cùng sức chứa và số người/phòng cố định suốt chuyến đi.
4. Mỗi khoản có đơn vị `person`, `room` hoặc `group`; tần suất `once`, `per_day`
   hoặc `per_night`; số đơn vị mỗi lần. Có thể chỉ định danh sách ngày tính phí.
5. Số lượng = số đơn vị tính phí × số lần × số đơn vị mỗi lần.
   Ví dụ: 2 người × 3 ngày × 3 bữa/ngày = 18 suất ăn;
   1 phòng × 2 đêm = 2 phòng–đêm; một chuyến xe cả đoàn = 1 lượt tính phí.
6. Mỗi lựa chọn có khoảng đơn giá [min, max] đã gồm thuế/phí bắt buộc. Mỗi đầu
   khoảng nhân số lượng, làm tròn lên đến đồng VND ở từng khoản. Dùng Decimal
   xuyên suốt, không dùng số thực nhị phân để cộng tiền.
7. Cộng các khoản có giá hợp lệ thành `known_min_vnd`, `known_max_vnd`.
   Dự phòng = làm tròn lên(tổng tối đa đã biết × reserve_pct / 100).
   Tổng tối đa đã biết sau dự phòng = known_max + dự phòng.
8. Số dư = ngân sách đoàn − tổng tối đa đã biết sau dự phòng.
   `over_budget_vnd` là phần dương vượt trần theo kịch bản tối đa này.
   Chi phí bình quân/người làm tròn lên, chỉ để hiển thị, không cộng ngược làm tổng đoàn.

Một chuyến trong ngày có 0 đêm. Khoản `per_night` khi đó có số lượng 0, trạng thái
`not_applicable`; nhóm lưu trú tự được bỏ khỏi danh sách nhóm bắt buộc của chuyến trong ngày.
Khoản lưu trú dạng `once` vẫn được tính nếu caller cung cấp, ví dụ thuê phòng nghỉ ban ngày.

## Giá và độ đầy đủ

- `quoted`: giá caller khai báo từ nguồn báo giá, phải có thời điểm quan sát.
- `estimated`: ước tính có nguồn hoặc giả định do người dùng cung cấp.
- `unknown`: cả min/max phải null. Giá 0 chỉ được chấp nhận khi có certainty/nguồn phù hợp.
- Giá hết hạn tại `valid_until`, thời điểm quan sát ở tương lai hoặc không phủ
  ngày sử dụng được loại khỏi tổng đã biết. Dòng vẫn tồn tại, tổng dòng là null,
  có `price_state` giải thích lý do và ID nằm trong `unknown_expense_ids`.
- `service_start_date`/`service_end_date` nếu có là phạm vi ngày tính phí bao gồm
  hai đầu; phải phủ mọi ngày khoản đó được tính. Ngày trả phòng không phải một đêm thuê.
- Giá không có ngày dịch vụ không được mặc định là báo giá riêng cho chuyến đi;
  caller chịu trách nhiệm cung cấp giá và ngày đúng nhu cầu.
- Không đủ giá hoặc thiếu nhóm chi bắt buộc sẽ không được kết luận đủ ngân sách.
  Sự xuất hiện một nhóm không chứng minh mỗi bữa/ngày/dịch vụ đã được liệt kê đủ.
  `coverage_complete` chỉ nói đủ theo khoản và nhóm đầu vào, không phải kiểm toán chuyến đi.
- Các nguồn đầu vào không được tool này tự xác thực qua Internet. Đọc snippet có
  giá trên trang tìm kiếm chưa đủ cơ sở để khai báo thành giá `quoted`.

Trạng thái được xét theo thứ tự:

| status | Điều kiện |
| --- | --- |
| over_budget | Tổng min đã biết lớn hơn ngân sách: ngay các khoản đã biết đã vượt trần |
| incomplete | Chưa vượt trần ở min nhưng còn thiếu giá, thiếu nhóm bắt buộc hoặc không có khoản áp dụng |
| at_risk | Đủ theo đầu vào, min không vượt nhưng max cộng dự phòng vượt ngân sách |
| within_estimate | Đủ theo đầu vào và max cộng dự phòng không vượt ngân sách |

`within_estimate` và `fits_supplied_costs` không bảo đảm giá bán, tồn phòng hay giá
ngoài đời sẽ giữ nguyên. Dự phòng không thể thay thế khoản chưa có giá.

## Đề xuất giảm chi phí

Caller cung cấp các options đã được chấp nhận cho cùng một khoản, bao gồm nhu cầu,
dịch vụ, sức chứa, ngày và điều kiện sử dụng. Budget không tự quyết định khách sạn
hay nhà hàng khác có đáp ứng nhu cầu người dùng không.

Khi tổng max cộng dự phòng vượt ngân sách:

1. Với từng khoản có giá dùng được, tìm option hợp lệ có tổng max thấp nhất.
2. Nếu khoản là tùy chọn và caller bật `allow_drop_optional=true`, có thể đề xuất bỏ khoản.
3. Xếp các cơ hội theo số tiền tiết kiệm giảm dần, lần lượt lấy đến khi đạt trần.
4. Tính lại quỹ dự phòng; vẫn giữ trạng thái incomplete nếu thiếu giá/nhóm bắt buộc.
5. Trả danh sách thay đổi và `applied=false`. Không sửa input hoặc lịch trình đã lưu.

Với các khoản độc lập, chọn tiết kiệm lớn nhất trước giúp giảm số khoản cần thay đổi.
Đây không phải tối ưu chất lượng trải nghiệm, không giải quyết các ràng buộc liên
quan nhau. Gói combo, giá ưu đãi phụ thuộc khoản khác hoặc thay khách sạn làm đổi
giá di chuyển phải được caller gom thành phương án nhất quán hoặc tính lại sau
Planner. Không so sánh phương án thiếu giá như phương án có giá 0.

## Chạy và API

Không cần Gemini key hoặc Maps key để chạy tính Budget:

```powershell
uv run --no-sync python -m app.specialists trip-budget --input examples/trip-budget.json --output evaluation/trip-budget-example.json
```

Ví dụ minh họa (toàn bộ đơn giá là giả định, không phải báo giá thị trường):

| Khoản | Tính | Thành tiền |
| --- | --- | --- |
| Phòng | 500.000 × 1 phòng × 2 đêm | 1.000.000 |
| Ăn | 100.000 × 2 người × 3 bữa × 3 ngày | 1.800.000 |
| Di chuyển | 500.000 × 1 đoàn | 500.000 |
| Vé | 200.000 × 2 người | 400.000 |
| Tổng đã biết | | 3.700.000 |
| Dự phòng 10% | | 370.000 |
| Tổng so với ngân sách 4 triệu | | 4.070.000, at_risk |

Option phòng 400.000/đêm thay cho 500.000/đêm tiết kiệm 200.000 tiền phòng và
20.000 dự phòng, tổng đề xuất 3.850.000. Chưa tự áp dụng thay đổi.

API: `POST /api/v1/agents/budget/trip`, body theo file ví dụ, Bearer token cấu hình
`TRAVELMATE_API_TOKEN` trên specialist workbench. API cũ `/api/v1/agents/budget`
tiếp tục nhận danh sách CostLine đơn giản, không nhận schema mới.

LLM ADK có thể nhận callable `assess_trip_budget(request_json: str) -> dict` trong
danh sách tools. Callable thực thi schema và trả kết quả cùng phép tính; agent gọi
phải dùng giá đầu vào có nguồn và không tự sửa số trong kết quả. Chưa ghép tool này
vào workflow đa agent cũ hoặc đưa lên giao diện ở thay đổi này.

## Kiểm thử

`tests/test_trip_budget.py` kiểm tra quy đổi đơn vị, ngày/đêm, số phòng lẻ, ngân sách
theo người, khoảng giá, dự phòng, làm tròn, null/0, hạn giá, ngày dịch vụ, phương án
giảm chi phí, bảo vệ khoản bắt buộc, không sửa input, runtime validation và API.

```powershell
uv run --no-sync pytest tests/test_trip_budget.py -q
```

Đầu ra ví dụ có nhãn nguồn giả định rõ ràng; không sử dụng làm giá đặt dịch vụ thật.
