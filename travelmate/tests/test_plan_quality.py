"""Plan quality rules found by planning a real Huế trip with Gemini.

That plan had two bún bò shops 90 minutes apart, four restaurants in a day, the same
shop again on day 2 under a second map entry, and no Đại Nội, yet passed its self-check.
"""

from datetime import date, timedelta

import pytest
from test_planning import payload
from test_self_check import ScriptedLLM, act, draft_with, ids, orchestrator

from app.agents.recommendation import RecommendationAgent
from app.agents.rule_scheduler import rule_draft
from app.agents.self_check import review_draft
from app.core.models import (
    Context,
    Day,
    Draft,
    Place,
    PlaceResult,
    Preferences,
    RecommendationInput,
    TicketInfo,
    TripRequest,
    WeatherResult,
)
from app.tools.places.same_place import drop_near_duplicates, same_place

D1 = date.today() + timedelta(days=2)
D2 = D1 + timedelta(days=1)


def place(ident, name, kind, lat=16.4670, lon=107.5790, ticket=None, **extra):
    tk = TicketInfo(group_id=ticket, label="Vé", adult_vnd=50000, checked=date(2026, 11, 5)) if ticket else None
    return Place(id=ident, name=name, address="Huế", latitude=lat, longitude=lon, source="t", types=[kind],
                 ticket=tk, **extra)


# --- one real place, two map entries ---------------------------------------------------------


def test_same_place_needs_a_shared_name_start_and_a_short_distance():
    cam = place("a", "Quán Cẩm", "restaurant")
    assert same_place(cam, place("b", "Quán Cẩm - Bún Bò Huế", "restaurant", lat=16.4680))
    assert not same_place(cam, place("c", "Quán Cẩm - Bún Bò Huế", "restaurant", lat=16.49))  # ~2.5 km away
    assert not same_place(place("d", "Chùa", "temple"), place("e", "Chùa Thiên Mụ", "temple"))  # one word
    assert not same_place(place("f", "Quán Chay Tịnh", "restaurant"), place("g", "Quán Chay Thanh Liễu", "restaurant"))


def test_duplicates_keep_the_richer_entry_at_the_first_position():
    plain_entry = place("a", "Quán Cẩm", "restaurant")
    rich_entry = place("b", "Quán Cẩm - Bún Bò Huế", "restaurant", opening_hours_raw="Mo-Su 06:00-21:00")
    other = place("c", "Bảo tàng Cổ vật Cung đình Huế", "museum")
    assert [p.id for p in drop_near_duplicates([plain_entry, other, rich_entry])] == ["b", "c"]


@pytest.mark.asyncio
async def test_ranking_drops_the_second_map_entry():
    places = PlaceResult(places=[place("a", "Quán Cẩm", "restaurant"), place("b", "Quán Cẩm Bún Bò", "restaurant")])
    ranked = await RecommendationAgent().execute(
        RecommendationInput(places=places, preferences=Preferences(interests=[])), Context())
    assert [p.id for p in ranked.places] == ["a"]


# --- self-check --------------------------------------------------------------------------------

PLACES = PlaceResult(places=[
    place("dn", "Hoàng Thành Huế", "castle", ticket="hue-dai-noi"),
    place("nm", "Ngọ Môn", "attraction", ticket="hue-dai-noi"),
    place("td", "Lăng Tự Đức", "tomb", lat=16.43, ticket="hue-tu-duc"),
    place("bt", "Bảo tàng Cổ vật Cung đình Huế", "museum", ticket="hue-bao-tang-co-vat"),
    place("cafe", "Nhà Quin Coffee", "cafe"),
    place("r1", "Bún bò Kim Đồng", "restaurant", lat=16.47),
    place("r2", "Quán Hạnh", "restaurant", lat=16.471),
    place("r3", "Quán Chay Tịnh", "restaurant", lat=16.472),
    place("r4", "Quán Bánh Chi", "restaurant", lat=16.473),
])
NO_RAIN = WeatherResult()


def checks_for(*days):
    return review_draft(Draft(days=[Day(date=D1 + timedelta(days=i), activities=acts) for i, acts in enumerate(days)]),
                        PLACES, NO_RAIN)


def detail(checks, check_id):
    return next(c.detail for c in checks if c.id == check_id)


def test_meals_too_close_or_too_many_fail_with_names_and_times():
    close = checks_for([act("r1", 480, 540), act("r2", 570, 630), act("dn", 660, 780)])
    assert "meal_pacing" in ids(close, False)
    assert "Bún bò Kim Đồng 08:00" in detail(close, "meal_pacing") and "Quán Hạnh 09:30" in detail(close, "meal_pacing")
    many = checks_for([act("r1", 420, 480), act("r2", 600, 660), act("r3", 780, 840), act("r4", 1080, 1140)])
    assert "4 quán ăn" in detail(many, "meal_pacing")
    fine = checks_for([act("dn", 480, 660), act("r1", 690, 780), act("cafe", 900, 960), act("r2", 1080, 1170)])
    assert "meal_pacing" in ids(fine, True)


def test_the_best_known_sight_and_one_famous_sight_a_day():
    no_dai_noi = checks_for([act("bt", 480, 600), act("r1", 690, 780)], [act("td", 480, 600), act("r2", 690, 780)])
    assert "famous" in ids(no_dai_noi, False) and "Hoàng Thành Huế" in detail(no_dai_noi, "famous")
    # Ngọ Môn is part of Đại Nội: the same site counts once, so two days need a second site.
    one_site = checks_for([act("dn", 480, 600), act("nm", 620, 680)], [act("cafe", 480, 540), act("r2", 690, 780)])
    assert "famous" in ids(one_site, False) and "Lăng Tự Đức" in detail(one_site, "famous")
    good = checks_for([act("nm", 480, 600), act("r1", 690, 780)], [act("td", 480, 600), act("r2", 690, 780)])
    assert "famous" in ids(good, True)


def test_best_known_follows_the_ticket_table_not_the_ranking():
    # Interest ranking put the museum first; the table still lists Đại Nội as Huế's best known.
    museum_first = PlaceResult(places=[PLACES.places[3], *PLACES.places[:3], *PLACES.places[4:]])
    draft = Draft(days=[Day(date=D1, activities=[act("bt", 480, 600), act("r1", 690, 780)])])
    checks = review_draft(draft, museum_first, NO_RAIN)
    assert "famous" in ids(checks, False) and "Hoàng Thành Huế" in detail(checks, "famous")
    rules = rule_draft(TripRequest(**payload()), museum_first, NO_RAIN)
    assert rules.days[0].activities[0].place_id == "dn"


def test_no_ticket_table_match_means_no_famous_check():
    plain_places = PlaceResult(places=[place("m", "Bảo tàng", "museum"), place("r", "Quán Cơm", "restaurant")])
    draft = Draft(days=[Day(date=D1, activities=[act("m", 480, 600)])])
    assert "famous" not in {c.id for c in review_draft(draft, plain_places, NO_RAIN)}


# --- rule scheduler (used when Gemini is unavailable) ---------------------------------------------


def test_rule_schedule_covers_the_famous_sights_and_spaces_meals():
    # Ranked as interest matching might leave them: restaurants and a café ahead of the sights.
    ranked = PlaceResult(places=[*PLACES.places[4:], *PLACES.places[:4]])
    trip = TripRequest(**payload())
    draft = rule_draft(trip, ranked, NO_RAIN)
    checks = review_draft(draft, ranked, NO_RAIN)
    assert {"famous", "meal_pacing"} <= ids(checks, True)
    first_day = [a.place_id for a in draft.days[0].activities]
    assert first_day[0] == "dn" and "nm" not in first_day  # one stop per site, best known first


# --- the revision loop acts on the new checks -----------------------------------------------------


@pytest.mark.asyncio
async def test_back_to_back_meals_are_fed_back_and_fixed():
    # test_self_check's provider offers m (museum), r and v (restaurants).
    llm = ScriptedLLM([draft_with(["r", "v", "m"], ["m", "r"]), draft_with(["v", "m"], ["m", "r"])])
    result = await orchestrator(llm).plan(TripRequest(**payload()))
    assert any("Bữa ăn quá dày" in f for f in llm.feedback[1])
    assert result.self_check.revisions == 1 and result.self_check.final_passed
