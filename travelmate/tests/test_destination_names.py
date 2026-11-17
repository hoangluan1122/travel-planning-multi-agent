"""Second tries for destinations the map search does not know."""

import pytest

from app.tools.places.destination_names import cleaned, closest


@pytest.mark.parametrize("typed,expected", [
    ("Hạ Long Bay", "Hạ Long"),
    ("Vịnh Hạ Long", "Hạ Long"),
    ("Đảo Phú Quốc", "Phú Quốc"),
    ("Đà Lạt, Việt Nam", "Đà Lạt"),
    ("Thành phố Huế", "Huế"),
    ("Khu du lịch Tràng An", "Tràng An"),
    ("Hoi An city", "Hoi An"),
    ("Nha Trang", None),  # nothing to drop
])
def test_cleaned_drops_words_around_the_name_and_keeps_accents(typed, expected):
    assert cleaned(typed) == expected


@pytest.mark.parametrize("typed,expected", [
    ("Đà Lạtt", "Đà Lạt"),
    ("Ha Noii", "Hà Nội"),
    ("Phu Quocc", "Phú Quốc"),
    ("Đà Lạt", None),     # already right
    ("Bangkok", None),    # not in Vietnam: never turned into a Vietnamese town
    ("Tokyo", None),
    ("Hà Nam", None),     # a real province, not a typo of Hà Nội
])
def test_closest_only_fixes_near_misses(typed, expected):
    assert closest(typed) == expected
