"""Google Places (New) rich fields, budget estimates from price ranges, stays and photo proxy."""

import asyncio
import json
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from test_planning import payload

from app.agents import BudgetAgent
from app.main import Settings, create_app
from app.models import (
    Activity,
    BudgetInput,
    Context,
    Day,
    Draft,
    Place,
    PlaceResult,
    PriceRange,
    TripRequest,
)
from app.place_media import GooglePhotoProxy
from app.providers import LiveProvider


def google_item(ident, name, types, **extra):
    return {
        "id": ident, "displayName": {"text": name}, "formattedAddress": "1 Lê Lợi, Huế",
        "location": {"latitude": 16.46, "longitude": 107.59}, "types": types, **extra,
    }


RICH = google_item(
    "r1", "Quán Bún Bò", ["restaurant", "food"],
    rating=4.6, userRatingCount=1234, priceLevel="PRICE_LEVEL_INEXPENSIVE",
    priceRange={"startPrice": {"currencyCode": "VND", "units": "50000"},
                "endPrice": {"currencyCode": "VND", "units": "100000"}},
    photos=[{"name": "places/r1/photos/AbC_1", "authorAttributions": [{"displayName": "Lan", "uri": "https://maps.google.com/u/1"}]}],
    regularOpeningHours={"weekdayDescriptions": ["Thứ Hai: 06:00–21:00", "Thứ Ba: 06:00–21:00"]},
    googleMapsUri="https://maps.google.com/?cid=1",
)


def transport(by_label, requests):
    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        label = body["textQuery"].split(" in ")[0]
        return httpx.Response(200, json={"places": by_label.get(label, [])})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_google_fields_become_place_photo_price_rating_hours():
    requests = []
    photos = GooglePhotoProxy("k")
    provider = LiveProvider("k", transport=transport({"Restaurants": [RICH]}, requests), photos=photos,
                            attractions=0, hotels=0)
    result = await provider.search(TripRequest(**payload()))
    place = result.places[0]
    assert place.rating == 4.6 and place.rating_count == 1234
    assert place.price_level == "inexpensive"
    assert place.price_range == PriceRange(low_vnd=Decimal("50000"), high_vnd=Decimal("100000"))
    assert place.photo.url == "/api/v1/places/photo?ref=places/r1/photos/AbC_1"
    assert "Lan" in place.photo.attribution
    assert place.opening_hours_raw.startswith("Thứ Hai")
    assert place.maps_url == "https://maps.google.com/?cid=1"
    mask = requests[0].headers["X-Goog-FieldMask"]
    assert "places.photos" in mask and "places.priceRange" in mask


@pytest.mark.asyncio
async def test_google_hotels_are_stays_and_foreign_currency_is_ignored():
    hotel = google_item("h1", "Khách sạn A", ["lodging", "hotel"],
                        priceRange={"startPrice": {"currencyCode": "USD", "units": "40"}})
    provider = LiveProvider("k", transport=transport({"Hotels": [hotel], "Tourist attractions": [
        google_item("a1", "Đại Nội", ["tourist_attraction"])]}, []), attractions=5, restaurants=0, hotels=3)
    result = await provider.search(TripRequest(**payload()))
    assert [p.id for p in result.places] == ["a1"]
    assert [p.id for p in result.stays] == ["h1"] and result.stays[0].price_range is None
    assert result.places[0].photo is None  # no proxy, no exposed photo


def place(ident, rng=None, cost=None):
    return Place(id=ident, name=ident.upper(), address="a", latitude=0, longitude=0, source="t",
                 price_range=rng, estimated_visit_cost_vnd=cost)


@pytest.mark.asyncio
async def test_budget_estimate_uses_price_ranges_without_counting_them_as_known():
    trip = TripRequest(**payload())
    places = PlaceResult(places=[
        place("a", PriceRange(low_vnd=Decimal("50000"), high_vnd=Decimal("100000"))),
        place("b", PriceRange(high_vnd=Decimal("200000"))), place("c", cost=Decimal("30000")), place("d"),
    ])
    draft = Draft(days=[Day(date=trip.start_date, activities=[
        Activity(place_id=x, start_minute=480 + i * 90, end_minute=540 + i * 90) for i, x in enumerate("abcd")
    ]), Day(date=trip.end_date, activities=[Activity(place_id="d", start_minute=480, end_minute=540)])])
    result = await BudgetAgent().run(BudgetInput(trip=trip, draft=draft, places=places), Context())
    assert result.known_subtotal == Decimal("60000")  # only the explicit cost, x2 travelers
    ranged = next(line for line in result.lines if line.category == "places")
    assert ranged.kind == "sourced"
    assert (ranged.low_vnd, ranged.high_vnd) == (2 * Decimal("250000"), 2 * Decimal("300000"))
    assert len(result.estimate_basis) == 2
    assert any("D" in item for item in result.unknown_items)


def test_plan_response_carries_stays_through_both_orchestrators():
    pytest.importorskip("agent_framework")
    from app.agents import (
        MemoryAgent,
        PlaceAgent,
        PlannerAgent,
        RecommendationAgent,
        Registry,
        WeatherAgent,
    )
    from app.orchestrator import Orchestrator
    from app.providers import DemoProvider
    from app.workflow_orchestrator import WorkflowOrchestrator

    class WithStays(DemoProvider):
        async def search(self, trip):
            result = await super().search(trip)
            return result.model_copy(update={"stays": [place("hotel-1")]})

    for cls in (Orchestrator, WorkflowOrchestrator):
        registry = Registry()
        provider = WithStays()
        for agent in [MemoryAgent(), PlaceAgent(provider), WeatherAgent(provider), RecommendationAgent(),
                      PlannerAgent(), BudgetAgent()]:
            registry.register(agent)
        response = asyncio.run(cls(registry).plan(TripRequest(**payload())))
        assert [p.id for p in response.stays] == ["hotel-1"]
        assert all(a.place_id != "hotel-1" for d in response.draft.days for a in d.activities)


def test_photo_endpoint_redirects_only_issued_names(monkeypatch):
    settings = Settings(_env_file=None, travelmate_mode="live", travelmate_place_provider="google",
                        google_api_key="g", google_maps_api_key="maps-secret", travelmate_api_token="t")
    app = create_app(settings)
    endpoint = next(r.endpoint for r in app.routes if getattr(r, "path", "") == "/api/v1/places/photo")
    proxy = next(c.cell_contents for c in endpoint.__closure__ if isinstance(c.cell_contents, GooglePhotoProxy))

    async def fake_resolve(name):
        return "https://lh3.googleusercontent.com/p/x" if name in proxy.allowed else None

    monkeypatch.setattr(proxy, "resolve", fake_resolve)
    proxy.register("places/a/photos/b")
    with TestClient(app) as client:
        ok = client.get("/api/v1/places/photo", params={"ref": "places/a/photos/b"}, follow_redirects=False)
        assert ok.status_code == 302 and ok.headers["location"].startswith("https://lh3.googleusercontent.com/")
        assert "maps-secret" not in ok.headers["location"]
        assert client.get("/api/v1/places/photo", params={"ref": "places/z/photos/z"}).status_code == 404
