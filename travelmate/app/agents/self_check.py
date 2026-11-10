"""Metacognition (course lesson 09): the planner checks its own draft before answering.

review_draft() is the monitoring step: rule-based checks on a schedule, so their verdict
is reliable and testable. The orchestrator turns failed checks into feedback for the
itinerary LLM (the regulation step) and keeps the draft with the fewest failures.
Each check passes trivially when the data needed to satisfy it does not exist (no meal
candidates, no rain in the forecast...), so the agent is never asked the impossible.
"""

from app.core.models import CheckResult
from app.tools.places.place_media import plain
from app.tools.prices.ticket_prices import fame_rank

MEAL_TYPES = {"restaurant", "fast_food", "food_court", "food", "meal_takeaway"}
OUTDOOR_TYPES = {"park", "viewpoint", "beach", "peak", "nature_reserve", "zoo", "theme_park", "national_park",
                 "cave_entrance", "campground", "amusement_park"}
RAIN_CODES = set(range(51, 68)) | set(range(80, 83)) | set(range(95, 100))
LUNCH_FROM, LUNCH_TO = 10 * 60 + 30, 14 * 60 + 30
MAX_OUTDOOR_ON_RAINY_DAY = 1
MAX_MEALS_PER_DAY = 3
MIN_MINUTES_BETWEEN_MEALS = 3 * 60


def hhmm(minute):
    return f"{minute // 60:02d}:{minute % 60:02d}"


def check_wishes(draft, places, wishes):
    """Each stated wish that has matching candidates gets at least one scheduled place."""
    scheduled = {a.place_id for d in draft.days for a in d.activities}
    results = []
    for label, keyword, candidate_ids in wishes:
        if not candidate_ids:
            continue
        word = plain(keyword)
        hit = [places[i].name for i in scheduled
               if i in places and (i in candidate_ids or (word and word in plain(places[i].name)))]
        results.append(CheckResult(
            id=f"wish:{word}",
            label=f"Có địa điểm cho mong muốn {label}",
            passed=bool(hit),
            detail=f"Đã xếp: {', '.join(hit[:3])}." if hit else
            f"Chưa xếp địa điểm nào cho {label}, dù có {len(candidate_ids)} ứng viên phù hợp.",
        ))
    return results


def check_meals(draft, places):
    """A day that spans lunchtime includes a meal place starting between 10:30 and 14:30."""
    if not any(MEAL_TYPES & set(p.types) for p in places.values()):
        return []
    missing = []
    for day in draft.days:
        acts = day.activities
        if not acts or min(a.start_minute for a in acts) > 12 * 60 or max(a.end_minute for a in acts) < 13 * 60:
            continue  # the day does not span lunch
        if not any(MEAL_TYPES & set(places[a.place_id].types) and LUNCH_FROM <= a.start_minute <= LUNCH_TO
                   for a in acts if a.place_id in places):
            missing.append(day.date.isoformat())
    return [CheckResult(
        id="meals", label="Mỗi ngày có bữa trưa", passed=not missing,
        detail="Ngày nào kéo qua trưa cũng có quán ăn trong khung 10:30–14:30." if not missing else
        f"Thiếu quán ăn trong khung 10:30–14:30 các ngày: {', '.join(missing)}.",
    )]


def check_meal_pacing(draft, places):
    """No eating marathon: at most three meal places a day, each meal three hours after the last."""
    problems = []
    for day in draft.days:
        meals = sorted((a for a in day.activities
                        if a.place_id in places and MEAL_TYPES & set(places[a.place_id].types)),
                       key=lambda a: a.start_minute)
        if len(meals) > MAX_MEALS_PER_DAY:
            problems.append(f"{day.date.isoformat()}: {len(meals)} quán ăn (tối đa {MAX_MEALS_PER_DAY})")
        for before, after in zip(meals, meals[1:]):
            if after.start_minute - before.start_minute < MIN_MINUTES_BETWEEN_MEALS:
                problems.append(f"{day.date.isoformat()}: {places[before.place_id].name} {hhmm(before.start_minute)} "
                                f"rồi {places[after.place_id].name} {hhmm(after.start_minute)}")
    if not any(MEAL_TYPES & set(p.types) for p in places.values()):
        return []
    return [CheckResult(
        id="meal_pacing", label="Bữa ăn cách nhau hợp lý", passed=not problems,
        detail=f"Mỗi ngày tối đa {MAX_MEALS_PER_DAY} quán ăn, các bữa cách nhau ít nhất 3 tiếng." if not problems else
        f"Bữa ăn quá dày: {'; '.join(problems)}. Thay bằng điểm tham quan hoặc quán cà phê.",
    )]


def famous_groups(places):
    """Well-known sights among the candidates, best known first: one (group, first place) per site.

    A place is well known when it matched the hand-made ticket table, which lists the sights a
    visitor would expect to see (Đại Nội, the royal tombs...), each city's best known first.
    Parts of one site (Ngọ Môn, Điện Thái Hòa in Đại Nội) share a group.
    """
    groups = {}
    for p in places.values():
        if p.ticket and p.ticket.group_id not in groups:
            groups[p.ticket.group_id] = p
    return sorted(groups.items(), key=lambda item: fame_rank(item[0]))


def check_famous(draft, places):
    """The best-known sight is on the plan, and one well-known sight per day when there are enough."""
    groups = famous_groups(places)
    if not groups:
        return []
    scheduled = {places[a.place_id].ticket.group_id for d in draft.days for a in d.activities
                 if a.place_id in places and places[a.place_id].ticket}
    need = min(len(groups), len(draft.days))
    top_group, top_place = groups[0]
    missing = [p.name for g, p in groups if g not in scheduled]
    passed = top_group in scheduled and len(scheduled) >= need
    if passed:
        detail = f"Đã xếp {len(scheduled)} điểm nổi tiếng, có {top_place.name}."
    elif top_group not in scheduled:
        detail = f"Chưa có {top_place.name}, điểm nổi tiếng nhất trong danh sách."
    else:
        detail = (f"Mới có {len(scheduled)} điểm nổi tiếng cho {len(draft.days)} ngày; còn chưa xếp: "
                  f"{', '.join(missing[:3])}.")
    return [CheckResult(id="famous", label="Có các điểm tham quan nổi tiếng", passed=passed, detail=detail)]


def check_rain(draft, places, weather):
    """On rainy days, at most one outdoor place when indoor alternatives exist."""
    rainy = {d.date for d in weather.days if d.weather_code in RAIN_CODES}
    indoor_exists = any(not (OUTDOOR_TYPES & set(p.types)) for p in places.values())
    if not rainy or not indoor_exists:
        return []
    heavy = []
    for day in draft.days:
        if day.date not in rainy:
            continue
        outdoor = [places[a.place_id].name for a in day.activities
                   if a.place_id in places and OUTDOOR_TYPES & set(places[a.place_id].types)]
        if len(outdoor) > MAX_OUTDOOR_ON_RAINY_DAY:
            heavy.append(f"{day.date.isoformat()} ({', '.join(outdoor)})")
    return [CheckResult(
        id="rain", label="Ngày mưa ưu tiên chỗ trong nhà", passed=not heavy,
        detail="Ngày có mưa không xếp quá một điểm ngoài trời." if not heavy else
        f"Quá nhiều điểm ngoài trời vào ngày mưa: {'; '.join(heavy)}.",
    )]


def check_repeats(draft, places):
    """A place is not repeated across days while unused places of the same kind remain."""
    days_of = {}
    for day in draft.days:
        for a in day.activities:
            days_of.setdefault(a.place_id, set()).add(day.date)
    used = set(days_of)
    repeated = []
    for place_id, dates in days_of.items():
        if len(dates) < 2 or place_id not in places:
            continue
        kind = (places[place_id].types or ["?"])[0]
        if any(pid not in used and (p.types or ["?"])[0] == kind for pid, p in places.items()):
            repeated.append(places[place_id].name)
    if len(draft.days) < 2:
        return []
    return [CheckResult(
        id="repeats", label="Không lặp địa điểm khi còn lựa chọn khác", passed=not repeated,
        detail="Không có địa điểm nào bị lặp không cần thiết." if not repeated else
        f"Lặp lại trong nhiều ngày dù còn chỗ cùng loại chưa dùng: {', '.join(repeated)}.",
    )]


def review_draft(draft, ranked, weather, wishes=()):
    """Run every check. wishes: (label, keyword, candidate place ids) per stated wish."""
    places = {p.id: p for p in ranked.places}
    return (check_wishes(draft, places, wishes) + check_famous(draft, places) + check_meals(draft, places)
            + check_meal_pacing(draft, places) + check_rain(draft, places, weather) + check_repeats(draft, places))


def feedback_from(checks):
    """Failed checks to fix, plus the passing ones to keep, for the itinerary LLM.

    Read as data via inspect_trip. Naming what already passes stops a revision from fixing
    one problem by breaking another.
    """
    fix = [f"Cần sửa: {c.detail}" for c in checks if not c.passed]
    keep = [c.label for c in checks if c.passed]
    return fix + ([f"Giữ nguyên các điểm đang đạt: {'; '.join(keep)}."] if keep and fix else [])


def draft_score(checks):
    """Lower is better: unmet stated wishes first (what the user asked for), then other failures."""
    wishes = sum(not c.passed for c in checks if c.id.startswith("wish:"))
    return wishes, sum(not c.passed for c in checks)
