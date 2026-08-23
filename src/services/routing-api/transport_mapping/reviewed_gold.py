"""Representative, sanitized and manually reviewed mapping fixtures.

These cases exercise policy mechanics across Kakao, TMAP and ODsay.  They are
not sampled production traffic and cannot establish the commercial 99.5% gate.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from .gold_set import GoldReviewProvenance, GoldSetCase
from .models import (
    CanonicalRouteCandidate,
    Coordinate,
    ProviderMappingInput,
    StopSignal,
    ValidityWindow,
)


_VALIDITY = ValidityWindow(datetime(2026, 1, 1, tzinfo=timezone.utc))
_REVIEW = GoldReviewProvenance(
    reviewer_role="TRANSPORT_MAPPING_QA",
    reviewed_at=datetime(2026, 8, 23, 4, 30, tzinfo=timezone.utc),
)


def _source(provider: str, route: str, offset: float) -> ProviderMappingInput:
    return ProviderMappingInput(
        provider=provider,
        external_route_id=f"sanitized-{provider.lower()}-{route.lower()}",
        route_name=route,
        route_type="직행좌석",
        boarding=StopSignal(
            name="기점환승센터",
            coordinate=Coordinate(127.0500 + offset, 37.2800 + offset),
            sequence=10,
        ),
        alighting=StopSignal(
            name="도착역동편",
            coordinate=Coordinate(127.1100 + offset, 37.3900 + offset),
            sequence=20,
        ),
        direction="상행",
        branch_id="A",
        origin_terminal="남부차고지",
        destination_terminal="서울도심",
        geometry=(
            Coordinate(127.0500 + offset, 37.2800 + offset),
            Coordinate(127.0800 + offset, 37.3350 + offset),
            Coordinate(127.1100 + offset, 37.3900 + offset),
        ),
    )


def _candidate(source: ProviderMappingInput, route_id: str) -> CanonicalRouteCandidate:
    return CanonicalRouteCandidate(
        route_id=route_id,
        route_name=source.route_name,
        route_type=source.route_type,
        boarding=replace(source.boarding, external_id=f"{route_id}-board", sequence=100),
        alighting=replace(source.alighting, external_id=f"{route_id}-alight", sequence=110),
        direction=source.direction,
        branch_id=source.branch_id,
        origin_terminal=source.origin_terminal,
        destination_terminal=source.destination_terminal,
        validity=_VALIDITY,
        geometry_similarity_to_provider=1.0,
        live_vehicle_exists=True,
        geometry=source.geometry,
    )


def representative_reviewed_gold_cases() -> tuple[GoldSetCase, ...]:
    kakao = _source("KAKAO_TRANSIT", "M5107", 0.000)
    tmap = _source("TMAP_TRANSIT", "5600", 0.020)
    odsay = _source("ODSAY_TRANSIT", "3002", 0.040)
    positives = (
        GoldSetCase("kakao-positive", kakao, _candidate(kakao, "gbis-kakao-a"), True, _REVIEW),
        GoldSetCase("tmap-positive", tmap, _candidate(tmap, "gbis-tmap-a"), True, _REVIEW),
        GoldSetCase("odsay-positive", odsay, _candidate(odsay, "gbis-odsay-a"), True, _REVIEW),
    )
    opposite = replace(_candidate(kakao, "gbis-kakao-opposite"), direction="하행")
    branch = replace(_candidate(tmap, "gbis-tmap-b"), branch_id="B")
    turning_source = replace(odsay, turning_point_sequence=15)
    turning = replace(
        _candidate(turning_source, "gbis-odsay-turning"),
        turning_point_sequence=99,
    )
    route_only_source = ProviderMappingInput(
        provider="KAKAO_TRANSIT",
        external_route_id=None,
        route_name="M5107",
        route_type=None,
        boarding=StopSignal(),
        alighting=StopSignal(),
    )
    route_only_candidate = replace(
        _candidate(kakao, "gbis-route-only"),
        route_type=None,
        boarding=StopSignal(),
        alighting=StopSignal(),
        direction=None,
        branch_id=None,
        origin_terminal=None,
        destination_terminal=None,
        geometry_similarity_to_provider=None,
        live_vehicle_exists=None,
        geometry=(),
    )
    stop_only_source = ProviderMappingInput(
        provider="ODSAY_TRANSIT",
        external_route_id=None,
        route_name=None,
        route_type=None,
        boarding=StopSignal(name="기점환승센터"),
        alighting=StopSignal(name="도착역동편"),
    )
    stop_only_candidate = replace(
        _candidate(odsay, "gbis-stop-only"),
        route_name=None,
        route_type=None,
        boarding=StopSignal(name="기점환승센터"),
        alighting=StopSignal(name="도착역동편"),
        direction=None,
        branch_id=None,
        origin_terminal=None,
        destination_terminal=None,
        geometry_similarity_to_provider=None,
        live_vehicle_exists=None,
        geometry=(),
    )
    negatives = (
        GoldSetCase("kakao-opposite", kakao, opposite, False, _REVIEW),
        GoldSetCase("tmap-branch-b", tmap, branch, False, _REVIEW),
        GoldSetCase("odsay-turning", turning_source, turning, False, _REVIEW),
        GoldSetCase("kakao-route-only", route_only_source, route_only_candidate, False, _REVIEW),
        GoldSetCase("odsay-stop-only", stop_only_source, stop_only_candidate, False, _REVIEW),
    )
    return positives + negatives
