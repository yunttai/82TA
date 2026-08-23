from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from transport_mapping.fingerprint import (
    candidate_fingerprint,
    mapping_cache_key,
    provider_fingerprint,
)
from transport_mapping.models import CanonicalRouteCandidate, ProviderMappingInput
from transport_mapping.normalization import (
    normalize_branch,
    normalize_direction,
    normalize_route_name,
    normalize_stop_name,
)


def test_normalization_is_conservative_and_unicode_stable() -> None:
    assert normalize_route_name(" Ｍ5107 번 버스 ") == "m5107"
    assert normalize_stop_name("판교역·동편 버스정류장") == "판교역동편"
    assert normalize_direction("상행선") == "UP"
    assert normalize_direction("하행") == "DOWN"
    assert normalize_branch(" branch-A ") == "BRANCHA"


def test_provider_fingerprint_is_stable_across_formatting(
    provider_input: ProviderMappingInput,
) -> None:
    reformatted = replace(
        provider_input,
        provider="kakao transit",
        route_name="Ｍ５１０７번버스",
        direction="상행",
        branch_id=" a ",
    )

    assert provider_fingerprint(provider_input) == provider_fingerprint(reformatted)


def test_identity_change_changes_fingerprint(provider_input: ProviderMappingInput) -> None:
    changed = replace(
        provider_input,
        boarding=replace(provider_input.boarding, sequence=13),
    )
    assert provider_fingerprint(provider_input) != provider_fingerprint(changed)


def test_candidate_fingerprint_excludes_volatile_evidence(
    exact_candidate: CanonicalRouteCandidate,
) -> None:
    changed_live = replace(
        exact_candidate,
        live_vehicle_exists=False,
        geometry_similarity_to_provider=0.1,
    )
    assert candidate_fingerprint(exact_candidate) == candidate_fingerprint(changed_live)


def test_cache_key_requires_mapping_version_and_validity(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    provider_identity = provider_fingerprint(provider_input)
    candidate_identity = candidate_fingerprint(exact_candidate)
    first = mapping_cache_key(
        provider_identity,
        candidate_identity,
        "0.1.0-planned",
        valid_from=exact_candidate.validity.valid_from,
        valid_to=exact_candidate.validity.valid_to,
    )
    changed_version = mapping_cache_key(
        provider_identity,
        candidate_identity,
        "0.2.0",
        valid_from=exact_candidate.validity.valid_from,
        valid_to=exact_candidate.validity.valid_to,
    )
    assert first != changed_version


def test_cache_key_normalizes_equivalent_validity_instants(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
) -> None:
    provider_identity = provider_fingerprint(provider_input)
    candidate_identity = candidate_fingerprint(exact_candidate)
    utc = datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc)
    kst = datetime(2026, 8, 23, 9, 0, tzinfo=timezone(timedelta(hours=9)))

    first = mapping_cache_key(
        provider_identity,
        candidate_identity,
        "0.1.0-planned",
        valid_from=utc,
        valid_to=None,
    )
    second = mapping_cache_key(
        provider_identity,
        candidate_identity,
        "0.1.0-planned",
        valid_from=kst,
        valid_to=None,
    )
    assert first == second
