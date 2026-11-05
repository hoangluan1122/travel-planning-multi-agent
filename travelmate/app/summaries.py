"""Compact JSON views of places and plans, shared by the MCP server and the A2A endpoint."""


def place_summary(place):
    ticket = place.ticket
    return {
        "name": place.name,
        "address": place.address,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "types": place.types[:4],
        "rating": place.rating,
        "ticket": None if ticket is None else {
            "label": ticket.label,
            "adult_vnd": None if ticket.adult_vnd is None else int(ticket.adult_vnd),
            "low_vnd": None if ticket.low_vnd is None else int(ticket.low_vnd),
            "high_vnd": None if ticket.high_vnd is None else int(ticket.high_vnd),
            "sources": ticket.sources,
            "checked": ticket.checked.isoformat(),
        },
        "map_url": place.maps_url
        or f"https://www.openstreetmap.org/?mlat={place.latitude}&mlon={place.longitude}#map=17/{place.latitude}/"
        f"{place.longitude}",
        "source": place.attribution or place.source,
    }


def plan_summary(plan):
    """Compact, client-friendly view of a PlanResponse (shared by MCP and A2A)."""
    names = {p.id: p for p in plan.places}
    days = [{
        "date": d.date.isoformat(),
        "activities": [{
            "start": f"{a.start_minute // 60:02d}:{a.start_minute % 60:02d}",
            "end": f"{a.end_minute // 60:02d}:{a.end_minute % 60:02d}",
            "place": names[a.place_id].name if a.place_id in names else a.place_id,
        } for a in d.activities],
    } for d in plan.draft.days]
    budget = plan.budget
    return {
        "request_id": str(plan.request_id),
        "mode": plan.mode,
        "days": days,
        "budget": {
            "known_subtotal_vnd": int(budget.known_subtotal),
            "estimated_low_vnd": None if budget.estimated_low_vnd is None else int(budget.estimated_low_vnd),
            "estimated_high_vnd": None if budget.estimated_high_vnd is None else int(budget.estimated_high_vnd),
            "unknown_items": budget.unknown_items,
        },
        "self_check_passed": None if plan.self_check is None else plan.self_check.final_passed,
        "warnings": plan.warnings[:8],
    }
