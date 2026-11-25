# Metacognition (Bài 09) trong TravelMate

Chạy cùng Planning pattern (`TRAVELMATE_ORCHESTRATOR=planning`). Mã:
`travelmate/app/agents/self_check.py` (kiểm tra) và `PlanningOrchestrator.reviewed_draft`
(`travelmate/app/agents/planning.py`, vòng tự sửa).

## Agent tự kiểm tra lịch trước khi trả lời

**Giám sát (monitoring)** — kiểm tra bằng luật trong code, không nhờ LLM tự chấm, để kết quả
đáng tin và test được:

| Tiêu chí | Đạt khi |
|---|---|
| Mong muốn đã nêu | Mỗi lượt tìm theo nhu cầu có kết quả (ví dụ “lăng”, “vegetarian”) có ít nhất một địa điểm phù hợp trong lịch |
| Bữa trưa | Ngày nào kéo qua trưa cũng có quán ăn bắt đầu trong khung 10:30–14:30 |
| Bữa ăn cách nhau hợp lý | Mỗi ngày tối đa 3 quán ăn, bữa sau bắt đầu ít nhất 3 tiếng sau bữa trước (không xếp hai quán liền nhau) |
| Điểm nổi tiếng | Có điểm nổi tiếng nhất trong danh sách, và mỗi ngày một điểm nổi tiếng khi đủ. “Nổi tiếng” là có trong bảng giá vé có nguồn (`app/data/ticket_prices.json`); các phần của một khu (Ngọ Môn, Điện Thái Hòa thuộc Đại Nội) tính là một |
| Ngày mưa | Ngày có mã thời tiết mưa không xếp quá một điểm ngoài trời |
| Không lặp | Không lặp một địa điểm qua nhiều ngày khi còn chỗ cùng loại chưa dùng |

Trước khi xếp, một địa điểm có hai bản ghi trên bản đồ (ví dụ “Quán Cẩm” và “Quán Cẩm - Bún Bò Huế” cách nhau vài bước) được gộp làm một (`app/tools/places/same_place.py`), nên không bị đi hai lần dưới hai tên.

Tiêu chí nào không có dữ liệu để đạt (không có quán ăn, không mưa, mong muốn không có ứng viên…)
thì không áp dụng, nên agent không bị đòi điều không thể.

**Điều chỉnh (regulation)** — lỗi được đưa lại cho LLM xếp lịch dưới dạng dữ liệu (`feedback`
trong `inspect_trip`): “Cần sửa: …” kèm “Giữ nguyên các điểm đang đạt: …”, tối đa 2 lần sửa.
Bản được chọn: ít mong muốn bị bỏ sót nhất, rồi ít lỗi nhất, rồi bản sớm nhất. Bản sửa nào lỗi
(sai ràng buộc, hết hạn mức Gemini, lỗi máy chủ) thì bỏ, giữ bản tốt nhất đã có.

**Minh bạch** — response có `self_check` (mọi bản nháp và kết quả từng tiêu chí); giao diện
hiện mục “Agent tự kiểm tra” với ✅/⚠️ và số lần đã tự sửa.

## Kết quả chạy thật (Huế 2 ngày, “Muốn ăn chay và xem lăng tẩm”, MAF)

| Lượt | Bản nháp | Kết quả |
|---|---|---|
| A | 1: thiếu lăng → 2: có lăng nhưng lặp địa điểm → 3: đạt hết | Chọn bản 3: Lăng Tự Đức, Lăng Minh Mạng, các quán chay |
| B | 1: thiếu bữa trưa → 2: đạt hết | Chọn bản 2: Lăng Khải Định, Lăng Minh Mạng |
| C | 1: sai 3 tiêu chí → 2: sai 1 → 3: đạt hết | Chọn bản 3 |

## Giới hạn

- Mỗi lần tự sửa là thêm một lần gọi Gemini; với key miễn phí dễ chạm hạn mức (429). Lỗi 429
  được chờ lâu hơn (10 s, 20 s) rồi thử lại; nếu vẫn lỗi thì giữ bản tốt nhất đã có.
- Chỉ kiểm tra được những gì đo được bằng luật; “lịch có hợp lý không” theo nghĩa rộng
  (đi lại có kịp không, thứ tự có thuận đường không) chưa được kiểm.
