"""Deterministic, conservative parsers for the observed Cốc Cốc card layout."""

import re
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import WeatherLocation, WeatherValues

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def normalize(text):
    text = unicodedata.normalize("NFD", text.casefold().replace("đ", "d"))
    return " ".join("".join(c for c in text if unicodedata.category(c) != "Mn").split())


def locality_key(text):
    text = normalize(text)
    text = re.sub(r"^(phuong|xa|thi xa|thi tran|thanh pho|huyen|tinh)\s+", "", text)
    # Exact token content, allowing Sa Pa / Sapa spelling. Never substring matching.
    return re.sub(r"\s+", "", text)


def location_matches(requested: WeatherLocation, label: str):
    parts = [p.strip() for p in label.split(",")]
    return (
        len(parts) >= 2
        and locality_key(requested.name) == locality_key(parts[0])
        and locality_key(requested.province) == locality_key(parts[1])
    )


def parse_stamp(text):
    found = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s*(\d{1,2}):(\d{2}))?", text)
    if not found:
        raise ValueError("No explicit calendar date in card")
    d, m, y, hour, minute = found.groups()
    stamp = datetime(int(y), int(m), int(d), int(hour or 0), int(minute or 0), tzinfo=TZ)
    return stamp, hour is not None


def day_dates(anchor, labels):
    """Require consecutive labelled weekdays and days; handle month/year rollovers."""
    result = []
    for index, label in enumerate(labels):
        expected = anchor + timedelta(days=index)
        match = re.fullmatch(r"\s*(\d{1,2})\s+(TH[2-7]|CN)\s*", label.upper())
        weekday = "CN" if expected.weekday() == 6 else f"TH{expected.weekday() + 2}"
        if not match or int(match[1]) != expected.day or match[2] != weekday:
            raise ValueError("Day labels do not match anchored calendar dates")
        result.append(expected)
    return result


def number(text, unit):
    if not text:
        return None
    match = re.fullmatch(r"\s*(-?\d+(?:[.,]\d+)?)\s*" + re.escape(unit) + r"\s*", text)
    return float(match[1].replace(",", ".")) if match else None


def parse_values(snapshot):
    metrics = snapshot.get("metrics", {})
    return WeatherValues(
        description=snapshot.get("description") or None,
        temperature_c=number(snapshot.get("temperature"), "°C"),
        feels_like_c=number(snapshot.get("feels_like"), "°C"),
        humidity_pct=number(metrics.get("Độ ẩm"), "%"),
        wind_kmh=number(metrics.get("Gió"), "km/h"),
        precipitation_mm=number(metrics.get("Lượng mưa"), "mm"),
        precipitation_probability_pct=number(metrics.get("Khả năng mưa"), "%"),
    )
