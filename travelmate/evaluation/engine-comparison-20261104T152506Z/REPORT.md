# So sánh engine: ADK vs MAF (model `gemini-3.5-flash-lite`)

## Tổng

| Engine | Lượt chạy | Được chấp nhận | Tỷ lệ | Trung vị (ms) | Lâu nhất (ms) | Lỗi |
|---|---|---|---|---|---|---|
| adk | 9 | 9 | 100% | 44562 | 65250 | — |
| maf | 9 | 9 | 100% | 55485 | 70593 | — |

## Theo đầu vào

| Đầu vào · engine | Lượt chạy | Được chấp nhận | Tỷ lệ | Trung vị (ms) | Lâu nhất (ms) | Lỗi |
|---|---|---|---|---|---|---|
| planner · adk | 3 | 3 | 100% | 46453 | 52046 | — |
| planner · maf | 3 | 3 | 100% | 42264 | 55485 | — |
| planner-3day-constraints · adk | 3 | 3 | 100% | 47906 | 65250 | — |
| planner-3day-constraints · maf | 3 | 3 | 100% | 69000 | 70593 | — |
| recommendation-required-excluded · adk | 3 | 3 | 100% | 39593 | 41922 | — |
| recommendation-required-excluded · maf | 3 | 3 | 100% | 63594 | 65891 | — |

Chỉ ghi kết quả, loại lỗi và thời gian; không lưu prompt, bản nháp hay văn bản của model.
