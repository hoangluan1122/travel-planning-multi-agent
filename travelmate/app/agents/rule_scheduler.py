"""Rule-based itinerary used when the itinerary LLM is unavailable (quota, outage, timeout).

It builds a schedule that satisfies the same self-check rules the LLM is held to:
stated wishes first, lunch between 10:30 and 14:30, at most one outdoor stop on a rainy day,
no place repeated while unused ones remain, every place from the ranked candidates. It is
a sensible default, not a route optimisation: travel times between stops are not known.
"""

from datetime import timedelta

from app.agents.self_check import MEAL_TYPES, OUTDOOR_TYPES, RAIN_CODES
from app.core.models import Activity, Day, Draft

CAFE_TYPES = {"cafe", "coffee_shop", "bakery"}
STAY_TYPES = {"hotel", "lodging", "hostel", "guest_house", "motel", "resort", "camp_site"}
# (start, end, kind): two sights in the morning, lunch, two sights, a cafe break, dinner.
SLOTS = [
    (8 * 60 + 30, 10 * 60, "sight"),
    (10 * 60 + 15, 11 * 60 + 30, "sight"),
    (12 * 60, 13 * 60, "meal"),
    (14 * 60, 15 * 60 + 30, "sight"),
    (15 * 60 + 45, 16 * 60 + 30, "cafe"),
    (16 * 60 + 45, 18 * 60, "sight"),
    (18 * 60 + 30, 19 * 60 + 30, "meal"),
]


def kind_of(place):
    types = set(place.types)
    if types & MEAL_TYPES:
        return "meal"
    if types & CAFE_TYPES:
        return "cafe"
    if types & STAY_TYPES:
        return "stay"
    return "sight"


def rule_draft(trip, places, weather=None, wish_ids=()):
    """A Draft for every trip day from ranked places (best first)."""
    ranked = list(places.places)
    wish_ids = set(wish_ids)
    pools = {kind: [p for p in ranked if kind_of(p) == kind] for kind in ("sight", "meal", "cafe")}
    # Places matching a stated wish go first, so every wish gets scheduled early in the trip.
    pools["sight"].sort(key=lambda p: p.id not in wish_ids)
    pools["meal"].sort(key=lambda p: p.id not in wish_ids)
    used = set()
    rain = {d.date for d in (weather.days if weather else []) if d.weather_code in RAIN_CODES}
    days = []
    total = (trip.end_date - trip.start_date).days + 1
    for index in range(total):
        day = trip.start_date + timedelta(days=index)
        rainy, outdoor_today, today = day in rain, 0, set()
        activities = []
        for start, end, slot in SLOTS:
            pool = pools[slot]
            if not pool:
                continue

            def allowed(place):
                if place.id in today:
                    return False
                return not (rainy and slot == "sight" and outdoor_today >= 1 and OUTDOOR_TYPES & set(place.types))

            fresh = [p for p in pool if p.id not in used and allowed(p)]
            if rainy and slot == "sight":
                fresh.sort(key=lambda p: bool(OUTDOOR_TYPES & set(p.types)))  # indoor first when it rains
            choice = fresh[0] if fresh else next((p for p in pool if allowed(p)), None)
            if choice is None:
                continue
            if slot == "sight" and OUTDOOR_TYPES & set(choice.types):
                outdoor_today += 1
            used.add(choice.id)
            today.add(choice.id)
            activities.append(Activity(place_id=choice.id, start_minute=start, end_minute=end))
        if not activities:  # only stays found: still return a valid day
            activities.append(Activity(place_id=ranked[index % len(ranked)].id, start_minute=540, end_minute=660))
        days.append(Day(date=day, activities=activities))
    return Draft(days=days)
