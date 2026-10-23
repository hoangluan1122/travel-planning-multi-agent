"""Auditable preference scores and eligibility checks over supplied evidence."""

import math
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..models import Model
from ..osm_places import distance_m, normalized

Feature = Literal[
    "nature",
    "culture",
    "food",
    "shopping",
    "lodging",
    "indoor",
    "outdoor",
    "family_friendly",
    "quiet",
    "wheelchair_accessible",
]
Basis = Literal["per_person_visit", "per_person_meal", "per_room_night", "per_group"]

# Explicit taxonomy mappings, not claims inferred from a business name/review.
TYPE_TOPICS = {
    "museum": "culture",
    "gallery": "culture",
    "historic": "culture",
    "park": "nature",
    "nature_reserve": "nature",
    "viewpoint": "nature",
    "restaurant": "food",
    "cafe": "food",
    "food_court": "food",
    "hotel": "lodging",
    "hostel": "lodging",
    "guest_house": "lodging",
    "resort": "lodging",
    "mall": "shopping",
    "marketplace": "shopping",
}
ALIASES = {
    "thien nhien": "nature",
    "nature": "nature",
    "cong vien": "nature",
    "van hoa": "culture",
    "culture": "culture",
    "bao tang": "culture",
    "museum": "culture",
    "museums": "culture",
    "am thuc": "food",
    "food": "food",
    "nha hang": "food",
    "mua sam": "shopping",
    "shopping": "shopping",
    "khach san": "lodging",
    "hotel": "lodging",
    "lodging": "lodging",
    "trong nha": "indoor",
    "indoor": "indoor",
    "ngoai troi": "outdoor",
    "outdoor": "outdoor",
    "gia dinh": "family_friendly",
    "family friendly": "family_friendly",
    "yen tinh": "quiet",
    "quiet": "quiet",
    "xe lan": "wheelchair_accessible",
    "wheelchair accessible": "wheelchair_accessible",
}


class FeatureEvidence(Model):
    feature: Feature
    value: bool = Field(strict=True)
    source: str = Field(min_length=1, max_length=2000)

    @field_validator("source")
    @classmethod
    def source_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Evidence source must not be blank")
        return value.strip()


class CandidatePrice(Model):
    min_vnd: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    max_vnd: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    basis: Basis
    source: str = Field(min_length=1, max_length=2000)
    observed_at: datetime
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def price_rules(self):
        if self.min_vnd > self.max_vnd or not self.source.strip():
            raise ValueError("Price range/source invalid")
        for stamp in [self.observed_at, self.valid_until]:
            if stamp is not None and (stamp.tzinfo is None or stamp.utcoffset() is None):
                raise ValueError("Price timestamps must include timezone")
        if self.valid_until is not None and self.valid_until < self.observed_at:
            raise ValueError("Price expires before observation")
        return self


class RecommendationOrigin(Model):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def numeric_location(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Origin coordinates must be JSON numbers")
        return value


class RecommendationWeights(Model):
    interests: float = Field(default=0.5, ge=0, le=1)
    proximity: float = Field(default=0.2, ge=0, le=1)
    affordability: float = Field(default=0.2, ge=0, le=1)
    weather: float = Field(default=0.1, ge=0, le=1)

    @model_validator(mode="after")
    def positive_sum(self):
        if sum(self.model_dump().values()) <= 0:
            raise ValueError("At least one weight must be positive")
        return self


class RecommendationContext(Model):
    origin: RecommendationOrigin | None = None
    max_distance_m: float | None = Field(default=None, gt=0, le=500000)
    proximity_scale_m: float = Field(default=5000, gt=0, le=500000)
    max_price_vnd: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    price_basis: Basis = "per_person_visit"
    prices: dict[str, CandidatePrice] = Field(default_factory=dict, max_length=30)
    features: dict[str, list[FeatureEvidence]] = Field(default_factory=dict, max_length=30)
    required_features: list[Feature] = Field(default_factory=list, max_length=10)
    unknown_policy: Literal["keep_with_warning", "exclude"] = "keep_with_warning"
    weather_risk: Literal["not_supplied", "low", "elevated", "unknown"] = "not_supplied"
    weather_source: str | None = Field(default=None, min_length=1, max_length=2000)
    weights: RecommendationWeights = Field(default_factory=RecommendationWeights)

    @model_validator(mode="after")
    def coherent(self):
        if self.max_distance_m is not None and self.origin is None:
            raise ValueError("Distance filter requires an origin")
        if self.weather_risk in {"low", "elevated"} and not (self.weather_source or "").strip():
            raise ValueError("Weather ranking requires a supplied source")
        if len(set(self.required_features)) != len(self.required_features):
            raise ValueError("Duplicate required features")
        for facts in self.features.values():
            if len(facts) > 10 or len({f.feature for f in facts}) != len(facts):
                raise ValueError("Feature evidence must be unique and bounded per candidate")
        return self


class CriterionScore(Model):
    criterion: str
    value: float = Field(ge=0, le=1)
    weight: float = Field(ge=0, le=1)
    contribution: float = Field(ge=0, le=100)
    evidence_sources: list[str]
    explanation: str


class RecommendationItem(Model):
    place_id: str
    score: float = Field(ge=0, le=100)
    criteria: list[CriterionScore]
    matched_interests: list[str]
    unresolved_interests: list[str]
    missing_evidence: list[str]
    distance_m: float | None
    distance_method: Literal["haversine_straight_line", "not_computed"]
    is_required: bool
    price_unavailable_reason: (
        Literal["not_supplied", "basis_mismatch", "future_observation", "expired"] | None
    ) = None


class RejectedCandidate(Model):
    place_id: str
    reasons: list[str]
    evidence_sources: list[str] = Field(default_factory=list)


class RecommendationEvaluation(Model):
    items: list[RecommendationItem]
    rejected: list[RejectedCandidate]
    required_conflicts: list[str]
    warnings: list[str]


def prepare_recommendations(data, now):
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Recommendation clock must return an aware datetime")
    ctx = data.context
    # Unknown/unused dimensions do not change the weights of known criteria per candidate.
    active = {
        "interests": bool(data.interests),
        "proximity": ctx.origin is not None,
        "affordability": ctx.max_price_vnd is not None,
        "weather": ctx.weather_risk == "elevated",
    }
    weights = ctx.weights.model_dump()
    denominator = sum(weights[key] for key in weights if active[key])
    weights = {key: weights[key] / denominator if denominator and active[key] else 0 for key in weights}
    items, rejected = [], []
    for place in data.candidates:
        if place.id in data.excluded_place_ids:
            rejected.append(RejectedCandidate(place_id=place.id, reasons=["excluded_by_user"]))
            continue
        facts = {fact.feature: fact for fact in ctx.features.get(place.id, [])}
        type_topics = {TYPE_TOPICS[t] for t in place.types if t in TYPE_TOPICS}
        source = place.source_url or place.source

        def feature_value(key):
            if key in facts:
                return facts[key].value, facts[key].source
            if key in type_topics:
                return True, place.field_sources.get("types", source)
            return None, None

        missing, reasons, matched, unresolved, rejection_sources = [], [], [], [], []
        for key in ctx.required_features:
            value, feature_source = feature_value(key)
            if value is False:
                reasons.append(f"required_feature_false:{key}")
                rejection_sources.append(feature_source)
            elif value is None:
                missing.append(f"required_feature:{key}")
                if ctx.unknown_policy == "exclude":
                    reasons.append(f"required_feature_unknown:{key}")
        distance = None
        if ctx.origin is not None:
            distance = distance_m(
                (ctx.origin.latitude, ctx.origin.longitude), (place.latitude, place.longitude)
            )
            if ctx.max_distance_m is not None and distance > ctx.max_distance_m:
                reasons.append("outside_distance_limit")
                rejection_sources.append(source)
        price = ctx.prices.get(place.id)
        price_reason = "not_supplied" if price is None else None
        if price is not None:
            if price.basis != ctx.price_basis:
                price_reason = "basis_mismatch"
            elif price.observed_at > now:
                price_reason = "future_observation"
            elif price.valid_until is not None and price.valid_until <= now:
                price_reason = "expired"
        if price_reason:
            price = None
        if ctx.max_price_vnd is not None:
            if price is None:
                missing.append("price")
                if ctx.unknown_policy == "exclude":
                    reasons.append("price_unknown_or_unusable")
            elif price.min_vnd > ctx.max_price_vnd:
                reasons.append("price_above_limit")
                rejection_sources.append(price.source)
            elif price.max_vnd > ctx.max_price_vnd:
                missing.append("price_range_exceeds_limit")
                if ctx.unknown_policy == "exclude":
                    reasons.append("price_range_exceeds_limit")
                    rejection_sources.append(price.source)
        if reasons:
            rejected.append(
                RejectedCandidate(
                    place_id=place.id,
                    reasons=reasons,
                    evidence_sources=list(dict.fromkeys(rejection_sources)),
                )
            )
            continue
        criteria = []

        def add(key, value, sources, explanation):
            if not weights[key]:
                return
            criteria.append(
                CriterionScore(
                    criterion=key,
                    value=value,
                    weight=weights[key],
                    contribution=100 * weights[key] * value,
                    evidence_sources=list(dict.fromkeys(sources)),
                    explanation=explanation,
                )
            )

        if data.interests:
            interest_sources = []
            for interest in data.interests:
                key = ALIASES.get(normalized(interest))
                value, fact_source = feature_value(key) if key else (None, None)
                if value is True:
                    matched.append(interest)
                    interest_sources.append(fact_source)
                elif value is None:
                    unresolved.append(interest)
            if unresolved:
                missing.append("interests")
            add(
                "interests",
                len(matched) / len(data.interests),
                interest_sources,
                f"{len(matched)}/{len(data.interests)} sở thích khớp taxonomy hoặc bằng chứng được cung cấp.",
            )
        if distance is not None:
            add(
                "proximity",
                max(0, 1 - distance / ctx.proximity_scale_m),
                [source],
                "Khoảng cách đường chim bay theo tọa độ; không phải quãng đường hay thời gian lái xe.",
            )
        if ctx.max_price_vnd is not None:
            value = max(0, 1 - float(price.max_vnd / ctx.max_price_vnd)) if price else 0
            add(
                "affordability",
                value,
                [price.source] if price else [],
                "So mức giá tối đa với trần cùng đơn vị; thiếu giá nhận 0 điểm tiêu chí và giữ cảnh báo.",
            )
        if ctx.weather_risk == "elevated":
            indoor, indoor_source = feature_value("indoor")
            outdoor, outdoor_source = feature_value("outdoor")
            if indoor is True and outdoor is not True:
                value, sources = 1, [indoor_source, ctx.weather_source]
            elif indoor is True and outdoor is True:
                value, sources = 0.5, [indoor_source, outdoor_source, ctx.weather_source]
            else:
                value, sources = 0, [ctx.weather_source]
                if indoor is None:
                    missing.append("indoor_weather_suitability")
            add(
                "weather",
                value,
                sources,
                "Ưu tiên có bằng chứng trong nhà khi rủi ro thời tiết cao; không xác nhận an toàn.",
            )
        items.append(
            RecommendationItem(
                place_id=place.id,
                score=min(100, math.fsum(c.contribution for c in criteria)),
                criteria=criteria,
                matched_interests=matched,
                unresolved_interests=unresolved,
                missing_evidence=list(dict.fromkeys(missing)),
                distance_m=distance,
                distance_method="haversine_straight_line" if distance is not None else "not_computed",
                is_required=place.id in data.required_place_ids,
                price_unavailable_reason=price_reason if ctx.max_price_vnd is not None else None,
            )
        )
    eligible = {item.place_id for item in items}
    return RecommendationEvaluation(
        items=items,
        rejected=rejected,
        required_conflicts=sorted(set(data.required_place_ids) - eligible),
        warnings=[
            "Điểm 0–100 là độ khớp theo công thức đầu vào, không phải sao cộng đồng hay xác suất hài lòng.",
            "Bằng chứng và giá do caller cung cấp; công cụ chưa tự xác minh nguồn qua Internet.",
            "Khoảng cách là đường chim bay; Route cần kiểm tra đường đi và thời gian sau khi chọn điểm.",
        ]
        + (["Không có tiêu chí có trọng số đang hoạt động; các điểm bằng nhau."] if not denominator else []),
    )
