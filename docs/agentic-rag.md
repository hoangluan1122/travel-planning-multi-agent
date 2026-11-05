# Agentic RAG (Bài 05) trong TravelMate: Hướng dẫn viên có nguồn

Mã: `travelmate/app/knowledge.py`. Trong **Trợ lý AI**, câu hỏi về một địa danh hay thành phố
(lịch sử, có gì hay, giá vé, giờ mở cửa, đi lại, kinh nghiệm) được chuyển cho chuyên gia
`guide_advisor` (“Hướng dẫn viên”).

## Nguồn (miễn phí, có trích dẫn)

| Nguồn | Dùng cho |
|---|---|
| Wikipedia tiếng Việt (tiếng Anh nếu không có bài) | Lịch sử, mô tả địa danh |
| Wikivoyage tiếng Anh | Kinh nghiệm: tham quan, đi lại, ăn uống, giá taxi… |
| Bảng giá vé `app/data/ticket_prices.json` | Giá vé có nguồn báo chí/chính thức và ngày kiểm tra |

Trang được cắt thành đoạn ngắn (≤ 700 ký tự). Mỗi đoạn mang tiêu đề mục ở đầu (ví dụ
“Get around › By taxi: …”). Phần “Tham khảo / Liên kết ngoài” bị bỏ. Đoạn được xếp theo độ trùng
từ với câu hỏi; đoạn không khớp tiêu đề và cũng không trùng ít nhất hai từ thì bị loại.

## Phần “agentic”

LLM không nhận sẵn tài liệu mà tự đi tìm:

1. `search_knowledge(query, source)`: agent tự chọn từ khoá và nguồn (hỏi giá thì tra bảng vé
   trước), đọc đoạn tìm được, thấy chưa đủ thì tìm lại bằng từ khoá, ngôn ngữ hoặc nguồn khác.
   Tối đa 4 lượt tìm mới. Lượt tìm trùng trả lại kết quả cũ và không bị tính, để khi Gemini lỗi
   và vòng lặp chạy lại, agent vẫn thấy những gì đã tìm.
2. `submit_answer`: câu trả lời đi qua **submit gate** và chỉ được nhận khi
   - mọi trích dẫn là id của đoạn đã thực sự tìm được trong lượt này;
   - trạng thái `answered`/`partial` có ít nhất một trích dẫn;
   - **mọi con số** trong câu trả lời (giá, năm, giờ) có trong đoạn được trích dẫn. Nhờ vậy giá vé
     và giờ mở cửa không thể bịa.

   Không đạt thì agent nhận danh sách lỗi để sửa.
3. Nguồn không có thông tin (ví dụ giờ mở cửa) thì agent phải nói rõ và trả `partial`.

**Dự phòng:** không có LLM (chế độ demo) hoặc agent không nộp được câu trả lời hợp lệ thì trả
nguyên văn hai đoạn tốt nhất kèm nguồn, có ghi chú “Trích nguyên văn”. Câu hỏi được rút gọn thành
chủ đề trước khi tìm (“Lăng Tự Đức có gì đặc biệt?” → “Lăng Tự Đức”).

## Kết quả chạy thật (MAF, Gemini)

| Câu hỏi | Kết quả |
|---|---|
| Lăng Tự Đức có gì đặc biệt, giá vé bao nhiêu? | Xây 1864–1867, cảnh quan hồ và điện thờ; vé 150.000 ₫ người lớn, 30.000 ₫ trẻ 7–12 tuổi. Nguồn: bảng vé (Tuổi Trẻ) và Wikivoyage |
| ở đó nên đi buổi nào? (câu tiếp theo) | Concierge tự hiểu “ở đó” là Lăng Tự Đức; nguồn không nói nên đi buổi nào và agent nói rõ điều đó |
| Đi lại trong Huế bằng gì tiện? | Taxi (mở cửa 15.000 đồng 2 km đầu), xe máy, xích lô (thoả thuận giá trước), xe máy kèm tài xế khoảng 10 USD/ngày; chưa có thông tin xe buýt |
| Đi taxi từ trung tâm Huế ra lăng hết bao nhiêu? | Khoảng 300.000 đồng cho hai lăng kèm thời gian chờ (Wikivoyage) |
| Chùa Cầu Hội An mở cửa mấy giờ? | Nguồn không có giờ mở cửa; vé phố cổ 80.000–120.000 ₫ (`partial`) |
| Chùa Thiên Mụ có gì hay? | Biểu tượng của Huế, nhìn ra sông Hương, có chiếc xe của hoà thượng Thích Quảng Đức, vào cửa miễn phí |

Trong lúc chạy thử, mình đã sửa ba lỗi:
- Lượt tìm của lần chạy lỗi bị tính vào ngân sách, khiến agent hết lượt tìm.
- Mất tiêu đề mục nên câu hỏi về đi lại không khớp mục “Get around”.
- Bảng vé khớp theo tên thành phố của chuyến đi, nên hỏi “Đà Lạt” lại ra vé Huế.

## Giới hạn

- Wikivoyage tiếng Anh và Wikipedia có thể cũ hoặc thiếu (đặc biệt giờ mở cửa); câu trả lời chỉ
  đúng bằng nguồn.
- Xếp hạng đoạn dùng trùng từ, chưa có embedding; câu hỏi diễn đạt khác hẳn nguồn có thể trượt.
- Gemini miễn phí hay quá tải (503/429): lượt trả lời chậm hơn hoặc chuyển sang trích nguyên văn.
- Kiểm tra số chỉ bảo đảm con số có trong nguồn được trích, chưa bảo đảm đúng ngữ cảnh.
