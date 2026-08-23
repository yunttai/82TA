from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from transport_mapping.models import (
    CanonicalRouteCandidate,
    MappingGrade,
    ProviderMappingInput,
    ReviewDisposition,
    StopSignal,
    ValidityWindow,
)
from transport_mapping.scoring import map_candidate


def test_strong_independent_evidence_is_high_and_enables_bus_intelligence(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    result = map_candidate(provider_input, exact_candidate, evaluated_at=evaluated_at)

    assert result.grade is MappingGrade.HIGH
    assert result.score >= 0.92
    assert result.allows_bus_intelligence is True
    assert result.review.disposition is ReviewDisposition.AUTO_ACCEPT
    assert result.mapping_version == "0.1.0-planned"
    assert result.blockers == ()


def test_route_number_alone_never_yields_high(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    sparse_source = ProviderMappingInput(
        provider=provider_input.provider,
        external_route_id=None,
        route_name="M5107",
        route_type=None,
        boarding=StopSignal(),
        alighting=StopSignal(),
    )
    sparse_target = replace(
        exact_candidate,
        route_type=None,
        boarding=StopSignal(),
        alighting=StopSignal(),
        direction=None,
        branch_id=None,
        origin_terminal=None,
        destination_terminal=None,
        geometry_similarity_to_provider=None,
        live_vehicle_exists=None,
    )

    result = map_candidate(sparse_source, sparse_target, evaluated_at=evaluated_at)

    assert result.score == 1.0
    assert result.grade is MappingGrade.LOW
    assert result.allows_bus_intelligence is False
    assert result.review.disposition is ReviewDisposition.REJECT


def test_stop_names_alone_never_yield_high(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    sparse_source = replace(
        provider_input,
        route_name=None,
        route_type=None,
        boarding=StopSignal(name=provider_input.boarding.name),
        alighting=StopSignal(name=provider_input.alighting.name),
        direction=None,
        branch_id=None,
        origin_terminal=None,
        destination_terminal=None,
    )
    sparse_target = replace(
        exact_candidate,
        route_name=None,
        route_type=None,
        boarding=StopSignal(name=exact_candidate.boarding.name),
        alighting=StopSignal(name=exact_candidate.alighting.name),
        direction=None,
        branch_id=None,
        origin_terminal=None,
        destination_terminal=None,
        geometry_similarity_to_provider=None,
        live_vehicle_exists=None,
    )

    result = map_candidate(sparse_source, sparse_target, evaluated_at=evaluated_at)

    assert result.grade is MappingGrade.LOW
    assert result.allows_bus_intelligence is False


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("direction", "하행", "OPPOSITE_DIRECTION"),
        ("branch_id", "B", "BRANCH_MISMATCH"),
    ],
)
def test_direction_and_branch_mismatches_are_hard_blockers(
    field: str,
    value: str,
    blocker: str,
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    target = replace(exact_candidate, **{field: value})

    result = map_candidate(provider_input, target, evaluated_at=evaluated_at)

    assert blocker in result.blockers
    assert result.grade is MappingGrade.LOW
    assert result.allows_bus_intelligence is False
    assert result.review.disposition is ReviewDisposition.REJECT


def test_reversed_stop_sequence_is_hard_blocked(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    target = replace(
        exact_candidate,
        boarding=replace(exact_candidate.boarding, sequence=115),
        alighting=replace(exact_candidate.alighting, sequence=102),
    )

    result = map_candidate(provider_input, target, evaluated_at=evaluated_at)

    assert "SEQUENCE_DIRECTION_MISMATCH" in result.blockers
    assert result.grade is MappingGrade.LOW
    assert result.allows_bus_intelligence is False


def test_missing_direction_caps_a_strong_match_at_medium_and_queues_review(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    source = replace(provider_input, direction=None)
    target = replace(exact_candidate, direction=None)

    result = map_candidate(source, target, evaluated_at=evaluated_at)

    assert result.score >= 0.92
    assert result.grade is MappingGrade.MEDIUM
    assert result.review.should_queue is True
    assert result.allows_bus_intelligence is False


def test_outside_validity_is_low_even_when_signals_match(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    expired = replace(
        exact_candidate,
        validity=ValidityWindow(
            evaluated_at - timedelta(days=2),
            evaluated_at - timedelta(days=1),
        ),
    )

    result = map_candidate(provider_input, expired, evaluated_at=evaluated_at)

    assert result.grade is MappingGrade.LOW
    assert "CANDIDATE_OUTSIDE_VALIDITY" in result.blockers
    assert result.allows_bus_intelligence is False


def test_signal_breakdown_marks_missing_as_unavailable_not_zero(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    target = replace(
        exact_candidate,
        geometry_similarity_to_provider=None,
        live_vehicle_exists=None,
    )

    result = map_candidate(provider_input, target, evaluated_at=evaluated_at)

    geometry = result.breakdown.signal("geometry")
    live = result.breakdown.signal("live_vehicle")
    assert geometry.available is False and geometry.similarity is None
    assert live.available is False and live.similarity is None
    assert result.grade is MappingGrade.HIGH


def test_unverified_turning_point_caps_match_below_high(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    candidate = replace(exact_candidate, turning_point_sequence=110)

    result = map_candidate(provider_input, candidate, evaluated_at=evaluated_at)

    assert result.breakdown.signal("turning_point").available is False
    assert result.grade is MappingGrade.MEDIUM
    assert result.allows_bus_intelligence is False


def test_turning_point_topology_mismatch_is_hard_blocked(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    source = replace(provider_input, turning_point_sequence=18)
    candidate = replace(exact_candidate, turning_point_sequence=100)

    result = map_candidate(source, candidate, evaluated_at=evaluated_at)

    assert "TURNING_POINT_MISMATCH" in result.blockers
    assert result.grade is MappingGrade.LOW
    assert result.allows_bus_intelligence is False


def test_matching_turning_point_topology_can_be_high(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    source = replace(provider_input, turning_point_sequence=18)
    candidate = replace(exact_candidate, turning_point_sequence=110)

    result = map_candidate(source, candidate, evaluated_at=evaluated_at)

    assert result.breakdown.signal("turning_point").similarity == 1.0
    assert result.grade is MappingGrade.HIGH
    assert result.allows_bus_intelligence is True


def test_mapping_requires_timezone_aware_evaluation_time(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        map_candidate(
            provider_input,
            exact_candidate,
            evaluated_at=datetime(2026, 8, 23),
        )


def test_validity_window_is_half_open(evaluated_at: datetime) -> None:
    window = ValidityWindow(evaluated_at, evaluated_at + timedelta(hours=1))
    assert window.contains(evaluated_at)
    assert window.contains(evaluated_at + timedelta(minutes=59))
    assert not window.contains(evaluated_at + timedelta(hours=1))


def test_invalid_window_rejected(evaluated_at: datetime) -> None:
    with pytest.raises(ValueError, match="later"):
        ValidityWindow(evaluated_at, evaluated_at)
