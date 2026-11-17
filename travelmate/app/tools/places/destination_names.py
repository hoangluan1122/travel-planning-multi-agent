"""Second tries for a destination the map search did not find.

Travellers type "Hạ Long Bay", "Đảo Phú Quốc" or "Đà Lạtt". The map search finds none of
these, so instead of failing the plan:

1. cleaned(): drop words around the name ("đảo", "vịnh", "bay", "city", "Việt Nam"...).
2. closest(): a well-known destination or province spelled almost the same ("Đà Lạtt" → "Đà Lạt").

closest() only suggests a name that is very close, so a place outside Vietnam ("Bangkok")
is not turned into some Vietnamese town; the caller says it was not found instead. Call it
on the cleaned name: "Vịnh Hạ Long" is close to "Vĩnh Long", "Hạ Long" is not.
"""

import difflib
import re

from app.tools.places.place_media import plain
from app.tools.places.vietnam_regions import load_catalog

# Where travellers go most; with the 34 provinces, the names a typo is matched against.
POPULAR = [
    "Hà Nội", "TP. Hồ Chí Minh", "Đà Nẵng", "Hội An", "Huế", "Nha Trang", "Đà Lạt", "Phú Quốc", "Hạ Long",
    "Sa Pa", "Hà Giang", "Ninh Bình", "Tràng An", "Tam Cốc", "Mộc Châu", "Mai Châu", "Cát Bà", "Hải Phòng",
    "Quy Nhơn", "Tuy Hòa", "Phong Nha", "Đồng Hới", "Vũng Tàu", "Côn Đảo", "Mũi Né", "Phan Thiết", "Cần Thơ",
    "Châu Đốc", "Bến Tre", "Cà Mau", "Buôn Ma Thuột", "Pleiku", "Kon Tum", "Quảng Ngãi", "Lý Sơn", "Tam Đảo",
    "Cao Bằng", "Bản Giốc", "Lạng Sơn", "Điện Biên Phủ", "Hà Tiên", "Rạch Giá", "Cô Tô", "Sầm Sơn", "Cửa Lò",
    "Vinh", "Thanh Hóa", "Bà Nà", "Hồ Tràm", "Tây Ninh", "Mỹ Tho", "Sóc Trăng", "Bạc Liêu", "Long Xuyên",
]
# Words around a place name that the map search does not expect (compared without accents).
EXTRA = {
    "viet nam", "vietnam", "thanh pho", "tp", "tinh", "huyen", "thi xa", "vinh", "dao", "bai bien", "bien",
    "khu du lich", "bay", "city", "town", "province", "island", "islands", "beach", "district",
}


def cleaned(destination):
    """The destination without the words around the name, or None when nothing was removed.

    Accents are ignored when matching, but kept in the result: "Đảo Phú Quốc" → "Phú Quốc".
    """
    words = [w for w in re.split(r"[\s,.;/]+", destination) if w]
    kept, i = [], 0
    while i < len(words):
        step = next((n for n in (3, 2, 1) if i + n <= len(words) and plain(" ".join(words[i:i + n])) in EXTRA), 0)
        if step:
            i += step
        else:
            kept.append(words[i])
            i += 1
    result = " ".join(kept)
    return result if result and plain(result) != plain(destination) else None


def known_names():
    names = [r["name"] for r in load_catalog().current] + POPULAR
    return {plain(n).replace(" ", ""): n for n in names}


def closest(destination):
    """A well-known destination spelled almost like this one ("Đà Lạtt" → "Đà Lạt"), or None."""
    key = plain(destination).replace(" ", "")
    if len(key) < 4:
        return None
    names = known_names()
    found = difflib.get_close_matches(key, names, n=1, cutoff=0.85)
    return names[found[0]] if found and found[0] != key else None
