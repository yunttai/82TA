"""GBIS catalog query port and bounded in-memory reference implementation.

The production adapter is expected to implement this port with PostGIS using
the same query bounds.  This module performs no HTTP or database access.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from typing import Mapping, Protocol

from .models import (
    CanonicalRouteCandidate,
    Coordinate,
    GitsRoadLinkIdentity,
    PersistedMappingResolution,
    ProviderMappingInput,
)
from .normalization import name_similarity, normalize_type


MAX_CANDIDATES = 64
MAX_REFERENCE_RECORDS = 1024
MAX_GEOMETRY_SAMPLE_POINTS = 64


def distance_meters(left: Coordinate, right: Coordinate) -> float:
    earth_radius_m = 6_371_000
    lat1, lat2 = radians(left.lat), radians(right.lat)
    delta_lat = radians(right.lat - left.lat)
    delta_lon = radians(right.lon - left.lon)
    value = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(value))


@dataclass(frozen=True, slots=True)
class CatalogQuery:
    source: ProviderMappingInput
    as_of: datetime
    max_candidates: int = 16
    stop_radius_meters: int = 500
    min_route_name_similarity: float = 0.55

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if not 1 <= self.max_candidates <= MAX_CANDIDATES:
            raise ValueError(f"max_candidates must be between 1 and {MAX_CANDIDATES}")
        if not 1 <= self.stop_radius_meters <= 2_000:
            raise ValueError("stop_radius_meters must be between 1 and 2000")
        if not 0 <= self.min_route_name_similarity <= 1:
            raise ValueError("min_route_name_similarity must be between 0 and 1")


class GbisCatalogRepository(Protocol):
    """Persistence port; a PostGIS implementation must honor every query bound."""

    def find_candidates(
        self,
        query: CatalogQuery,
    ) -> tuple[CanonicalRouteCandidate, ...]: ...


class GitsRoadLinkIdentityRepository(Protocol):
    """Resolve only durable GITS identities already accepted for route directions."""

    def find_for_targets(
        self,
        targets: tuple[tuple[str, str], ...],
        *,
        as_of: datetime,
    ) -> Mapping[tuple[str, str], GitsRoadLinkIdentity]: ...


class DisabledGitsRoadLinkIdentityRepository:
    """Explicit zero-I/O adapter for scoring catalogs and disabled capability."""

    def find_for_targets(
        self,
        targets: tuple[tuple[str, str], ...],
        *,
        as_of: datetime,
    ) -> Mapping[tuple[str, str], GitsRoadLinkIdentity]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return {}


def enrich_selected_gits_road_link_target(
    target: CanonicalRouteCandidate,
    resolution: PersistedMappingResolution,
    repository: GitsRoadLinkIdentityRepository,
    *,
    as_of: datetime,
) -> CanonicalRouteCandidate:
    """Perform one fail-closed lookup after a typed accepted HIGH resolution."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    without_identity = replace(target, gits_road_link_identity=None)
    if (
        target.direction is None
        or resolution.route_id != target.route_id
        or resolution.accepted_at > as_of
        or not resolution.validity.contains(as_of)
        or not target.validity.contains(as_of)
    ):
        return without_identity
    try:
        identities = repository.find_for_targets(
            ((target.route_id, target.direction),),
            as_of=as_of,
        )
    except Exception:
        # The repository is an optional traffic-context seam. Driver failures,
        # schema rejection and deadline exhaustion must not downgrade canonical
        # bus mapping or fabricate a spatial substitute.
        return without_identity
    identity = identities.get((target.route_id, target.direction))
    if identity is None or not identity.validity.contains(as_of):
        return without_identity
    return replace(without_identity, gits_road_link_identity=identity)


@dataclass(frozen=True, slots=True)
class GitsRoadLinkIdentityRecord:
    route_id: str
    direction: str
    identity: GitsRoadLinkIdentity

    def __post_init__(self) -> None:
        if not self.route_id.strip() or not self.direction.strip():
            raise ValueError("GITS road-link route and direction must be non-blank")


class InMemoryGitsRoadLinkIdentityRepository:
    """Bounded fixture/reference implementation of the production identity port."""

    def __init__(
        self,
        records: tuple[GitsRoadLinkIdentityRecord, ...],
    ) -> None:
        if len(records) > MAX_REFERENCE_RECORDS:
            raise ValueError(
                f"GITS identity reference is bounded to {MAX_REFERENCE_RECORDS} records"
            )
        indexed: dict[tuple[str, str], GitsRoadLinkIdentity] = {}
        for record in records:
            key = (record.route_id, record.direction)
            if key in indexed:
                raise ValueError("GITS identity route/direction is ambiguous")
            indexed[key] = record.identity
        self._records = indexed

    def find_for_targets(
        self,
        targets: tuple[tuple[str, str], ...],
        *,
        as_of: datetime,
    ) -> Mapping[tuple[str, str], GitsRoadLinkIdentity]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if len(targets) > MAX_CANDIDATES or len(set(targets)) != len(targets):
            raise ValueError("GITS identity target lookup is invalid or unbounded")
        if any(not route_id.strip() or not direction.strip() for route_id, direction in targets):
            raise ValueError("GITS identity target values must be non-blank")
        requested = frozenset(targets)
        return {
            key: identity
            for key, identity in sorted(self._records.items())
            if key in requested and identity.validity.contains(as_of)
        }


def _sample(points: tuple[Coordinate, ...]) -> tuple[Coordinate, ...]:
    if len(points) <= MAX_GEOMETRY_SAMPLE_POINTS:
        return points
    last = len(points) - 1
    indices = {
        round(index * last / (MAX_GEOMETRY_SAMPLE_POINTS - 1))
        for index in range(MAX_GEOMETRY_SAMPLE_POINTS)
    }
    return tuple(points[index] for index in sorted(indices))


def _directed_geometry_distance(
    left: tuple[Coordinate, ...],
    right: tuple[Coordinate, ...],
) -> float:
    return sum(min(distance_meters(point, other) for other in right) for point in left) / len(left)


def geometry_similarity(
    left: tuple[Coordinate, ...],
    right: tuple[Coordinate, ...],
) -> float | None:
    if not left or not right:
        return None
    sampled_left = _sample(left)
    sampled_right = _sample(right)
    mean_distance = (
        _directed_geometry_distance(sampled_left, sampled_right)
        + _directed_geometry_distance(sampled_right, sampled_left)
    ) / 2
    return round(max(0.0, 1 - min(mean_distance / 1_000, 1.0)), 6)


def _stop_distance(
    source: Coordinate | None,
    target: Coordinate | None,
) -> float | None:
    if source is None or target is None:
        return None
    return distance_meters(source, target)


def _terminal_score(source: ProviderMappingInput, target: CanonicalRouteCandidate) -> float:
    values = (
        name_similarity(source.origin_terminal, target.origin_terminal, kind="stop"),
        name_similarity(
            source.destination_terminal,
            target.destination_terminal,
            kind="stop",
        ),
    )
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else 0.0


class InMemoryGbisCatalogRepository:
    """Bounded deterministic reference for fixtures and repository contract tests."""

    def __init__(self, records: tuple[CanonicalRouteCandidate, ...]) -> None:
        if len(records) > MAX_REFERENCE_RECORDS:
            raise ValueError(
                f"reference catalog is bounded to {MAX_REFERENCE_RECORDS} records"
            )
        self._records = records

    def find_candidates(
        self,
        query: CatalogQuery,
    ) -> tuple[CanonicalRouteCandidate, ...]:
        ranked: list[tuple[tuple[float, ...], CanonicalRouteCandidate]] = []
        for record in self._records:
            if not record.validity.contains(query.as_of):
                continue
            route_name = name_similarity(
                query.source.route_name,
                record.route_name,
                kind="route",
            )
            if route_name is not None and route_name < query.min_route_name_similarity:
                continue
            boarding_distance = _stop_distance(
                query.source.boarding.coordinate,
                record.boarding.coordinate,
            )
            alighting_distance = _stop_distance(
                query.source.alighting.coordinate,
                record.alighting.coordinate,
            )
            if boarding_distance is not None and boarding_distance > query.stop_radius_meters:
                continue
            if alighting_distance is not None and alighting_distance > query.stop_radius_meters:
                continue

            geometry = geometry_similarity(query.source.geometry, record.geometry)
            candidate = replace(record, geometry_similarity_to_provider=geometry)
            type_match = (
                1.0
                if normalize_type(query.source.route_type) is not None
                and normalize_type(query.source.route_type) == normalize_type(record.route_type)
                else 0.0
            )
            boarding_name = name_similarity(
                query.source.boarding.name,
                record.boarding.name,
                kind="stop",
            ) or 0.0
            alighting_name = name_similarity(
                query.source.alighting.name,
                record.alighting.name,
                kind="stop",
            ) or 0.0
            proximity = sum(
                max(0.0, 1 - distance / query.stop_radius_meters)
                for distance in (boarding_distance, alighting_distance)
                if distance is not None
            )
            priority = (
                route_name or 0.0,
                type_match,
                boarding_name + alighting_name,
                proximity,
                _terminal_score(query.source, record),
                geometry or 0.0,
            )
            ranked.append((priority, candidate))

        ranked.sort(key=lambda item: item[1].route_id)
        ranked.sort(key=lambda item: item[0], reverse=True)
        return tuple(candidate for _, candidate in ranked[: query.max_candidates])
