from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from provider_core.canonical import (
    CanonicalLeg,
    CanonicalStop,
    Coordinate as ProviderCoordinate,
    DataOrigin,
    MoneyRange,
    TimeEstimate,
    TransitDescriptor,
    TravelMode,
)

from transport_mapping.catalog import (
    CatalogQuery,
    InMemoryGbisCatalogRepository,
    geometry_similarity,
)
from transport_mapping.models import (
    CanonicalRouteCandidate,
    Coordinate,
    MappingGrade,
    PersistedMappingResolution,
    ProviderMappingInput,
    ReviewDisposition,
)
from transport_mapping.pipeline import (
    AcceptedHighMappingEntry,
    InMemoryMappingReviewRepository,
    TransportMappingPipeline,
)


class RecordingAcceptedHighRepository:
    def __init__(self) -> None:
        self.entries: list[AcceptedHighMappingEntry] = []

    def persist(
        self,
        entry: AcceptedHighMappingEntry,
    ) -> PersistedMappingResolution:
        self.entries.append(entry)
        mapping = entry.mapping
        return PersistedMappingResolution(
            entity_mapping_id=str(uuid4()),
            provider_fingerprint=mapping.provider_fingerprint,
            candidate_fingerprint=mapping.candidate_fingerprint,
            route_id=mapping.route_id,
            mapping_version=mapping.mapping_version,
            validity=mapping.validity,
            accepted_at=entry.accepted_at,
        )


def _provider_leg(
    source: ProviderMappingInput,
    *,
    direction: str | None | object = ...,
) -> CanonicalLeg:
    start = datetime(2026, 8, 23, 8, 0, tzinfo=timezone(timedelta(hours=9)))
    descriptor_direction = source.direction if direction is ... else direction
    boarding = CanonicalStop(
        source.boarding.name or "unknown boarding",
        ProviderCoordinate(source.boarding.coordinate.lon, source.boarding.coordinate.lat),  # type: ignore[union-attr]
        source.boarding.external_id,
        source.boarding.sequence,
    )
    alighting = CanonicalStop(
        source.alighting.name or "unknown alighting",
        ProviderCoordinate(source.alighting.coordinate.lon, source.alighting.coordinate.lat),  # type: ignore[union-attr]
        source.alighting.external_id,
        source.alighting.sequence,
    )
    return CanonicalLeg(
        "canonical-leg",
        0,
        TravelMode.BUS,
        boarding,
        alighting,
        TimeEstimate(600, 720, DataOrigin.PROVIDER_ESTIMATE),
        10_000,
        MoneyRange(2_800, 2_800, 2_800, DataOrigin.PROVIDER_ESTIMATE),
        expected_start_at=start,
        expected_end_at=start + timedelta(seconds=600),
        transit=TransitDescriptor(
            route_label=source.route_name,
            external_route_id=source.external_route_id,
            route_type=source.route_type,
            direction=descriptor_direction,  # type: ignore[arg-type]
            branch_id=source.branch_id,
            boarding_sequence=source.boarding.sequence,
            alighting_sequence=source.alighting.sequence,
            terminal_names=(source.origin_terminal, source.destination_terminal),  # type: ignore[arg-type]
        ),
        geometry=tuple(
            ProviderCoordinate(point.lon, point.lat)
            for point in (
                source.geometry
                or (
                    source.boarding.coordinate,  # type: ignore[arg-type]
                    source.alighting.coordinate,  # type: ignore[arg-type]
                )
            )
        ),
    )


def test_catalog_query_is_bounded_and_filters_far_stops(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    near = tuple(
        replace(exact_candidate, route_id=f"near-{index}")
        for index in range(10)
    )
    far = replace(
        exact_candidate,
        route_id="far",
        boarding=replace(
            exact_candidate.boarding,
            coordinate=Coordinate(128.0, 36.0),
        ),
    )
    repository = InMemoryGbisCatalogRepository(near + (far,))

    found = repository.find_candidates(
        CatalogQuery(provider_input, evaluated_at, max_candidates=3)
    )

    assert len(found) == 3
    assert all(candidate.route_id.startswith("near-") for candidate in found)


def test_catalog_ranks_name_type_terminal_and_geometry_evidence(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    source = replace(
        provider_input,
        geometry=(provider_input.boarding.coordinate, provider_input.alighting.coordinate),  # type: ignore[arg-type]
    )
    exact = replace(
        exact_candidate,
        route_id="exact",
        geometry=(exact_candidate.boarding.coordinate, exact_candidate.alighting.coordinate),  # type: ignore[arg-type]
    )
    weaker = replace(
        exact,
        route_id="weaker",
        route_type="일반",
        origin_terminal="다른기점",
        geometry=(Coordinate(127.5, 37.8), Coordinate(127.6, 37.9)),
    )
    repository = InMemoryGbisCatalogRepository((weaker, exact))

    found = repository.find_candidates(CatalogQuery(source, evaluated_at))

    assert tuple(candidate.route_id for candidate in found) == ("exact", "weaker")
    assert found[0].geometry_similarity_to_provider is not None
    assert geometry_similarity(source.geometry, exact.geometry) is not None


def test_pipeline_selects_high_and_exposes_versioned_cache_key(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    review = InMemoryMappingReviewRepository()
    pipeline = TransportMappingPipeline(
        InMemoryGbisCatalogRepository((exact_candidate,)),
        review,
    )

    output = pipeline.map_bus_leg(
        "KAKAO_TRANSIT",
        _provider_leg(provider_input),
        evaluated_at=evaluated_at,
    )

    assert output.selected is not None
    assert output.selected.grade is MappingGrade.HIGH
    assert output.allows_bus_intelligence is True
    assert output.selected_cache_key is not None
    assert output.selected_resolution is None
    assert output.selected_entity_mapping_id is None
    assert output.review_ticket_id is None
    assert review.entries == ()


def test_pipeline_exposes_only_committed_typed_high_resolution(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    accepted = RecordingAcceptedHighRepository()
    persisted_candidate = replace(exact_candidate, route_id=str(uuid4()))
    pipeline = TransportMappingPipeline(
        InMemoryGbisCatalogRepository((persisted_candidate,)),
        InMemoryMappingReviewRepository(),
        accepted,
    )

    output = pipeline.map_bus_leg(
        "KAKAO_TRANSIT",
        _provider_leg(provider_input),
        evaluated_at=evaluated_at,
    )

    assert output.selected is not None
    assert output.selected.grade is MappingGrade.HIGH
    assert output.selected_resolution is not None
    assert output.selected_entity_mapping_id == output.selected_resolution.entity_mapping_id
    assert output.selected_resolution.route_id == output.selected.route_id
    assert output.selected_resolution.mapping_version == output.selected.mapping_version
    assert len(accepted.entries) == 1
    assert accepted.entries[0].mapping.review.disposition is ReviewDisposition.AUTO_ACCEPT


def test_pipeline_never_persists_medium_or_low_as_accepted(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    accepted = RecordingAcceptedHighRepository()
    medium = replace(exact_candidate, direction=None)
    pipeline = TransportMappingPipeline(
        InMemoryGbisCatalogRepository((medium,)),
        InMemoryMappingReviewRepository(),
        accepted,
    )

    output = pipeline.map_bus_leg(
        "TMAP_TRANSIT",
        _provider_leg(provider_input, direction=None),
        evaluated_at=evaluated_at,
    )

    assert output.selected is not None
    assert output.selected.grade is MappingGrade.MEDIUM
    assert output.allows_bus_intelligence is False
    assert output.selected_entity_mapping_id is None
    assert accepted.entries == []


def test_pipeline_persists_medium_review_idempotently(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    review = InMemoryMappingReviewRepository()
    candidate = replace(exact_candidate, direction=None)
    pipeline = TransportMappingPipeline(
        InMemoryGbisCatalogRepository((candidate,)),
        review,
    )
    leg = _provider_leg(provider_input, direction=None)

    first = pipeline.map_bus_leg("TMAP", leg, evaluated_at=evaluated_at)
    second = pipeline.map_bus_leg("TMAP", leg, evaluated_at=evaluated_at)

    assert first.selected is not None
    assert first.selected.grade is MappingGrade.MEDIUM
    assert first.allows_bus_intelligence is False
    assert first.review_ticket_id == second.review_ticket_id
    assert len(review.entries) == 1


def test_pipeline_demotes_ambiguous_high_candidates_to_review(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    review = InMemoryMappingReviewRepository()
    alternative = replace(exact_candidate, route_id="alternative-route")
    pipeline = TransportMappingPipeline(
        InMemoryGbisCatalogRepository((exact_candidate, alternative)),
        review,
    )

    output = pipeline.map_bus_leg(
        "ODSAY",
        _provider_leg(provider_input),
        evaluated_at=evaluated_at,
    )

    assert output.selected is not None
    assert output.selected.grade is MappingGrade.MEDIUM
    assert output.selected.review.disposition is ReviewDisposition.QUEUE
    assert output.selected.review.reasons == ("AMBIGUOUS_TOP_CANDIDATES",)
    assert output.allows_bus_intelligence is False
    assert len(review.entries) == 1
