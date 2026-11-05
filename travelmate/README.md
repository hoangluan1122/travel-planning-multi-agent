# TravelMate

Backend FastAPI, các agent và giao diện thử nghiệm cho hệ thống lập kế hoạch du lịch.

## Cài đặt

Chạy các lệnh sau trong thư mục `travelmate`:

```powershell
uv sync --extra dev --extra ai --extra browser
```

Chỉ tạo `.env` từ `.env.example` khi cần cấu hình khóa API; không commit `.env`.

## Bản demo: lịch trình thật trên web

Nhập điểm đến trên web, nhận lịch trình từ **địa điểm thật** (OpenStreetMap/Photon),
**thời tiết thật** (Open-Meteo) và lịch do **Gemini** lập. Không cần Google Maps key.

1. Cài đặt: `uv sync --extra dev --extra ai --extra browser --extra maf`
2. Tạo `.env` từ `.env.example`, rồi đặt:

   ```dotenv
   GOOGLE_API_KEY=<key Gemini của bạn>
   TRAVELMATE_API_TOKEN=<chuỗi ngẫu nhiên bất kỳ>
   TRAVELMATE_MODE=live
   TRAVELMATE_PLACE_PROVIDER=open_data
   AGENT_ENGINE=maf
   TRAVELMATE_ORCHESTRATOR=workflow
   TRAVELMATE_AGENT_TIMEOUT=120
   ```

3. Chạy `uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000`
4. Mở http://127.0.0.1:8000/, vào **Cấu hình kết nối** nhập đúng `TRAVELMATE_API_TOKEN`,
   rồi **Bắt đầu hành trình**. Một lịch 2 ngày mất khoảng 1 phút.

Kết quả: từng ngày có khung giờ, loại địa điểm, địa chỉ, link bản đồ OpenStreetMap, dự báo
thời tiết; chi phí chưa biết được liệt kê theo tên, không coi là 0. Giới hạn của bản demo:
tên trùng (ví dụ "Hội An") tự chọn địa danh khớp nhất và báo rõ trong cảnh báo; chỉ lấy địa
điểm trong 5 km quanh trung tâm (8 điểm tham quan, 4 quán ăn); chưa có giá, giờ mở cửa, ảnh,
tuyến đường thật giữa các điểm, lưu trú, đặt chỗ hay tài khoản người dùng; lịch có thể lặp
lại quán ăn khi nguồn có ít lựa chọn.

## Place Agent — dữ liệu thật

```powershell
uv run uvicorn app.live_place_api:create_app --factory --host 127.0.0.1 --port 8001
```

Mở http://127.0.0.1:8001/. Hỗ trợ tìm lưu trú, ăn uống và tham quan qua
GeoNames/Open-Meteo và Photon/OpenStreetMap; chọn địa danh, bán kính, khu vực,
phân trang và tải JSON. Không cần khóa Google Maps cho giao diện này.

Khi tên trùng nhau, chọn đúng địa danh và loại thực thể. Với khu du lịch lớn,
điểm nguồn có thể là tâm hình học. Nút mở rộng bán kính cần người dùng bấm xác nhận.
Mặc định chạy workflow công cụ; ADK/LLM là chế độ tùy chọn cần cấu hình riêng.

## API lịch trình thử nghiệm

```powershell
uv run uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

Mở http://127.0.0.1:8000/docs. `.env.example` mặc định `TRAVELMATE_MODE=demo`:
endpoint demo dùng dữ liệu giả lập có nhãn. Cấu hình `live` cần khóa API tương ứng.

## Engine agent: ADK hoặc Microsoft Agent Framework

Các agent dùng LLM (planner, routed planner, recommendation, Place Agent) chạy được bằng
Google ADK (mặc định) hoặc Microsoft Agent Framework (MAF). Mỗi agent định nghĩa tool và
điều kiện chấp nhận một lần; `app/tool_loop.py` chạy vòng lặp đó trên engine được chọn.
Để dùng MAF:

```powershell
uv sync --extra dev --extra ai --extra browser --extra maf
```

rồi đặt `AGENT_ENGINE=maf` trong `.env` (`PLANNER_ENGINE` cũ vẫn được nhận). Giao diện
Place Agent dữ liệu thật dùng `LIVE_PLACE_MODE=maf_llm`.

MAF mặc định trả lỗi tool về cho model, gọi thêm một lượt khi chạm giới hạn vòng lặp và
chỉ dừng sớm khi tín hiệu đến từ middleware. `app/tool_loop.py` xử lý cả ba để ngân sách
tool, ngân sách gọi model và điểm dừng sau khi chấp nhận giống hệt ADK.

### Orchestrator dạng MAF Workflow

API lịch trình (`app.main`) có hai cách điều phối, chọn bằng `TRAVELMATE_ORCHESTRATOR`:
`classic` (mặc định, `app/orchestrator.py`) hoặc `workflow` (`app/workflow_orchestrator.py`).
Bản workflow là đồ thị executor của MAF:

```text
memory ──► place ───┐
      └──► weather ─┴─► recommendation ─► planner ─► validate ─► budget ─► PlanResponse
```

`place` và `weather` chạy song song (fan-out), `recommendation` chờ cả hai (fan-in). Hai
bản dùng chung quy tắc từng bước (`checked_places`, `checked_weather`, `validate_draft`,
`plan_response`), nên cho cùng kết quả và cùng lỗi với cùng đầu vào. Bản workflow nhận
`checkpoint_storage` tùy chọn để lưu checkpoint sau mỗi superstep.

## Sở thích đã lưu trong luồng lập lịch

Khi đặt `TRAVELMATE_MEMORY_USER` (UUID do host xác thực) và `TRAVELMATE_MEMORY_DB`, API lịch
trình đọc sở thích đã lưu của danh tính đó, gộp sau sở thích trong request (bỏ trùng, tối đa
20), dùng cho xếp hạng gợi ý và đưa cho planner. Response có cảnh báo liệt kê sở thích đã dùng.

- **Chỉ đọc:** luồng lập lịch không bao giờ ghi memory. Lưu/xóa đi qua memory specialist
  (`/api/v1/agents/memory`), bắt buộc `confirmed=true`.
- **Không chọn danh tính từ request:** host cấu hình danh tính; request không thể đọc memory
  của người khác.
- **Là dữ liệu, không phải chỉ thị:** sở thích đến planner LLM qua kết quả `inspect_trip`, không
  được chèn vào system prompt, nên nội dung đã lưu không thể đóng vai lệnh (memory poisoning).
- **Không chặn kế hoạch:** memory hết hạn, đã xóa hoặc không đọc được thì chỉ dùng sở thích
  trong request, kèm cảnh báo.

## Trace và so sánh engine

**Trace (OpenTelemetry).** Đặt `TRAVELMATE_TELEMETRY=console` (in ra terminal) hoặc `otlp`
(gửi tới `OTEL_EXPORTER_OTLP_ENDPOINT`, ví dụ Jaeger hoặc Aspire Dashboard); cần extra `maf`.
Mỗi lần agent chạy có một span `agent <tên>` kèm `request_id` và kết quả; span của MAF
(`invoke_agent`, `chat`, `execute_tool`) nằm lồng bên trong, nên một request là một trace.
Không xuất nội dung prompt, tham số hay kết quả tool: chế độ sensitive luôn tắt.

**So sánh ADK và MAF trên Gemini thật** (tốn token, cần `GOOGLE_API_KEY`):

```powershell
uv sync --extra dev --extra ai --extra maf
uv run python scripts/compare_engines.py --runs 3
```

Script cho cả hai engine lập lịch cùng đầu vào qua cùng submit gate, rồi ghi tỷ lệ được chấp
nhận, loại lỗi và thời gian vào `evaluation/engine-comparison-<UTC>/`.

## Cấu trúc

- `app/`: API, schema, agent, provider và công cụ.
- `frontend/`: các giao diện thử nghiệm.
- `tests/`: kiểm thử tự động và fixture hồi quy.
- `scripts/`: nhập dữ liệu tham chiếu và kiểm tra nguồn thật.
- `evaluation/`: phản hồi API, bằng chứng HTTP và kết quả kiểm thử.
- `examples/`: đầu vào/ví dụ chạy thử.

## Kiểm thử

```powershell
uv run --no-sync pytest -q
```

Lần kiểm tra ngày 23/10/2026: **513 passed**, 1 cảnh báo deprecation TestClient.
Kiểm tra giao diện đạt. 15 lượt thử dữ liệu thật sau sửa có 14 lượt trả bản ghi
trong 5 km; khách sạn Fansipan trả rỗng trong 5 km và có 5 bản ghi khi thử 10 km.

Bằng chứng: `evaluation/fix-verification-20261022T182826Z/` và
`evaluation/fix-verification-20261022T183050Z/`.

Chưa xác minh mọi điểm đến Việt Nam. Tràng An còn cần kiểm tra nguồn đúng quần thể
khu du lịch; Sầm Sơn cần kiểm tra sai số polygon tham chiếu. Giá, phòng trống,
ảnh được cấp quyền và trạng thái đang hoạt động chưa được xác minh đầy đủ.
Tích hợp workflow multi-agent và sản phẩm hoàn chỉnh vẫn đang phát triển.

## Nguồn dữ liệu

Thông tin nguồn, phiên bản ranh giới và điều kiện sử dụng được giữ trong
[`app/data/README.md`](app/data/README.md). Dữ liệu OpenStreetMap thuộc các cộng tác viên,
được cung cấp theo [ODbL](https://www.openstreetmap.org/copyright).
