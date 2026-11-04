# Đánh giá Place Agent — ADK vs MAF (model `gemini-3.5-flash-lite`)

| Engine | Lượt | Thành công | Tỷ lệ | TB số địa điểm | Mọi địa điểm có nguồn | Ca đúng nhu cầu | Địa điểm đúng nhu cầu | Tìm rộng trước | Trung vị (ms) | Trạng thái |
|---|---|---|---|---|---|---|---|---|---|---|
| adk | 10 | 4 | 40% | 2.0 | ✅ | 33% | 80% | 40% | 2281 | partial×4, source_error×6 |
| maf | 10 | 3 | 30% | 1.0 | ✅ | 33% | 40% | 30% | 640 | partial×3, source_error×7 |

## Từng ca

| Ca | Engine | Trạng thái | Số địa điểm | Đúng nhu cầu | Lượt tìm | Từ khoá LLM chọn | ms |
|---|---|---|---|---|---|---|---|
| hoian-chay | adk | partial | 5 | 4 | 2 | “chay”, “restaurant” | 9187 |
| hoian-chay | maf | partial | 3 | 1 | 2 | “chay”, (rộng) | 4093 |
| hoian-chay | adk | partial | 5 | 4 | 2 | “chay”, “restaurant” | 3672 |
| hoian-chay | maf | partial | 2 | 1 | 2 | “chay”, (rộng) | 2452 |
| sapa-hotel | adk | partial | 5 | — | 1 | (rộng) | 6422 |
| sapa-hotel | maf | partial | 5 | — | 1 | (rộng) | 1687 |
| sapa-hotel | adk | partial | 5 | — | 1 | (rộng) | 5280 |
| sapa-hotel | maf | source_error | 0 | — | 0 | — | 282 |
| dalat-sights | adk | source_error | 0 | — | 1 | (rộng) | 4062 |
| dalat-sights | maf | source_error | 0 | — | 1 | (rộng) | 983 |
| dalat-sights | adk | source_error | 0 | — | 1 | (rộng) | 891 |
| dalat-sights | maf | source_error | 0 | — | 0 | — | 296 |
| hue-heritage | adk | source_error | 0 | 0 | 0 | — | 297 |
| hue-heritage | maf | source_error | 0 | 0 | 1 | (rộng) | 5827 |
| hue-heritage | adk | source_error | 0 | 0 | 0 | — | 312 |
| hue-heritage | maf | source_error | 0 | 0 | 0 | — | 281 |
| danang-seafood | adk | source_error | 0 | 0 | 0 | — | 297 |
| danang-seafood | maf | source_error | 0 | 0 | 0 | — | 296 |
| danang-seafood | adk | source_error | 0 | 0 | 0 | — | 296 |
| danang-seafood | maf | source_error | 0 | 0 | 0 | — | 297 |
