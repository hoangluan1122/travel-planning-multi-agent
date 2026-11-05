# Đánh giá Place Agent — ADK vs MAF (model `gemini-3.5-flash-lite`)

| Engine | Lượt | Thành công | Tỷ lệ | TB số địa điểm | Mọi địa điểm có nguồn | Ca đúng nhu cầu | Địa điểm đúng nhu cầu | Tìm rộng trước | Trung vị (ms) | Trạng thái |
|---|---|---|---|---|---|---|---|---|---|---|
| adk | 6 | 5 | 83% | 4.0 | ✅ | 67% | 42% | 33% | 4016 | partial×5, source_error×1 |
| maf | 6 | 5 | 83% | 3.67 | ✅ | 67% | 46% | 33% | 2647 | partial×5, source_error×1 |

## Từng ca

| Ca | Engine | Trạng thái | Số địa điểm | Đúng nhu cầu | Lượt tìm | Từ khoá LLM chọn | ms |
|---|---|---|---|---|---|---|---|
| hoian-chay | adk | partial | 4 | 0 | 2 | “chay”, (rộng) | 10891 |
| hoian-chay | maf | partial | 4 | 0 | 2 | “chay”, (rộng) | 3186 |
| hoian-chay | adk | partial | 5 | 1 | 2 | “chay”, “restaurant” | 4985 |
| hoian-chay | maf | partial | 5 | 1 | 2 | “chay”, “restaurant” | 3031 |
| hue-heritage | adk | partial | 5 | 3 | 1 | (rộng) | 7687 |
| hue-heritage | maf | partial | 5 | 3 | 1 | (rộng) | 2718 |
| hue-heritage | adk | partial | 5 | 3 | 1 | (rộng) | 2125 |
| hue-heritage | maf | partial | 5 | 3 | 1 | (rộng) | 2577 |
| danang-seafood | adk | partial | 5 | 3 | 1 | “Hải sản” | 3047 |
| danang-seafood | maf | partial | 3 | 3 | 1 | “Hải sản” | 1702 |
| danang-seafood | adk | source_error | 0 | 0 | 0 | — | 297 |
| danang-seafood | maf | source_error | 0 | 0 | 1 | “Hải sản” | 875 |
