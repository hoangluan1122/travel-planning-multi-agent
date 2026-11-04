# Place Agent — chấm điểm theo chuẩn một agent đơn lẻ

Khung chấm: 8 thành phần của khóa *AI Agents for Beginners* (Model, Tools, Knowledge,
Context, Memory, Planning, Trust, Observability) cộng Evaluation. Agent được chấm là
`PlaceAssistant` (`travelmate/app/place_agent.py`) chạy trong `LivePlaceAgent`
(`travelmate/app/live_place_agent.py`) với nguồn thật `GeoGroundedProvider`
(Photon/OpenStreetMap). Ngày chấm: 2026-11-05.

## Agent làm gì

Nhận điểm đến, loại địa điểm (khách sạn / ăn uống / tham quan), nhu cầu tự do và số lượng.
LLM tự quyết định tìm bằng từ khoá nào, xem chi tiết địa điểm nào và chọn những ID nào,
qua đúng ba tool:

| Tool | Làm gì | Ngân sách |
|---|---|---|
| `search_places(keyword)` | Tìm trong điểm đến và loại đã cố định | 2 lần / lượt chạy |
| `get_place_details(place_id)` | Làm mới một ID đã tìm thấy | 2 lần / lượt chạy |
| `submit_places(place_ids)` | Nộp danh sách ID; mọi dữ kiện lấy từ tool, không từ LLM | 3 lần / lượt chạy |

## Kết quả chấm

| Thành phần | Trước khi sửa | Sau khi sửa |
|---|---|---|
| **Model** | ✅ ADK và MAF; giới hạn số lần gọi model | ✅ |
| **Tools** | ⚠️ Instruction nói 3 lần tìm / 3 lần xem, provider thật chỉ cho 2 / 2; `get_place_details` thiếu mô tả tham số | ✅ Một nguồn ngân sách duy nhất, instruction sinh từ ngân sách; mọi tool có mô tả tham số |
| **Knowledge** | ✅ Evidence store: chỉ nhận ID đã thấy trong lượt chạy, dữ kiện lấy từ nguồn, `LivePlaceAgent` kiểm lại từng bản ghi | ✅ |
| **Context** | ⚠️ Instruction bị đảo câu (giới hạn lần tìm nằm lạc chỗ); dữ liệu người dùng/nguồn đã được đánh dấu là DATA | ✅ Instruction viết lại thành các quy tắc có thứ tự |
| **Memory** | ✅ Chỉ nhớ trong lượt chạy, không có bộ nhớ chéo người dùng (cố ý) | ✅ |
| **Planning** | ⚠️ Có thể dùng hết lượt tìm với từ khoá hẹp rồi kết luận "không có kết quả" | ✅ Lượt tìm cuối tự mở rộng (bỏ từ khoá) khi chưa có bằng chứng nào, và báo cho LLM |
| **Trust** | ✅ Dừng chờ người dùng chọn địa danh; mở rộng bán kính cần người bấm; lỗi nguồn không bị coi là "không có địa điểm"; không đặt chỗ/thanh toán | ✅ |
| **Observability** | ⚠️ Trace không ghi từ khoá LLM đã dùng nên không debug được hành vi | ✅ Trace ghi từ khoá từng lượt tìm và việc tự mở rộng |
| **Evaluation** | ⚠️ Có kiểm thử với model giả và một lần chạy thật, chưa có bộ đánh giá lặp lại được trên cả hai engine | ✅ `scripts/eval_place_agent.py`: bộ ca cố định, chạy cả ADK và MAF, đo tỷ lệ thành công, số bản ghi, số lượt tìm, lượt tự mở rộng, thời gian |

## Các quy tắc agent phải giữ (đã có test)

1. Không bao giờ trả địa điểm hay dữ kiện không có trong bằng chứng của chính lượt chạy.
2. Lỗi nguồn ≠ không có địa điểm: trạng thái `provider_error` / `source_error`, không phải `no_results`.
3. Tên địa danh mơ hồ → dừng ở `needs_location`, không tự chọn thay người dùng.
4. Mỗi ngân sách (lượt tìm, lượt xem, lượt nộp, lượt gọi model) là giới hạn cứng trên cả hai engine.
5. Không đặt chỗ, thanh toán, hay gọi agent khác.

## Chạy đánh giá

```powershell
cd travelmate
uv run python scripts/eval_place_agent.py --runs 1
```

Bộ ca nằm ở `travelmate/examples/eval/place_cases.json` (Hội An chay, Sa Pa khách sạn,
Đà Lạt tham quan, Huế di tích, Đà Nẵng hải sản). Mỗi ca chạy trên ADK rồi MAF; kết quả
ghi vào `travelmate/evaluation/place-agent-eval-<UTC>/` gồm `REPORT.md` và `report.json`.
Tốn token Gemini và gọi Photon/OSM thật.

## Kết quả đánh giá thật (gemini-3.5-flash-lite, 2026-11-05)

| Lần chạy | Điều đã thay đổi | Kết quả chính |
|---|---|---|
| `place-agent-eval-20261104T194802Z` | Sau khi sửa ngân sách, instruction, tìm rộng | ADK 5/5, MAF 5/5 thành công; mọi địa điểm có nguồn. Đà Lạt (trước đây MAF trả 0) nay hai engine giống hệt nhau. Nhưng Huế trả Hồ Thủy Tiên, Bi Đình; Hội An chay trả quán không chay |
| `place-agent-eval-20261104T195202Z` | Lọc tên rác + ưu tiên di tích cho Place Agent; thêm thước đo "đúng nhu cầu"; quy tắc xếp theo nhu cầu | Huế: Hoàng Thành, Kinh thành, Điện Thái Hòa, Tử Cấm Thành trên cả hai engine. Hội An chay: vẫn 0–1/5 quán chay |
| `place-agent-eval-20261104T195411Z` | Mỗi lượt tìm trả 15–20 ứng viên cho LLM chọn (trước: đúng 5 gần nhất) | Hội An chay: ADK 4/5 quán chay (Quán Chay Diệu Hoa, Minh Hien Vegetarian, V vegan…), MAF đưa quán chay lên đầu nhưng chỉ nộp 2–3. Giữa lượt chạy Photon ngừng phản hồi: các ca sau là `source_error` (agent báo đúng là lỗi nguồn); số liệu các ca đó không dùng được. Đã thêm `--pause` giữa các lượt |

Việc còn lại để đánh giá chắc hơn: chạy lại toàn bộ với `--pause` khi nguồn ổn định, nhiều lượt hơn
(`--runs 3`), và xem vì sao MAF hay nộp ít địa điểm hơn giới hạn.
