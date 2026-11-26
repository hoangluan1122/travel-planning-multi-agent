# TravelMate

Backend FastAPI, các agent và giao diện thử nghiệm cho hệ thống lập kế hoạch du lịch.

## Cài đặt

Chạy các lệnh sau trong thư mục `travelmate`:

```powershell
uv sync --extra dev --extra maf --extra browser
```

Chỉ tạo `.env` từ `.env.example` khi cần cấu hình khóa API; không commit `.env`.

## Bản demo: lịch trình thật trên web

Nhập điểm đến trên web, nhận lịch trình từ **địa điểm thật** (OpenStreetMap/Photon),
**thời tiết thật** (Open-Meteo) và lịch do **Gemini** lập. Không cần Google Maps key.

1. Cài đặt: `uv sync --extra dev --extra maf --extra browser`
2. Tạo `.env` từ `.env.example`, rồi đặt:

   ```dotenv
   GOOGLE_API_KEY=<key Gemini của bạn>
   TRAVELMATE_API_TOKEN=<chuỗi ngẫu nhiên bất kỳ>
   TRAVELMATE_MODE=live
   TRAVELMATE_PLACE_PROVIDER=open_data
   TRAVELMATE_ORCHESTRATOR=planning
   TRAVELMATE_AGENT_TIMEOUT=120
   ```

3. Chạy `uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000`
4. Mở http://127.0.0.1:8000/, **Đăng ký** một tài khoản rồi **Tạo chuyến đi**. Lịch trình được
   tạo nền, trang hiện từng bước; một lịch 2–3 ngày thường mất 25–40 giây. Muốn dùng `TRAVELMATE_API_TOKEN` thay cho tài khoản, mở trang với `?dev`
   (ví dụ `http://127.0.0.1:8000/?dev`) để hiện mục **Cấu hình kết nối**.

Kết quả: từng ngày có khung giờ, loại địa điểm, địa chỉ, link bản đồ OpenStreetMap, dự báo
thời tiết, ảnh (Wikipedia/Wikimedia; quán ăn dùng ảnh minh hoạ món, có ghi rõ) và nơi ở gần đó;
chi phí chưa biết được liệt kê theo tên, không coi là 0. Giới hạn: tên trùng (ví dụ "Hội An") tự
chọn địa danh khớp nhất và báo rõ trong cảnh báo; chưa có giờ mở cửa, tuyến đường thật giữa các
điểm hay đặt chỗ; nơi ở hầu như chưa có ảnh; lịch có thể lặp lại quán ăn khi nguồn có ít lựa chọn.

## Trợ lý AI (Multi-Agent, hand-off)

Màn hình **Trợ lý AI** (`?view=chat`) gọi `POST /api/v1/chat`: một trợ lý điều phối đọc câu hỏi
rồi chuyển cho chuyên gia địa điểm, lịch trình, chi phí hoặc thời tiết, nhớ thông tin chuyến đi
qua các lượt. Chi tiết và kết quả chạy thật: [`docs/multi-agent.md`](../docs/multi-agent.md).

Câu hỏi về một địa danh (lịch sử, giá vé, giờ mở cửa, đi lại) đi tới **Hướng dẫn viên**
(Agentic RAG): agent tự tìm trong Wikipedia, Wikivoyage và bảng giá vé, trả lời kèm nguồn, và
không được ghi con số nào không có trong nguồn. Xem [`docs/agentic-rag.md`](../docs/agentic-rag.md).

## Đưa lên Internet

Trang chạy ở `/` (địa chỉ cũ `/ui/travelmate-v2/index.html` tự chuyển về). Có sẵn các trang Giới thiệu,
Bảng giá, Liên hệ (tin nhắn vào **Quản trị → Liên hệ**), Điều khoản sử dụng, Chính sách bảo mật;
`robots.txt`, `sitemap.xml`, thẻ chia sẻ (Open Graph) và header bảo mật. Mỗi tài khoản có hạn mức AI
mỗi ngày (`TRAVELMATE_DAILY_PLANS`, `TRAVELMATE_DAILY_CHATS`) để khoá Gemini miễn phí không bị một người
dùng hết. Triển khai miễn phí bằng Render + Neon với `render.yaml` và `travelmate/Dockerfile`; GitHub Actions chạy test cho mỗi PR, Render chỉ deploy khi CI qua, và cứ 3 giờ một lần kiểm tra trang đang chạy (hỏng thì gửi email):
[`docs/deploy.md`](../docs/deploy.md). Trang chính chạy trên một máy AWS EC2 t3.micro (Docker + Caddy,
tự kéo image mới sau mỗi lần CI đạt), Render giữ làm dự phòng: [`docs/deploy-aws.md`](../docs/deploy-aws.md).

## Tài khoản và nghiệp vụ

Đăng ký/đăng nhập, chuyến đi lưu theo tài khoản (sửa được), địa điểm yêu thích, trang địa điểm,
đánh giá có kiểm duyệt và khu vực quản trị. Dữ liệu nằm trong PostgreSQL (`TRAVELMATE_DATABASE_URL`,
cần extra `postgres`) hoặc SQLite (`TRAVELMATE_DB`) khi không đặt URL; đặt
`TRAVELMATE_ADMIN_EMAIL` để tài khoản đăng ký bằng email đó là quản trị viên. Chi tiết:
[`docs/product-features.md`](../docs/product-features.md).

## MCP và A2A

- **MCP:** `uv run python -m app.protocols.mcp_server` mở các tool `search_places`, `weather_forecast`,
  `ask_guide`, `plan_trip` cho Claude Desktop và các client MCP khác (cần extra `mcp`).
- **A2A 1.0:** API ở cổng 8000 có Agent Card tại `/.well-known/agent-card.json` và endpoint
  JSON-RPC `/a2a` (`SendMessage`, `GetTask`), để agent khác giao việc cho TravelMate.

Chi tiết, cấu hình Claude Desktop và kết quả chạy thử: [`docs/mcp-a2a.md`](../docs/mcp-a2a.md).

## Place Agent — dữ liệu thật

```powershell
uv run uvicorn app.place_agent.live_api:create_app --factory --host 127.0.0.1 --port 8001
```

Mở http://127.0.0.1:8001/. Hỗ trợ tìm lưu trú, ăn uống và tham quan qua
GeoNames/Open-Meteo và Photon/OpenStreetMap; chọn địa danh, bán kính, khu vực,
phân trang và tải JSON. Không cần khóa Google Maps cho giao diện này.

Khi tên trùng nhau, chọn đúng địa danh và loại thực thể. Với khu du lịch lớn,
điểm nguồn có thể là tâm hình học. Nút mở rộng bán kính cần người dùng bấm xác nhận.
Mặc định chạy workflow công cụ; chế độ LLM (`LIVE_PLACE_MODE=maf_llm`) là tùy chọn, cần `GOOGLE_API_KEY`.

## API lịch trình thử nghiệm

```powershell
uv run uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

Mở http://127.0.0.1:8000/docs. `.env.example` mặc định `TRAVELMATE_MODE=demo`:
endpoint demo dùng dữ liệu giả lập có nhãn. Cấu hình `live` cần khóa API tương ứng.

## Khung chạy agent: Microsoft Agent Framework

Mọi agent dùng LLM (lễ tân Trợ lý AI, Planning Agent, hướng dẫn viên, planner, recommendation,
Place Agent) chạy trên Microsoft Agent Framework (MAF) với Gemini; cài bằng `--extra maf`. Google ADK
đã được gỡ khỏi dự án (11/2026). Mỗi agent định nghĩa tool và điều kiện chấp nhận một lần;
`app/core/llm/tool_loop.py` chạy vòng lặp đó.

MAF mặc định trả lỗi tool về cho model, gọi thêm một lượt khi chạm giới hạn vòng lặp và
chỉ dừng sớm khi tín hiệu đến từ middleware. `tool_loop.py` thêm hai middleware để có đủ ba đảm
bảo: lỗi ngân sách của tool dừng cả lượt chạy, không vượt số lần gọi model, và dừng ngay khi bài nộp
được chấp nhận.

### Orchestrator dạng MAF Workflow

API lịch trình có ba cách điều phối, chọn bằng `TRAVELMATE_ORCHESTRATOR` (xem `app/services.py`):
`classic` (mặc định, `app/agents/orchestrator.py`), `workflow` (`app/agents/workflow_orchestrator.py`)
hoặc `planning` (`app/agents/planning.py`: LLM chia việc và lập kế hoạch lại khi thiếu; bản chạy trên
Render dùng cách này). Bản workflow là đồ thị executor của MAF:

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

## Trace

**Trace (OpenTelemetry).** Đặt `TRAVELMATE_TELEMETRY=console` (in ra terminal) hoặc `otlp`
(gửi tới `OTEL_EXPORTER_OTLP_ENDPOINT`, ví dụ Jaeger hoặc Aspire Dashboard); cần extra `maf` và
`telemetry`.
Mỗi lần agent chạy có một span `agent <tên>` kèm `request_id` và kết quả; span của MAF
(`invoke_agent`, `chat`, `execute_tool`) nằm lồng bên trong, nên một request là một trace.
Không xuất nội dung prompt, tham số hay kết quả tool: chế độ sensitive luôn tắt.

## Cấu trúc

`app/` được chia theo các phần của một agent: model, context, memory, tools, trust. Muốn
đọc một agent, bắt đầu từ `app/agents/`. Muốn biết agent chạy trong khung nào, xem
`app/core/base.py`.

```text
app/
├─ main.py                 Máy chủ FastAPI: chỉ ghép các phần dưới lại (lệnh chạy không đổi)
├─ settings.py             Mọi cấu hình đọc từ biến môi trường / .env, có giải thích từng mục
├─ services.py             Dựng agent và nguồn dữ liệu theo cấu hình (demo/live, nguồn địa điểm, orchestrator)
├─ api/                    Các endpoint, mỗi file một nhóm
│  ├─ plans.py             Tìm địa điểm, tạo lịch trình (chạy nền) và xem tiến độ
│  ├─ chat.py              Trợ lý AI
│  ├─ site.py              Trang web, robots.txt, sitemap.xml, /health, header bảo mật
│  └─ deps.py              Ai đang gọi (token, đăng nhập), hạn mức AI mỗi ngày
├─ core/                   Khung chung cho mọi agent
│  ├─ base.py              BaseAgent: kiểm tra đầu vào/ra, giới hạn thời gian, log, telemetry
│  ├─ models.py            Schema (Pydantic): TripRequest, Context, PlanResponse, BudgetResult…
│  ├─ telemetry.py         OpenTelemetry (bật khi cần)
│  └─ llm/                 MODEL: Gemini qua Microsoft Agent Framework
│     ├─ tool_loop.py      Vòng gọi công cụ có giới hạn số lần gọi model
│     ├─ maf_clients.py    Tạo client Gemini cho MAF
│     └─ maf_adapter.py    Agent xếp lịch từng ngày (MafPlanner)
├─ agents/                 Các agent
│  ├─ concierge.py         Trợ lý điều phối trong chat, chuyển cho chuyên gia (Multi-Agent)
│  ├─ planning.py          Planning Agent: chia việc, giao việc, lập kế hoạch lại
│  ├─ orchestrator.py, workflow_orchestrator.py   Hai cách chạy chuỗi agent lập lịch
│  ├─ place.py, weather.py, recommendation.py     Địa điểm, thời tiết, xếp hạng theo sở thích
│  ├─ itinerary.py, itinerary_tools.py           Xếp lịch từng ngày và công cụ của nó
│  ├─ budget.py            Chi phí cả chuyến, so với ngân sách, gợi ý tiết kiệm
│  ├─ guide.py             Hướng dẫn viên (Agentic RAG, trả lời có nguồn)
│  ├─ self_check.py        Tự kiểm tra lịch (Metacognition)
│  └─ rule_scheduler.py    Xếp lịch theo luật khi model lỗi
├─ memory/                 MEMORY
│  ├─ store.py             Cơ sở dữ liệu (SQLite/PostgreSQL): tài khoản, chuyến đi, chat, đánh giá
│  └─ preferences.py       Memory Agent: đọc sở thích đã lưu (chỉ đọc)
├─ tools/                  TOOLS: nguồn dữ liệu agent gọi, không tự quyết định
│  ├─ places/              OpenStreetMap/Photon, Wikipedia, vùng hành chính, ảnh, website chính thức;
│  │                       provider_wrappers.py: lưu kết quả tìm 24 giờ, ẩn địa điểm admin đã ẩn
│  ├─ browser_weather/     Đọc thời tiết từ trình duyệt
│  ├─ prices/              Bảng giá vé và giá tham khảo có nguồn
│  └─ http.py              Gọi HTTP có thử lại
├─ trust/                  TRUST
│  ├─ accounts.py          Đăng nhập (cookie HttpOnly, CSRF), quyền sở hữu, admin, đánh giá
│  └─ mailer.py            Gửi email đặt lại mật khẩu
├─ protocols/              mcp_server.py (MCP), a2a.py (A2A), summaries.py
├─ specialists/            Bàn thử từng chuyên gia riêng lẻ (api.py, `python -m app.specialists`)
├─ place_agent/            Ứng dụng Place Agent độc lập (cổng 8001)
├─ evaluation/             Bộ đánh giá dùng trong test và scripts/
└─ data/                   Bảng giá vé, giá tham khảo, ranh giới hành chính (JSON)
```

Ngoài `app/`:

- `frontend/`: giao diện web (`travelmate-v2` là bản chính).
- `tests/`: kiểm thử tự động, gồm cả kiểm thử giao diện trên trình duyệt.
- `scripts/`: chạy đánh giá, nhập dữ liệu, gọi thử MCP/A2A.
- `evaluation/`: phản hồi API, bằng chứng HTTP và kết quả kiểm thử.
- `examples/`: đầu vào mẫu để chạy thử.

## Kiểm thử

```powershell
uv run --no-sync pytest -q
```

Lần kiểm tra ngày 16/11/2026: **837 passed, 22 skipped**. Các test bị bỏ qua cần PostgreSQL;
GitHub Actions chạy chúng với PostgreSQL thật cho mỗi PR. `uv run ruff check app scripts tests`
kiểm tra kiểu viết.

**Đánh giá Trợ lý AI trên Gemini thật** (chạy tay, tốn lượt Gemini miễn phí): 42 hội thoại mẫu chia 9 nhóm
(giao tiếp, tìm địa điểm, hướng dẫn viên, thời tiết, lập lịch và chi phí, câu ghép, ngoài phạm vi, an toàn,
ngôn ngữ) trong `app/evaluation/assistant_cases.json`, mỗi câu có tiêu chí chấm tự động.

```powershell
uv run python scripts/eval_assistant.py            # toàn bộ; --only guide để chạy một nhóm
```

Báo cáo ghi vào `evaluation/assistant-eval-<UTC>/`. Câu hỏng được chạy lại một lần sau 65 giây để tách lỗi
tạm thời của nguồn miễn phí khỏi câu trả lời sai. Lần chạy 23/11/2026: 42/42 đạt (1 câu đạt ở lần chạy lại).

Bằng chứng các lần đo dữ liệu thật trước đây nằm trong `evaluation/` (ví dụ
`evaluation/fix-verification-20261022T182826Z/`).

Chưa xác minh mọi điểm đến Việt Nam. Tràng An còn cần kiểm tra nguồn đúng quần thể
khu du lịch; Sầm Sơn cần kiểm tra sai số polygon tham chiếu. Giá, phòng trống,
ảnh được cấp quyền và trạng thái đang hoạt động chưa được xác minh đầy đủ.
Tích hợp workflow multi-agent và sản phẩm hoàn chỉnh vẫn đang phát triển.

## Nguồn dữ liệu

Thông tin nguồn, phiên bản ranh giới và điều kiện sử dụng được giữ trong
[`app/data/README.md`](app/data/README.md). Dữ liệu OpenStreetMap thuộc các cộng tác viên,
được cung cấp theo [ODbL](https://www.openstreetmap.org/copyright).
