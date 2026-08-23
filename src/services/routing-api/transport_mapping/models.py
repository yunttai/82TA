"""Provider-neutral inputs and immutable mapping outputs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from math import isfinite
from uuid import UUID


def _aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _optional_non_blank(value: str | None, field_name: str) -> None:
    if value is not None and not value.strip():
        raise ValueError(f"{field_name} must be non-blank when supplied")


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

GITS_ROAD_LINK_IDENTITY_VERSION = "gits-road-link-identity.v1"
MAX_GITS_ROAD_LINK_IDS = 512
MAX_GITS_ROAD_LINK_ID_LENGTH = 128


def _validate_gits_road_link_external_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_GITS_ROAD_LINK_ID_LENGTH
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("GITS road-link identifier is invalid")
    return value


def gits_road_link_normalized_identity(link_external_id: str) -> dict[str, str]:
    """Return the exact two-key provider-entity identity schema."""

    external_id = _validate_gits_road_link_external_id(link_external_id)
    return {
        "identityVersion": GITS_ROAD_LINK_IDENTITY_VERSION,
        "linkExternalId": external_id,
    }


def gits_road_link_identity_fingerprint(link_external_id: str) -> str:
    """SHA-256 binding for the exact normalized GITS provider identity."""

    encoded = json.dumps(
        gits_road_link_normalized_identity(link_external_id),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class Coordinate:
    """WGS84 coordinate used only as identity evidence."""

    lon: float
    lat: float

    def __post_init__(self) -> None:
        if not isfinite(self.lon) or not 124 <= self.lon <= 132:
            raise ValueError("lon must be a finite WGS84 longitude in Korea")
        if not isfinite(self.lat) or not 33 <= self.lat <= 39.5:
            raise ValueError("lat must be a finite WGS84 latitude in Korea")


@dataclass(frozen=True, slots=True)
class StopSignal:
    """A stop identity as exposed by a canonical provider or master catalog."""

    name: str | None = None
    coordinate: Coordinate | None = None
    external_id: str | None = None
    sequence: int | None = None

    def __post_init__(self) -> None:
        _optional_non_blank(self.name, "stop name")
        _optional_non_blank(self.external_id, "stop external_id")
        if self.sequence is not None and self.sequence < 0:
            raise ValueError("stop sequence must be non-negative")


@dataclass(frozen=True, slots=True)
class ProviderMappingInput:
    """Canonical BUS-leg identity; never a raw provider response."""

    provider: str
    external_route_id: str | None
    route_name: str | None
    route_type: str | None
    boarding: StopSignal
    alighting: StopSignal
    direction: str | None = None
    branch_id: str | None = None
    origin_terminal: str | None = None
    destination_terminal: str | None = None
    turning_point_sequence: int | None = None
    geometry: tuple[Coordinate, ...] = ()

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider must be non-blank")
        for name in (
            "external_route_id",
            "route_name",
            "route_type",
            "direction",
            "branch_id",
            "origin_terminal",
            "destination_terminal",
        ):
            _optional_non_blank(getattr(self, name), name)
        if self.turning_point_sequence is not None and self.turning_point_sequence < 0:
            raise ValueError("turning_point_sequence must be non-negative")


@dataclass(frozen=True, slots=True)
class ValidityWindow:
    valid_from: datetime
    valid_to: datetime | None = None

    def __post_init__(self) -> None:
        _aware(self.valid_from, "valid_from")
        if self.valid_to is not None:
            _aware(self.valid_to, "valid_to")
            if self.valid_to <= self.valid_from:
                raise ValueError("valid_to must be later than valid_from")

    def contains(self, instant: datetime) -> bool:
        _aware(instant, "instant")
        return self.valid_from <= instant and (
            self.valid_to is None or instant < self.valid_to
        )


@dataclass(frozen=True, slots=True)
class GitsRoadLinkIdentity:
    """Accepted GITS road-link identities for one canonical route direction.

    The identifiers are opaque Provider values.  They may be used only as an
    allow-list for a bounded GITS traffic query; geometry and caller input are
    deliberately not part of this identity.
    """

    link_external_ids: tuple[str, ...]
    mapping_version: str
    validity: ValidityWindow
    identity_version: str = GITS_ROAD_LINK_IDENTITY_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.identity_version, str)
            or self.identity_version != GITS_ROAD_LINK_IDENTITY_VERSION
        ):
            raise ValueError("GITS road-link identity version is unsupported")
        if (
            not isinstance(self.mapping_version, str)
            or not self.mapping_version.strip()
            or len(self.mapping_version) > 128
        ):
            raise ValueError("GITS road-link mapping version is invalid")
        values = self.link_external_ids
        if not 1 <= len(values) <= MAX_GITS_ROAD_LINK_IDS:
            raise ValueError("GITS road-link identity count is outside the bound")
        for value in values:
            _validate_gits_road_link_external_id(value)
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError(
                "GITS road-link identifiers must be unique and deterministically ordered"
            )


@dataclass(frozen=True, slots=True)
class CanonicalRouteCandidate:
    """A route/stop/direction candidate projected from the GBIS master."""

    route_id: str
    route_name: str | None
    route_type: str | None
    boarding: StopSignal
    alighting: StopSignal
    direction: str | None
    branch_id: str | None
    origin_terminal: str | None
    destination_terminal: str | None
    validity: ValidityWindow
    geometry_similarity_to_provider: float | None = None
    live_vehicle_exists: bool | None = None
    turning_point_sequence: int | None = None
    geometry: tuple[Coordinate, ...] = ()
    gits_road_link_identity: GitsRoadLinkIdentity | None = None

    def __post_init__(self) -> None:
        if not self.route_id.strip():
            raise ValueError("route_id must be non-blank")
        for name in (
            "route_name",
            "route_type",
            "direction",
            "branch_id",
            "origin_terminal",
            "destination_terminal",
        ):
            _optional_non_blank(getattr(self, name), name)
        value = self.geometry_similarity_to_provider
        if value is not None and (not isfinite(value) or not 0 <= value <= 1):
            raise ValueError("geometry similarity must be between 0 and 1")
        if self.turning_point_sequence is not None and self.turning_point_sequence < 0:
            raise ValueError("turning_point_sequence must be non-negative")
        identity = self.gits_road_link_identity
        if identity is not None:
            candidate_end = self.validity.valid_to
            identity_end = identity.validity.valid_to
            if (
                candidate_end is not None
                and candidate_end <= identity.validity.valid_from
            ) or (
                identity_end is not None
                and identity_end <= self.validity.valid_from
            ):
                raise ValueError(
                    "GITS road-link identity validity must overlap route validity"
                )

    @property
    def traffic_link_external_ids(self) -> tuple[str, ...]:
        """Compatibility view consumed by the optional traffic-context fan-in."""

        identity = self.gits_road_link_identity
        return () if identity is None else identity.link_external_ids


class MappingGrade(StrEnum):
    """Internal mapping policy grade aligned with contract string values."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ReviewDisposition(StrEnum):
    AUTO_ACCEPT = "AUTO_ACCEPT"
    QUEUE = "QUEUE"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class SignalEvidence:
    name: str
    weight: float
    available: bool
    similarity: float | None
    contribution: float


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    signals: tuple[SignalEvidence, ...]
    available_weight: float
    weighted_similarity: float

    def signal(self, name: str) -> SignalEvidence:
        for evidence in self.signals:
            if evidence.name == name:
                return evidence
        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    disposition: ReviewDisposition
    reasons: tuple[str, ...] = ()

    @property
    def should_queue(self) -> bool:
        return self.disposition is ReviewDisposition.QUEUE


@dataclass(frozen=True, slots=True)
class MappingResult:
    provider_fingerprint: str
    candidate_fingerprint: str
    route_id: str
    score: float
    grade: MappingGrade
    breakdown: ScoreBreakdown
    mapping_version: str
    validity: ValidityWindow
    evaluated_at: datetime
    blockers: tuple[str, ...]
    review: ReviewDecision
    allows_bus_intelligence: bool = field(init=False)

    def __post_init__(self) -> None:
        if not self.mapping_version.strip():
            raise ValueError("mapping_version must be non-blank")
        _aware(self.evaluated_at, "evaluated_at")
        if not 0 <= self.score <= 1:
            raise ValueError("score must be between 0 and 1")
        # This is deliberately derived rather than caller-controlled.  There is
        # no path that allows MEDIUM/LOW enrichment.
        object.__setattr__(
            self,
            "allows_bus_intelligence",
            self.grade is MappingGrade.HIGH and not self.blockers,
        )


@dataclass(frozen=True, slots=True)
class PersistedMappingResolution:
    """Durable identity returned only after an accepted HIGH mapping commits.

    ``MappingResult`` remains a pure scoring result and deliberately carries no
    database identity. This separate type prevents fixture/local scoring from
    manufacturing an ``entity_mapping.id`` while giving downstream persistence
    a typed, validated reference.
    """

    entity_mapping_id: str
    provider_fingerprint: str
    candidate_fingerprint: str
    route_id: str
    mapping_version: str
    validity: ValidityWindow
    accepted_at: datetime
    grade: MappingGrade = field(init=False, default=MappingGrade.HIGH)
    review_disposition: ReviewDisposition = field(
        init=False,
        default=ReviewDisposition.AUTO_ACCEPT,
    )

    def __post_init__(self) -> None:
        try:
            parsed = UUID(self.entity_mapping_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("entity_mapping_id must be a UUID") from exc
        if str(parsed) != self.entity_mapping_id:
            raise ValueError("entity_mapping_id must use canonical UUID text")
        for value, field_name in (
            (self.provider_fingerprint, "provider_fingerprint"),
            (self.candidate_fingerprint, "candidate_fingerprint"),
        ):
            if _SHA256.fullmatch(value) is None:
                raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
        try:
            route_id = UUID(self.route_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("route_id must be a UUID") from exc
        if str(route_id) != self.route_id:
            raise ValueError("route_id must use canonical UUID text")
        if not self.mapping_version.strip():
            raise ValueError("mapping_version must be non-blank")
        _aware(self.accepted_at, "accepted_at")
        if not self.validity.contains(self.accepted_at):
            raise ValueError("accepted_at must fall inside mapping validity")
