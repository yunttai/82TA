"""Independent provider documentation, key, and production capability states."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Iterable, Mapping


class DocumentationState(StrEnum):
    UNKNOWN = "UNKNOWN"
    DOCUMENTED = "DOCUMENTED"


class KeyVerificationState(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    KEY_VERIFIED = "KEY_VERIFIED"
    FAILED = "FAILED"


class ProductionState(StrEnum):
    UNAPPROVED = "UNAPPROVED"
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class Capability:
    provider: str
    operation: str
    documentation_state: DocumentationState = DocumentationState.UNKNOWN
    key_verification_state: KeyVerificationState = KeyVerificationState.UNVERIFIED
    production_state: ProductionState = ProductionState.UNAPPROVED
    fixture_only: bool = True

    @property
    def enabled(self) -> bool:
        return (
            self.documentation_state is DocumentationState.DOCUMENTED
            and not self.fixture_only
            and self.key_verification_state is KeyVerificationState.KEY_VERIFIED
            and self.production_state is ProductionState.PRODUCTION_APPROVED
        )


class CapabilityRegistry:
    """Immutable registry; missing operations resolve to a disabled default."""

    def __init__(self, capabilities: Iterable[Capability] = ()) -> None:
        entries: dict[tuple[str, str], Capability] = {}
        for capability in capabilities:
            key = (capability.provider, capability.operation)
            if key in entries:
                raise ValueError(f"duplicate provider capability: {key!r}")
            entries[key] = capability
        self._entries: Mapping[tuple[str, str], Capability] = MappingProxyType(entries)

    def get(self, provider: str, operation: str) -> Capability:
        return self._entries.get((provider, operation), Capability(provider=provider, operation=operation))

    def enabled(self, provider: str, operation: str) -> bool:
        return self.get(provider, operation).enabled

    def all(self) -> tuple[Capability, ...]:
        return tuple(self._entries.values())


FOUNDATION_DOCUMENTED_OPERATIONS: tuple[tuple[str, str], ...] = (
    ("KAKAO_PUBLIC_TRANSIT", "search_current"),
    ("KAKAO_WALK", "route"),
    ("KAKAO_DIRECTIONS", "route_current"),
    ("KAKAO_MULTI_DESTINATION", "many_destinations"),
    ("KAKAO_MULTI_ORIGIN", "many_origins"),
    ("KAKAO_FUTURE_DIRECTIONS", "route_future"),
    ("GBIS_V2", "arrivals"),
    ("GBIS_V2", "locations"),
    ("GBIS_V2", "routes"),
    ("GBIS_V2", "stations"),
    ("KMA", "weather_context"),
    ("GITS", "traffic_context"),
    ("TMAP_TRANSIT", "search"),
    ("ODSAY", "search"),
)


def foundation_capability_registry() -> CapabilityRegistry:
    """Canonical documented operations, deliberately disabled for this foundation.

    The shared provider matrix documents these operations, but this repository run
    contains no key probe or commercial approval evidence. Fixture availability does
    not change either state.
    """

    return CapabilityRegistry(
        Capability(
            provider=provider,
            operation=operation,
            documentation_state=DocumentationState.DOCUMENTED,
            key_verification_state=KeyVerificationState.UNVERIFIED,
            production_state=ProductionState.UNAPPROVED,
            fixture_only=True,
        )
        for provider, operation in FOUNDATION_DOCUMENTED_OPERATIONS
    )
