# Đánh giá Place Agent — ADK vs MAF (model `gemini-3.5-flash-lite`)

| Engine | Lượt | Thành công | Tỷ lệ | TB số địa điểm | Mọi địa điểm có nguồn | Ca đúng nhu cầu | Địa điểm đúng nhu cầu | Tìm rộng trước | Trung vị (ms) | Trạng thái |
|---|---|---|---|---|---|---|---|---|---|---|
| adk | 10 | 10 | 100% | 4.7 | ✅ | 100% | 78% | 60% | 3773 | partial×8, success×2 |
| maf | 10 | 10 | 100% | 4.6 | ✅ | 100% | 73% | 50% | 2179 | partial×8, success×2 |

## Từng ca

| Ca | Engine | Trạng thái | Số địa điểm | Đúng nhu cầu | Lượt tìm | Từ khoá LLM chọn | ms |
|---|---|---|---|---|---|---|---|
| hoian-chay | adk | partial | 3 | 1 | 2 | “chay”, (rộng) | 12280 |
| hoian-chay | maf | partial | 5 | 1 | 2 | “chay”, (rộng) | 2796 |
| hoian-chay | adk | partial | 4 | 4 | 2 | “chay”, “restaurant” | 4546 |
| hoian-chay | maf | partial | 2 | 1 | 2 | “chay”, (rộng) | 4046 |
| sapa-hotel | adk | partial | 5 | — | 1 | (rộng) | 4796 |
| sapa-hotel | maf | partial | 5 | — | 1 | (rộng) | 2156 |
| sapa-hotel | adk | partial | 5 | — | 1 | (rộng) | 2593 |
| sapa-hotel | maf | partial | 5 | — | 1 | (rộng) | 1733 |
| dalat-sights | adk | success | 5 | — | 1 | (rộng) | 12656 |
| dalat-sights | maf | success | 5 | — | 1 | (rộng) | 1875 |
| dalat-sights | adk | success | 5 | — | 1 | (rộng) | 2671 |
| dalat-sights | maf | success | 5 | — | 1 | (rộng) | 2141 |
| hue-heritage | adk | partial | 5 | 3 | 1 | (rộng) | 8062 |
| hue-heritage | maf | partial | 5 | 3 | 1 | (rộng) | 2203 |
| hue-heritage | adk | partial | 5 | 3 | 1 | (rộng) | 2203 |
| hue-heritage | maf | partial | 4 | 4 | 2 | “bảo tàng”, “di tích” | 4718 |
| danang-seafood | adk | partial | 5 | 5 | 1 | “Hải sản” | 3000 |
| danang-seafood | maf | partial | 5 | 5 | 1 | “hải sản” | 3468 |
| danang-seafood | adk | partial | 5 | 5 | 1 | “hải sản” | 2264 |
| danang-seafood | maf | partial | 5 | 5 | 1 | “hải sản” | 1843 |
