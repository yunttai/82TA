"""Precision-first route/stop/direction mapping policy."""

from __future__ import annotations

from datetime import datetime
from math import asin, cos, radians, sin, sqrt

from .fingerprint import candidate_fingerprint, provider_fingerprint
from .models import (
    CanonicalRouteCandidate,
    Coordinate,
    MappingGrade,
    MappingResult,
    ProviderMappingInput,
    ReviewDecision,
    ReviewDisposition,
    ScoreBreakdown,
    SignalEvidence,
)
from .normalization import (
    name_similarity,
    normalize_branch,
    normalize_direction,
    normalize_stop_name,
    normalize_type,
)


DEFAULT_MAPPING_VERSION = "0.1.0-planned"
HIGH_THRESHOLD = 0.92
MEDIUM_THRESHOLD = 0.80

_WEIGHTS = {
    "route_name": 0.16,
    "route_type": 0.06,
    "boarding_name": 0.07,
    "boarding_coordinate": 0.10,
    "alighting_name": 0.07,
    "alighting_coordinate": 0.10,
    "sequence": 0.12,
    "direction": 0.12,
    "branch": 0.08,
    "terminals": 0.05,
    "geometry": 0.03,
    "live_vehicle": 0.01,
    "turning_point": 0.03,
}


def _exact(left: str | None, right: str | None, normalizer) -> float | None:
    a = normalizer(left)
    b = normalizer(right)
    if a is None or b is None:
        return None
    return 1.0 if a == b else 0.0


def _haversine_meters(left: Coordinate, right: Coordinate) -> float:
    earth_radius_m = 6_371_000
    lat1, lat2 = radians(left.lat), radians(right.lat)
    delta_lat = radians(right.lat - left.lat)
    delta_lon = radians(right.lon - left.lon)
    value = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(value))


def _coordinate_similarity(left: Coordinate | None, right: Coordinate | None) -> float | None:
    if left is None or right is None:
        return None
    distance = _haversine_meters(left, right)
    if distance <= 30:
        return 1.0
    if distance >= 300:
        return 0.0
    return round(1 - ((distance - 30) / 270), 6)


def _sequence_similarity(source: ProviderMappingInput, target: CanonicalRouteCandidate) -> float | None:
    values = (
        source.boarding.sequence,
        source.alighting.sequence,
        target.boarding.sequence,
        target.alighting.sequence,
    )
    if any(value is None for value in values):
        return None
    source_delta = values[1] - values[0]  # type: ignore[operator]
    target_delta = values[3] - values[2]  # type: ignore[operator]
    if source_delta <= 0 or target_delta <= 0:
        return 0.0
    return round(1 - min(abs(source_delta - target_delta) / max(source_delta, target_delta), 1), 6)


def _terminal_similarity(source: ProviderMappingInput, target: CanonicalRouteCandidate) -> float | None:
    origin = name_similarity(source.origin_terminal, target.origin_terminal, kind="stop")
    destination = name_similarity(
        source.destination_terminal,
        target.destination_terminal,
        kind="stop",
    )
    available = [value for value in (origin, destination) if value is not None]
    return round(sum(available) / len(available), 6) if available else None


def _live_similarity(value: bool | None) -> float | None:
    if value is None:
        return None
    return 1.0 if value else 0.0


def _turning_position(
    turning: int | None,
    boarding: int | None,
    alighting: int | None,
) -> str | None:
    if turning is None or boarding is None or alighting is None:
        return None
    if turning <= boarding:
        return "BEFORE_OR_AT_BOARDING"
    if turning >= alighting:
        return "AFTER_OR_AT_ALIGHTING"
    return "BETWEEN_STOPS"


def _turning_point_similarity(
    source: ProviderMappingInput,
    target: CanonicalRouteCandidate,
) -> float | None:
    # No turning point in the GBIS segment is an explicitly validated
    # not-applicable state.  If GBIS says the segment has one, provider evidence
    # must independently locate it before HIGH can be reached.
    if target.turning_point_sequence is None:
        return 1.0 if source.turning_point_sequence is None else 0.0
    source_position = _turning_position(
        source.turning_point_sequence,
        source.boarding.sequence,
        source.alighting.sequence,
    )
    target_position = _turning_position(
        target.turning_point_sequence,
        target.boarding.sequence,
        target.alighting.sequence,
    )
    if source_position is None or target_position is None:
        return None
    return 1.0 if source_position == target_position else 0.0


def _build_breakdown(similarities: dict[str, float | None]) -> ScoreBreakdown:
    evidence = tuple(
        SignalEvidence(
            name=name,
            weight=weight,
            available=similarities[name] is not None,
            similarity=similarities[name],
            contribution=round(weight * (similarities[name] or 0), 6),
        )
        for name, weight in _WEIGHTS.items()
    )
    available_weight = round(sum(item.weight for item in evidence if item.available), 6)
    contribution = sum(item.contribution for item in evidence)
    weighted_similarity = (
        round(contribution / available_weight, 6) if available_weight else 0.0
    )
    return ScoreBreakdown(
        signals=evidence,
        available_weight=available_weight,
        weighted_similarity=weighted_similarity,
    )


def _blockers(
    source: ProviderMappingInput,
    target: CanonicalRouteCandidate,
    *,
    evaluated_at: datetime,
    sequence_similarity: float | None,
    turning_point_similarity: float | None,
) -> tuple[str, ...]:
    blockers: list[str] = []
    source_direction = normalize_direction(source.direction)
    target_direction = normalize_direction(target.direction)
    if (
        source_direction is not None
        and target_direction is not None
        and source_direction != target_direction
    ):
        blockers.append("OPPOSITE_DIRECTION")
    source_branch = normalize_branch(source.branch_id)
    target_branch = normalize_branch(target.branch_id)
    if source_branch is not None and target_branch is not None and source_branch != target_branch:
        blockers.append("BRANCH_MISMATCH")
    if sequence_similarity == 0:
        source_delta = (
            None
            if source.boarding.sequence is None or source.alighting.sequence is None
            else source.alighting.sequence - source.boarding.sequence
        )
        target_delta = (
            None
            if target.boarding.sequence is None or target.alighting.sequence is None
            else target.alighting.sequence - target.boarding.sequence
        )
        if source_delta is not None and target_delta is not None and (
            source_delta <= 0 or target_delta <= 0
        ):
            blockers.append("SEQUENCE_DIRECTION_MISMATCH")
    if not target.validity.contains(evaluated_at):
        blockers.append("CANDIDATE_OUTSIDE_VALIDITY")
    if turning_point_similarity == 0:
        blockers.append("TURNING_POINT_MISMATCH")
    return tuple(blockers)


def _high_prerequisites(breakdown: ScoreBreakdown) -> bool:
    def value(name: str) -> float | None:
        return breakdown.signal(name).similarity

    required = {
        "route_name": 0.98,
        "boarding_name": 0.80,
        "boarding_coordinate": 0.65,
        "alighting_name": 0.80,
        "alighting_coordinate": 0.65,
        "sequence": 0.75,
        "direction": 1.0,
        "turning_point": 1.0,
    }
    return breakdown.available_weight >= 0.65 and all(
        value(name) is not None and value(name) >= minimum
        for name, minimum in required.items()
    )


def _medium_prerequisites(breakdown: ScoreBreakdown) -> bool:
    route = breakdown.signal("route_name").similarity
    boarding = (
        breakdown.signal("boarding_name").similarity,
        breakdown.signal("boarding_coordinate").similarity,
    )
    alighting = (
        breakdown.signal("alighting_name").similarity,
        breakdown.signal("alighting_coordinate").similarity,
    )
    structural = (
        breakdown.signal("sequence").similarity,
        breakdown.signal("direction").similarity,
    )
    return (
        breakdown.available_weight >= 0.40
        and route is not None
        and route >= 0.80
        and any(value is not None and value >= 0.65 for value in boarding)
        and any(value is not None and value >= 0.65 for value in alighting)
        and any(value is not None and value >= 0.75 for value in structural)
    )


def _grade(breakdown: ScoreBreakdown, blockers: tuple[str, ...]) -> MappingGrade:
    if blockers:
        return MappingGrade.LOW
    score = breakdown.weighted_similarity
    if score >= HIGH_THRESHOLD and _high_prerequisites(breakdown):
        return MappingGrade.HIGH
    if score >= MEDIUM_THRESHOLD and _medium_prerequisites(breakdown):
        return MappingGrade.MEDIUM
    return MappingGrade.LOW


def _review(
    grade: MappingGrade,
    score: float,
    available_weight: float,
    blockers: tuple[str, ...],
) -> ReviewDecision:
    if grade is MappingGrade.HIGH:
        return ReviewDecision(ReviewDisposition.AUTO_ACCEPT)
    if blockers:
        return ReviewDecision(ReviewDisposition.REJECT, blockers)
    if grade is MappingGrade.MEDIUM:
        return ReviewDecision(ReviewDisposition.QUEUE, ("MEDIUM_CONFIDENCE",))
    if score >= 0.65 and available_weight >= 0.40:
        return ReviewDecision(ReviewDisposition.QUEUE, ("AMBIGUOUS_LOW_CONFIDENCE",))
    return ReviewDecision(ReviewDisposition.REJECT, ("INSUFFICIENT_EVIDENCE",))


def map_candidate(
    source: ProviderMappingInput,
    target: CanonicalRouteCandidate,
    *,
    evaluated_at: datetime,
    mapping_version: str = DEFAULT_MAPPING_VERSION,
) -> MappingResult:
    """Score one candidate without network, ORM, clock, or provider dependencies."""

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    if not mapping_version.strip():
        raise ValueError("mapping_version must be non-blank")

    sequence = _sequence_similarity(source, target)
    turning_point = _turning_point_similarity(source, target)
    similarities = {
        "route_name": name_similarity(source.route_name, target.route_name, kind="route"),
        "route_type": _exact(source.route_type, target.route_type, normalize_type),
        "boarding_name": name_similarity(source.boarding.name, target.boarding.name, kind="stop"),
        "boarding_coordinate": _coordinate_similarity(
            source.boarding.coordinate,
            target.boarding.coordinate,
        ),
        "alighting_name": name_similarity(source.alighting.name, target.alighting.name, kind="stop"),
        "alighting_coordinate": _coordinate_similarity(
            source.alighting.coordinate,
            target.alighting.coordinate,
        ),
        "sequence": sequence,
        "direction": _exact(source.direction, target.direction, normalize_direction),
        "branch": _exact(source.branch_id, target.branch_id, normalize_branch),
        "terminals": _terminal_similarity(source, target),
        "geometry": target.geometry_similarity_to_provider,
        "live_vehicle": _live_similarity(target.live_vehicle_exists),
        "turning_point": turning_point,
    }
    breakdown = _build_breakdown(similarities)
    blockers = _blockers(
        source,
        target,
        evaluated_at=evaluated_at,
        sequence_similarity=sequence,
        turning_point_similarity=turning_point,
    )
    grade = _grade(breakdown, blockers)
    review = _review(
        grade,
        breakdown.weighted_similarity,
        breakdown.available_weight,
        blockers,
    )
    return MappingResult(
        provider_fingerprint=provider_fingerprint(source),
        candidate_fingerprint=candidate_fingerprint(target),
        route_id=target.route_id,
        score=breakdown.weighted_similarity,
        grade=grade,
        breakdown=breakdown,
        mapping_version=mapping_version,
        validity=target.validity,
        evaluated_at=evaluated_at,
        blockers=blockers,
        review=review,
    )
