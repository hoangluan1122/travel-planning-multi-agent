# Các specialist chạy độc lập

**Recommendation có bằng chứng:** xem [RECOMMENDATION_DESIGN.md](RECOMMENDATION_DESIGN.md)
cho công thức 4 tiêu chí, lọc điều kiện, điểm bắt buộc, dữ liệu thiếu và vòng ADK.
CLI `recommendation-score` / API `/api/v1/agents/recommendation/score` chạy không cần LLM.

**Budget theo chuyến đi:** xem [BUDGET_DESIGN.md](BUDGET_DESIGN.md) để tính theo
người/phòng/ngày/đêm, khoảng giá, dự phòng và đề xuất giảm chi phí. Schema mới nằm
ở `app/specialists/trip_budget.py`, CLI `trip-budget`, API `/api/v1/agents/budget/trip`.

**Bản cập nhật:** Hợp đồng chi tiết, ràng buộc mới và kiểm thử hardening xem
[AGENT_CONTRACTS.md](AGENT_CONTRACTS.md). API độc lập đã được bổ sung tại
[SPECIALIST_API.md](SPECIALIST_API.md); các ghi chú lịch sử dưới đây mô tả lần triển khai đầu.

Đây là triển khai bổ sung, không phải chứng nhận tuân thủ một tiêu chuẩn quốc tế.
Không thay đổi workflow preview cũ, không nối multi-agent, không có A2A ở bước này.
Các lớp cũ trong agents.py được giữ để tương thích; mã mới nằm ở app/specialists.

## Đối chiếu tài liệu chính thức

- ADK custom agents: https://adk.dev/agents/custom-agents/ — tham khảo cách tách logic xác định khỏi quyết định của LLM. BaseAgent của dự án là hợp đồng ứng dụng riêng, không giả danh lớp ADK BaseAgent.
- ADK memory: https://adk.dev/sessions/memory/ — tham khảo phân biệt session với bộ nhớ lâu dài. Repository SQLite dưới đây là adapter ứng dụng, chưa phải ADK MemoryService hay kho vector.
- Open-Meteo: https://open-meteo.com/en/docs — truy vấn daily weather_code, precipitation_probability_max theo tọa độ, múi giờ, phạm vi tối đa 16 ngày.
- Planner và Recommendation dùng LlmAgent, Runner và function tools của ADK 1.39.1 trong uv.lock. Không tự chuyển sang API ADK 2 từ trang tài liệu mới.

## Những gì đã triển khai

| Specialist | Vai trò và ranh giới |
| --- | --- |
| Weather | Truy vấn tọa độ đã xác định; ngày theo múi giờ; phân biệt thiếu forecast với lỗi dịch vụ; nguồn/thời điểm lấy dữ liệu; quy tắc rủi ro đơn giản |
| Budget | Tính Decimal theo đơn giá × số lượng; VND duy nhất; phân biệt quoted/estimated/unknown; kiểm tra ID trùng, khoản thiếu và nhóm chi phí thiếu |
| Memory | Đọc/lưu/quên sở thích có xác nhận; TTL; phiên bản chống cập nhật cũ; cô lập theo UUID do host cung cấp; SQLite local có transaction |
| Recommendation | LLM đọc ứng viên qua tool, xếp hạng bằng ID, sửa ID sai; dữ liệu cuối lấy nguyên từ ứng viên; tối đa 6 model calls và 3 submissions |
| Planner | Tách chạy riêng từ adapter ADK hiện có; kiểm tra ứng viên trùng/rỗng; tool validation cho ngày, ID, thời gian; không gọi agent khác |

Weather/Budget/Memory là specialist xác định, không phải LLM tự trị. Cố tình không
gắn LLM vào phép cộng tiền, tính hạn dữ liệu hay quyết định quyền truy cập. Nếu cần
diễn giải bằng ngôn ngữ tự nhiên sau này, lớp LLM phải dùng kết quả này như tool;
không được tự thay các con số hoặc quyền người dùng.

## Chạy từng thành phần

Chạy từ thư mục travelmate, cài `uv sync --extra dev --extra ai` một lần.

```powershell
uv run --no-sync python -m app.specialists budget --input examples/budget.json
uv run --no-sync python -m app.specialists weather --input examples/weather.json
uv run --no-sync python -m app.specialists recommendation --input examples/recommendation.json
uv run --no-sync python -m app.specialists planner --input examples/planner.json
```

Budget mẫu có subtotal 1.800.000 VND nhưng trạng thái incomplete vì chưa có giá
di chuyển. Đây là số giả định do người dùng nhập, không phải báo giá ngoài đời.
Sửa ngày trong weather.json thành ngày hiện tại hoặc tương lai gần trước mỗi lần thử.
Recommendation/Planner cần GOOGLE_API_KEY trong .env, có thể phát sinh phí.
Ứng viên trong hai file mẫu là giả lập có nhãn; không được dùng để đi du lịch.

Memory chạy local với danh tính thử nghiệm rõ ràng:

```powershell
uv run --no-sync python -m app.specialists memory --user 11111111-1111-4111-8111-111111111111 --input examples/memory-read.json
uv run --no-sync python -m app.specialists memory --user 11111111-1111-4111-8111-111111111111 --input examples/memory-save.json
```

Lệnh save lưu sở thích mẫu khi confirmed=true. Lần lưu tiếp theo phải đọc version
hiện tại và cập nhật expected_version. Không retry mù khi có xung đột.
File agent-memory.sqlite3 được tạo local; không sửa database PostgreSQL hiện có.
CLI không xác thực người dùng: --user chỉ dành cho người vận hành local đáng tin.
Khi mở API, danh tính bắt buộc lấy từ authentication, tuyệt đối không nhận từ LLM/body.

## Kiểm thử và phạm vi xác minh

```powershell
uv run --no-sync pytest -q
uv run --no-sync ruff check app tests
```

Test ADK dùng scripted LLM nhưng Runner/tool thật. Weather dùng HTTP mock;
Memory dùng SQLite tạm thật. Không đánh đồng với kiểm thử Gemini/Google thật.
Kiểm thử budget bao gồm số thập phân, thiếu khoản và vượt ngân sách; memory bao gồm
consent, user isolation, persistence, version conflict, TTL và forget.

## Chưa hoàn thiện cho sản phẩm

- Chưa có đánh giá chất lượng LLM bằng bộ dữ liệu thực tế hay so sánh baseline.
- Planner chưa tối ưu tuyến đường, thời gian di chuyển hoặc giờ mở cửa.
- Recommendation chưa kiểm chứng semantic từng nhu cầu, không tạo điểm chất lượng giả.
- Weather yêu cầu tọa độ chính xác từ caller; không tự chọn một địa danh mơ hồ.
- Budget không tự lấy báo giá, đổi ngoại tệ hoặc chứng minh danh sách khoản đã đầy đủ.
- Memory chưa có PostgreSQL adapter, retrieval semantic hay lịch sử hội thoại.
- TTL được dọn khi truy cập; chưa có scheduled purge. Forget xóa payload logic,
  không đảm bảo xóa an toàn khỏi backup/journal/thiết bị. SQLite chưa mã hóa.
- Ghi SQLite chạy trong thread: hủy coroutine không đảm bảo rollback một transaction
  đã bắt đầu. Sau timeout phải đọc lại version trước khi gửi lại thao tác ghi.
- Chưa có API public, auth JWT, phân quyền, rate limiting, quota hoặc dashboard trace.

Các giới hạn này phải được xử lý/đánh giá trước khi gọi hệ thống hoàn chỉnh.

## Lần kiểm tra ngày 21/10/2026

- Chạy CLI Budget với dữ liệu mẫu: subtotal 1.800.000 VND, trạng thái incomplete đúng dự kiến.
- Gọi Open-Meteo thật cho tọa độ 16.0544,108.2022 và ngày 21–22/10/2026: nhận được hai ngày dự báo. Đây là smoke test kết nối, không xác nhận độ chính xác dự báo.
- Chưa gọi Gemini thật; Recommendation/Planner mới kiểm chứng vòng tool bằng scripted model.
