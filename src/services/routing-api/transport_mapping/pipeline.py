"""Bounded provider-canonical to GBIS mapping workflow."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Mapping, Protocol

from .catalog import CatalogQuery, GbisCatalogRepository
from .extractors import CanonicalBusLegLike, extract_provider_identity
from .fingerprint import candidate_fingerprint, mapping_cache_key
from .models import (
    Coordinate,
    MappingGrade,
    MappingResult,
    PersistedMappingResolution,
    ProviderMappingInput,
    ReviewDecision,
    ReviewDisposition,
    ValidityWindow,
)
from .normalization import (
    normalize_branch,
    normalize_direction,
    normalize_route_name,
    normalize_stop_name,
    normalize_type,
)
from .scoring import DEFAULT_MAPPING_VERSION, map_candidate


@dataclass(frozen=True, slots=True)
class ReviewQueueEntry:
    cache_key: str
    provider: str
    provider_fingerprint: str
    candidate_fingerprint: str
    route_id: str
    grade: MappingGrade
    score: float
    mapping_version: str
    validity: ValidityWindow
    reasons: tuple[str, ...]
    requested_at: datetime
    provider_external_id: str
    provider_identity: Mapping[str, object]
    signal_breakdown: Mapping[str, object]
    direction: str | None


class MappingReviewRepository(Protocol):
    def enqueue(self, entry: ReviewQueueEntry) -> str: ...


@dataclass(frozen=True, slots=True)
class AcceptedHighMappingEntry:
    """Persistence command for a policy-accepted, current HIGH mapping."""

    cache_key: str
    provider: str
    provider_external_id: str
    provider_identity: Mapping[str, object]
    signal_breakdown: Mapping[str, object]
    direction: str | None
    mapping: MappingResult
    accepted_at: datetime

    def __post_init__(self) -> None:
        if self.mapping.grade is not MappingGrade.HIGH:
            raise ValueError("only HIGH mappings can be durably accepted")
        if self.mapping.review.disposition is not ReviewDisposition.AUTO_ACCEPT:
            raise ValueError("durable HIGH mapping must be policy accepted")
        if self.mapping.blockers or not self.mapping.allows_bus_intelligence:
            raise ValueError("blocked mappings cannot be durably accepted")
        if not self.mapping.validity.contains(self.accepted_at):
            raise ValueError("accepted mapping must be current")


class AcceptedHighMappingRepository(Protocol):
    def persist(
        self,
        entry: AcceptedHighMappingEntry,
    ) -> PersistedMappingResolution: ...


class InMemoryMappingReviewRepository:
    """Idempotent reference persistence keyed by the versioned mapping key."""

    def __init__(self) -> None:
        self._entries: dict[str, ReviewQueueEntry] = {}

    def enqueue(self, entry: ReviewQueueEntry) -> str:
        self._entries.setdefault(entry.cache_key, entry)
        return entry.cache_key

    @property
    def entries(self) -> tuple[ReviewQueueEntry, ...]:
        return tuple(self._entries[key] for key in sorted(self._entries))


@dataclass(frozen=True, slots=True)
class MappingPipelineResult:
    source: ProviderMappingInput
    evaluated: tuple[MappingResult, ...]
    selected: MappingResult | None
    selected_cache_key: str | None
    review_ticket_id: str | None
    selected_resolution: PersistedMappingResolution | None = None

    def __post_init__(self) -> None:
        resolution = self.selected_resolution
        if resolution is None:
            return
        if self.selected is None or self.selected_cache_key is None:
            raise ValueError("durable resolution requires a selected mapping")
        if self.selected.grade is not MappingGrade.HIGH:
            raise ValueError("durable resolution requires selected HIGH mapping")
        if (
            resolution.provider_fingerprint != self.selected.provider_fingerprint
            or resolution.candidate_fingerprint != self.selected.candidate_fingerprint
            or resolution.route_id != self.selected.route_id
            or resolution.mapping_version != self.selected.mapping_version
            or resolution.validity != self.selected.validity
            or resolution.accepted_at != self.selected.evaluated_at
        ):
            raise ValueError("durable resolution does not match selected mapping")

    @property
    def selected_entity_mapping_id(self) -> str | None:
        resolution = self.selected_resolution
        return None if resolution is None else resolution.entity_mapping_id

    @property
    def allows_bus_intelligence(self) -> bool:
        return self.selected is not None and self.selected.allows_bus_intelligence


def _grade_order(value: MappingGrade) -> int:
    return {
        MappingGrade.HIGH: 2,
        MappingGrade.MEDIUM: 1,
        MappingGrade.LOW: 0,
    }[value]


def _ambiguous(top: MappingResult, second: MappingResult, margin: float) -> bool:
    return (
        top.grade is MappingGrade.HIGH
        and second.grade is MappingGrade.HIGH
        and top.candidate_fingerprint != second.candidate_fingerprint
        and top.score - second.score <= margin
    )


def _demote_ambiguous(value: MappingResult) -> MappingResult:
    return replace(
        value,
        grade=MappingGrade.MEDIUM,
        review=ReviewDecision(
            ReviewDisposition.QUEUE,
            ("AMBIGUOUS_TOP_CANDIDATES",),
        ),
    )


def _coordinate_identity(value: Coordinate | None) -> object:
    if value is None:
        return None
    return [round(value.lon, 6), round(value.lat, 6)]


def _provider_identity(value: ProviderMappingInput) -> dict[str, object]:
    return {
        "provider": normalize_type(value.provider),
        "externalRouteId": normalize_branch(value.external_route_id),
        "routeName": normalize_route_name(value.route_name),
        "routeType": normalize_type(value.route_type),
        "boarding": {
            "name": normalize_stop_name(value.boarding.name),
            "coordinate": _coordinate_identity(value.boarding.coordinate),
            "externalId": normalize_branch(value.boarding.external_id),
            "sequence": value.boarding.sequence,
        },
        "alighting": {
            "name": normalize_stop_name(value.alighting.name),
            "coordinate": _coordinate_identity(value.alighting.coordinate),
            "externalId": normalize_branch(value.alighting.external_id),
            "sequence": value.alighting.sequence,
        },
        "direction": normalize_direction(value.direction),
        "branchId": normalize_branch(value.branch_id),
        "originTerminal": normalize_stop_name(value.origin_terminal),
        "destinationTerminal": normalize_stop_name(value.destination_terminal),
        "turningPointSequence": value.turning_point_sequence,
    }


def _signal_breakdown(value: MappingResult, cache_key: str) -> dict[str, object]:
    return {
        "mappingCacheKey": cache_key,
        "providerFingerprint": value.provider_fingerprint,
        "candidateFingerprint": value.candidate_fingerprint,
        "mappingVersion": value.mapping_version,
        "reviewDisposition": value.review.disposition.value,
        "availableWeight": value.breakdown.available_weight,
        "weightedSimilarity": value.breakdown.weighted_similarity,
        "signals": [
            {
                "name": signal.name,
                "weight": signal.weight,
                "available": signal.available,
                "similarity": signal.similarity,
                "contribution": signal.contribution,
            }
            for signal in value.breakdown.signals
        ],
        "blockers": list(value.blockers),
        "reviewReasons": list(value.review.reasons),
    }


class TransportMappingPipeline:
    def __init__(
        self,
        catalog: GbisCatalogRepository,
        review_repository: MappingReviewRepository,
        accepted_repository: AcceptedHighMappingRepository | None = None,
        *,
        max_candidates: int = 16,
        stop_radius_meters: int = 500,
        ambiguity_margin: float = 0.01,
    ) -> None:
        if not 0 <= ambiguity_margin <= 1:
            raise ValueError("ambiguity_margin must be between 0 and 1")
        # CatalogQuery centralizes the production bounds and validates them.
        self._max_candidates = max_candidates
        self._stop_radius_meters = stop_radius_meters
        self._ambiguity_margin = ambiguity_margin
        self._catalog = catalog
        self._review_repository = review_repository
        self._accepted_repository = accepted_repository

    def map_bus_leg(
        self,
        provider_code: str,
        leg: CanonicalBusLegLike,
        *,
        evaluated_at: datetime,
        mapping_version: str = DEFAULT_MAPPING_VERSION,
    ) -> MappingPipelineResult:
        source = extract_provider_identity(provider_code, leg)
        query = CatalogQuery(
            source=source,
            as_of=evaluated_at,
            max_candidates=self._max_candidates,
            stop_radius_meters=self._stop_radius_meters,
        )
        records = self._catalog.find_candidates(query)

        # Defend against a persistence adapter that violates the query cap or
        # returns duplicate master rows.
        unique = []
        seen: set[str] = set()
        for record in records[: query.max_candidates]:
            identity = candidate_fingerprint(record)
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(record)

        evaluated = tuple(
            map_candidate(
                source,
                record,
                evaluated_at=evaluated_at,
                mapping_version=mapping_version,
            )
            for record in unique
        )
        ordered = tuple(
            sorted(
                evaluated,
                key=lambda result: (
                    -_grade_order(result.grade),
                    -result.score,
                    result.route_id,
                ),
            )
        )
        if not ordered:
            return MappingPipelineResult(source, (), None, None, None)

        selected = ordered[0]
        if len(ordered) > 1 and _ambiguous(
            selected,
            ordered[1],
            self._ambiguity_margin,
        ):
            selected = _demote_ambiguous(selected)

        cache_key = mapping_cache_key(
            selected.provider_fingerprint,
            selected.candidate_fingerprint,
            selected.mapping_version,
            valid_from=selected.validity.valid_from,
            valid_to=selected.validity.valid_to,
        )
        review_ticket = None
        if selected.review.should_queue:
            review_ticket = self._review_repository.enqueue(
                ReviewQueueEntry(
                    cache_key=cache_key,
                    provider=source.provider,
                    provider_fingerprint=selected.provider_fingerprint,
                    candidate_fingerprint=selected.candidate_fingerprint,
                    route_id=selected.route_id,
                    grade=selected.grade,
                    score=selected.score,
                    mapping_version=selected.mapping_version,
                    validity=selected.validity,
                    reasons=selected.review.reasons,
                    requested_at=evaluated_at,
                    provider_external_id=(
                        source.external_route_id or selected.provider_fingerprint
                    ),
                    provider_identity=_provider_identity(source),
                    signal_breakdown=_signal_breakdown(selected, cache_key),
                    direction=source.direction,
                )
            )
        selected_resolution = None
        if (
            self._accepted_repository is not None
            and selected.grade is MappingGrade.HIGH
            and selected.review.disposition is ReviewDisposition.AUTO_ACCEPT
        ):
            selected_resolution = self._accepted_repository.persist(
                AcceptedHighMappingEntry(
                    cache_key=cache_key,
                    provider=source.provider,
                    provider_external_id=(
                        source.external_route_id or selected.provider_fingerprint
                    ),
                    provider_identity=_provider_identity(source),
                    signal_breakdown=_signal_breakdown(selected, cache_key),
                    direction=normalize_direction(source.direction),
                    mapping=selected,
                    accepted_at=evaluated_at,
                )
            )
        return MappingPipelineResult(
            source=source,
            evaluated=ordered,
            selected=selected,
            selected_cache_key=cache_key,
            review_ticket_id=review_ticket,
            selected_resolution=selected_resolution,
        )
