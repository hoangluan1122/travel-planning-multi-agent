# Đánh giá Place Agent — ADK vs MAF (model `gemini-3.5-flash-lite`)

| Engine | Lượt | Thành công | Tỷ lệ | TB số địa điểm | Mọi địa điểm có nguồn | Tìm rộng trước | Trung vị (ms) | Trạng thái |
|---|---|---|---|---|---|---|---|---|
| adk | 5 | 5 | 100% | 4.0 | ✅ | 40% | 6062 | partial×4, success×1 |
| maf | 5 | 5 | 100% | 4.2 | ✅ | 60% | 3141 | partial×4, success×1 |

## Từng ca

| Ca | Engine | Trạng thái | Số địa điểm | Lượt tìm | Từ khoá LLM chọn | ms |
|---|---|---|---|---|---|---|
| hoian-chay | adk | partial | 4 | 2 | “chay”, (rộng) | 10266 |
| hoian-chay | maf | partial | 5 | 2 | “chay”, “restaurant” | 4875 |
| sapa-hotel | adk | partial | 5 | 1 | “hotel” | 6062 |
| sapa-hotel | maf | partial | 5 | 1 | (rộng) | 3546 |
| dalat-sights | adk | success | 5 | 1 | (rộng) | 5282 |
| dalat-sights | maf | success | 5 | 1 | (rộng) | 1906 |
| hue-heritage | adk | partial | 3 | 1 | (rộng) | 6389 |
| hue-heritage | maf | partial | 3 | 1 | (rộng) | 2312 |
| danang-seafood | adk | partial | 3 | 1 | “Hải sản” | 3281 |
| danang-seafood | maf | partial | 3 | 1 | “hải sản” | 3141 |
