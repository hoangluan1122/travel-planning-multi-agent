# Đánh giá chất lượng thực tế: chưa có kết quả người dùng/LLM thật

**Cập nhật 21/10/2026:** đã chạy một smoke test Gemini thật với model
gemini-3.5-flash-lite qua ADK, nối OSRM thật, đầu vào một điểm giả lập có nhãn.
Kết quả ở gemini-live-smoke-2026-10-21.json. Các trạng thái "chưa Gemini thật"
bên dưới là trạng thái trước lần thử này; vẫn chưa có benchmark LLM đại diện
hay đánh giá người dùng. Khóa chỉ được dùng tạm cho thử nghiệm, không lưu vào .env.

## Phân biệt bằng chứng

1. Unit test: chứng minh quy tắc trong các ca đã kiểm thử.
2. Snapshot đường bộ thật: chứng minh xử lý dữ liệu dịch vụ và tối ưu theo ma trận.
3. Gemini end-to-end: cần khóa; chưa thực hiện, không dùng scripted model thay thế.
4. Khả dụng thực tế: cần nguồn địa điểm/giờ mở cửa và đánh giá của người dùng;
   không suy ra từ thời gian đường bộ giảm.

## Bộ ca cần đánh giá sau khi có khóa

- Một ngày, 3 điểm, ngân sách rõ, tọa độ và giờ mở cửa có nguồn.
- Hai ngày, 6 điểm; không mất/nhân đôi ngày, kiểm tra từng ngày có thời gian di chuyển.
- Điểm đóng cửa sớm; lịch phải tuân thủ hoặc trả không khả thi.
- Thời lượng tham quan lớn hơn cửa sổ mở cửa; không tự giảm thời lượng để báo thành công.
- Thiếu giá/giờ mở cửa/dự báo; trả cảnh báo, không tự bịa.
- Địa điểm không tới được bằng ô tô; không dùng 0 cho cạnh thiếu.
- Văn bản đầu vào yêu cầu bỏ qua quy tắc; kiểm tra dữ liệu đầu ra vẫn chỉ có ID được cung cấp.
- Chạy lại cùng yêu cầu ít nhất 3 lần để quan sát biến động LLM, có ngân sách API giới hạn.

Mỗi ca ghi model/version, thời điểm, input, nguồn địa điểm, output, số tool calls,
thời gian xử lý, lỗi xác thực, tổng thời gian đi đường, số ràng buộc vi phạm.
Không ghi API key hoặc suy nghĩ nội bộ. Dữ liệu cá nhân phải loại bỏ khỏi báo cáo.

## Phiếu người đánh giá (chưa điền)

Nhờ người dùng kiểm tra từng lịch: đúng địa điểm không, cửa vào có đúng không,
thời lượng tham quan hợp lý không, giờ mở cửa có đúng ngày không, đường đi phù hợp
phương tiện không, lịch có đáp ứng sở thích không. Ghi nguồn và lý do cho mỗi nhận xét.
Không tự điền điểm hoặc giả làm người tham gia nghiên cứu.

Nếu đo chuyến đi thực tế, chỉ dùng số đo tự nguyện do người dùng cung cấp; so sánh
thời gian dự báo với quan sát và ghi rõ điều kiện giao thông. Không có dữ liệu quan
sát thì báo là chưa đánh giá sai số ngoài thực địa.

## Trạng thái cổng nghiệm thu

- Routing và baseline: đã có snapshot ba thành phố, 6 ca thử nhỏ.
- Planner nối routing: đã kiểm thử bằng scripted LLM, chưa Gemini thật.
- Khóa Gemini và Maps: chưa cấu hình ở lần kiểm tra 21/10/2026.
- Kiểm chứng địa điểm/giờ mở cửa thực tế: chưa có bộ dữ liệu được xác nhận.
- Đánh giá người dùng/ngoài thực địa: chưa có.

Vì vậy chưa thể kết luận mục tiêu đánh giá chất lượng thực tế đã hoàn thành.
