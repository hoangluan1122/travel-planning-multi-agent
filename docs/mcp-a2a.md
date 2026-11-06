# MCP và A2A (Bài 11) trong TravelMate

Hai giao thức, hai vai trò:

| | MCP (Model Context Protocol) | A2A (Agent-to-Agent) |
|---|---|---|
| TravelMate đóng vai | **Hộp công cụ** cho agent/ứng dụng khác | **Một agent** để agent khác giao việc |
| Đơn vị trao đổi | Lời gọi tool (tham số có schema, kết quả JSON) | Task gồm nhiều message, có trạng thái |
| Mã | `travelmate/app/protocols/mcp_server.py` | `travelmate/app/protocols/a2a.py` (gắn vào API ở cổng 8000) |
| Client thử | `scripts/mcp_client.py` | `scripts/a2a_client.py` |

API, MCP và A2A dùng chung các dịch vụ (`build_services` trong `app/main.py`): cùng nguồn dữ
liệu, cùng orchestrator, cùng các chuyên gia.

## MCP server

**4 tool + 1 resource:**

- `search_places(destination, category, keyword, limit)`: địa điểm thật (OSM/Photon), kèm giá vé
  có nguồn nếu có. Điểm tham quan tìm trong 10 km vì lăng tẩm ở Huế xa trung tâm.
- `weather_forecast(destination, start_date, end_date)`: dự báo Open-Meteo.
- `ask_guide(question, destination)`: Hướng dẫn viên Agentic RAG, trả lời kèm trích dẫn.
- `plan_trip(destination, start_date, end_date, travelers, budget_vnd, interests, notes)`: toàn bộ
  pipeline lập lịch (Planning + Metacognition).
- Resource `travelmate://tickets`: bảng giá vé có nguồn.

Tham số có mô tả và ràng buộc (enum, min/max) trong JSON Schema để model gọi đúng. Lỗi trả về
một câu ngắn (“Invalid input: …”, “retry shortly”), không lộ URL nguồn, khoá hay traceback.

**Chạy:**

```bash
uv sync --extra mcp   # một lần (đã có sẵn nếu cài extra ai)
uv run python -m app.protocols.mcp_server
```

Lệnh trên chạy qua stdio. Muốn chạy Streamable HTTP ở `http://127.0.0.1:8765/mcp`, thêm
`--http --port 8765`.

**Dùng trong Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "travelmate": {
      "command": "uv",
      "args": ["run", "--directory", "C:/đường/dẫn/travel-planning-multi-agent/travelmate",
               "python", "-m", "app.protocols.mcp_server"]
    }
  }
}
```

Server đọc cùng `.env` với API. Chạy qua stdio thì telemetry console bị tắt, vì nó sẽ ghi vào
stdout và làm hỏng luồng MCP.

## A2A agent (A2A 1.0, JSON-RPC)

- `GET /.well-known/agent-card.json`: Agent Card công khai, gồm 5 skill (`find_places`,
  `plan_trip`, `trip_costs`, `weather`, `travel_guide`), endpoint
  `supportedInterfaces[0] = {url: …/a2a, protocolBinding: "JSONRPC", protocolVersion: "1.0"}` và
  `securitySchemes` Bearer khi server đặt token.
- `POST /a2a`: JSON-RPC 2.0 với `SendMessage` và `GetTask`.

Mỗi `SendMessage` là một lượt chat với trợ lý điều phối. `contextId` của A2A chính là phiên chat,
nên agent khác có thể mô tả chuyến đi qua nhiều tin nhắn:

```text
SendMessage "Lên lịch trình đi Huế"                  → task T1: TASK_STATE_INPUT_REQUIRED (hỏi ngày, số người, ngân sách)
SendMessage {taskId: T1} "08/11–09/11, 2 người, 5 triệu" → task T1: TASK_STATE_COMPLETED + artifact "plan" (JSON)
SendMessage {contextId} "Chùa Thiên Mụ có gì hay?"   → task T2: TASK_STATE_COMPLETED + artifact "citations"
```

- Kết quả dạng dữ liệu (địa điểm, lịch trình, trích dẫn) trả về thành artifact
  `{"data": …, "mediaType": "application/json"}`. Câu trả lời chữ nằm trong `status.message`, có
  `metadata.specialist` cho biết chuyên gia nào trả lời.
- Chuyên gia lỗi thì trả `TASK_STATE_FAILED`.
- Mã lỗi theo spec: `-32001` không tìm thấy task, `-32004` thao tác chưa hỗ trợ (streaming, push,
  huỷ task), `-32602` tham số sai, `-32601` method lạ. Header `A2A-Version` khác `1.0` thì trả
  HTTP 400 `application/problem+json` kèm `supportedVersions`.
- Agent Card công khai; `/a2a` cần `Authorization: Bearer <TRAVELMATE_API_TOKEN>` khi server đặt token.

## Kết quả chạy thử (05/11/2026)

- **MCP qua stdio** (`scripts/mcp_client.py`, giống cách Claude Desktop khởi chạy): đủ 4 tool và
  resource. `weather_forecast` trả dự báo Huế 3 ngày (mưa phùn). `ask_guide` trả giá vé lăng Tự Đức
  150.000 ₫ có nguồn Tuổi Trẻ. `search_places` chạy đúng giao thức; riêng tìm theo từ khoá
  (“tomb”, “lăng”) cho kết quả kém, đây là hạn chế của Photon/OSM chứ không phải của MCP.
- **A2A** (`scripts/a2a_client.py` gọi server live):
  - Đọc được Agent Card.
  - Lượt 1 ra `INPUT_REQUIRED`; lượt 2 tiếp tục đúng task đó.
  - Câu hỏi Chùa Thiên Mụ ra `COMPLETED`, kèm artifact trích dẫn Wikipedia.
- Lúc chạy thử, Gemini miễn phí đã hết hạn mức trong ngày (429). Vì vậy lượt lập lịch thất bại,
  và Hướng dẫn viên chuyển sang trích nguyên văn nguồn. Sau lượt này đã sửa hai điểm:
  - Hướng dẫn viên tự chuyển sang trích nguồn khi model lỗi bất kỳ.
  - Chuyên gia lỗi thì task báo `FAILED` thay vì `INPUT_REQUIRED`.

  Luồng lập lịch đầy đủ qua A2A với Gemini chưa chạy lại được trong ngày; trong test tự động
  (chế độ demo), luồng này đạt.

## Giới hạn

- MCP qua HTTP chưa có xác thực, chỉ nghe ở `127.0.0.1`; đừng mở ra mạng ngoài.
- A2A chưa hỗ trợ streaming (`SendStreamingMessage`), push notification, huỷ hay liệt kê task.
  Task và phiên lưu trong bộ nhớ.
- `plan_trip` (MCP) và lượt lập lịch (A2A) chạy đồng bộ 30–120 giây; client cần timeout đủ dài.
- Agent Card chưa có `securityRequirements` và chữ ký (signature) của A2A 1.0.
