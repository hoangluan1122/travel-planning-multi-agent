# Tài liệu TravelMate

Tài liệu chia làm ba nhóm. Mới đọc lần đầu: xem [sản phẩm](san-pham/product-features.md) trước, rồi đến kiến trúc.

## Kiến trúc: các pattern agent trong dự án (`kien-truc/`)

| Tài liệu | Nói về |
|---|---|
| [multi-agent.md](kien-truc/multi-agent.md) | Trợ lý AI: lễ tân chuyển câu hỏi cho đúng chuyên gia (hand-off), Bài 08 |
| [planning-pattern.md](kien-truc/planning-pattern.md) | Lập lịch trình: AI chia việc, giao cho agent, tự lập lại kế hoạch, Bài 07 |
| [agentic-rag.md](kien-truc/agentic-rag.md) | Hướng dẫn viên trả lời có nguồn (Wikipedia, Wikivoyage, bảng giá vé), Bài 05 |
| [metacognition.md](kien-truc/metacognition.md) | Agent tự kiểm tra lịch trình và tự sửa, Bài 09 |
| [mcp-a2a.md](kien-truc/mcp-a2a.md) | Cho ứng dụng khác gọi TravelMate qua MCP và A2A, Bài 11 |
| [place-agent-standard.md](kien-truc/place-agent-standard.md) | Place Agent chấm theo chuẩn một agent đơn lẻ |

## Sản phẩm: chức năng và quy tắc (`san-pham/`)

| Tài liệu | Nói về |
|---|---|
| [product-features.md](san-pham/product-features.md) | Mọi màn hình, quy tắc nghiệp vụ (tài khoản, chuyến đi, chi phí, đánh giá), bảo mật, kiểm thử, giới hạn |

## Triển khai: đưa lên Internet (`trien-khai/`)

| Tài liệu | Nói về |
|---|---|
| [aws.md](trien-khai/aws.md) | Trang chính: máy AWS EC2 t3.micro, Docker + Caddy, tự cập nhật |
| [render.md](trien-khai/render.md) | Trang dự phòng: Render + Neon PostgreSQL, miễn phí; canh trang 3 giờ một lần |
