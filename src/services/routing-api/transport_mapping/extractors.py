"""Provider-specific extraction from provider-core canonical BUS legs.

This module deliberately uses structural protocols instead of importing adapter
implementations.  The input has already crossed the provider-core normalization
boundary; dictionaries, provider field names and raw payloads are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .models import Coordinate, ProviderMappingInput, StopSignal


class CanonicalIdentityExtractionError(ValueError):
    pass


class TransitProvider(StrEnum):
    KAKAO = "KAKAO_TRANSIT"
    TMAP = "TMAP_TRANSIT"
    ODSAY = "ODSAY_TRANSIT"


class CoordinateLike(Protocol):
    lon: float
    lat: float


class StopLike(Protocol):
    name: str
    coordinate: CoordinateLike
    external_id: str | None
    sequence: int | None


class TransitDescriptorLike(Protocol):
    route_label: str | None
    external_route_id: str | None
    route_type: str | None
    direction: str | None
    branch_id: str | None
    boarding_sequence: int | None
    alighting_sequence: int | None
    terminal_names: tuple[str, ...]
    live_vehicle_observed: bool | None


class CanonicalBusLegLike(Protocol):
    mode: object
    from_stop: StopLike
    to_stop: StopLike
    transit: TransitDescriptorLike | None
    geometry: tuple[CoordinateLike, ...]


_PROVIDER_ALIASES = {
    "KAKAO": TransitProvider.KAKAO,
    "KAKAO_TRANSIT": TransitProvider.KAKAO,
    "KAKAO_MAPS_TRANSIT": TransitProvider.KAKAO,
    "TMAP": TransitProvider.TMAP,
    "TMAP_TRANSIT": TransitProvider.TMAP,
    "ODSAY": TransitProvider.ODSAY,
    "ODSAY_TRANSIT": TransitProvider.ODSAY,
}


def _mode_value(mode: object) -> str:
    value = getattr(mode, "value", mode)
    return str(value).strip().upper()


def _sequence(
    descriptor_value: int | None,
    stop_value: int | None,
    field_name: str,
) -> int | None:
    if (
        descriptor_value is not None
        and stop_value is not None
        and descriptor_value != stop_value
    ):
        raise CanonicalIdentityExtractionError(
            f"conflicting canonical {field_name} values"
        )
    return descriptor_value if descriptor_value is not None else stop_value


def _stop(value: StopLike, sequence: int | None) -> StopSignal:
    return StopSignal(
        name=value.name,
        coordinate=Coordinate(
            lon=float(value.coordinate.lon),
            lat=float(value.coordinate.lat),
        ),
        external_id=value.external_id,
        sequence=sequence,
    )


@dataclass(frozen=True, slots=True)
class CanonicalLegIdentityExtractor:
    """Provider policy boundary after raw adapter normalization."""

    provider: TransitProvider

    def extract(self, leg: CanonicalBusLegLike) -> ProviderMappingInput:
        if _mode_value(leg.mode) != "BUS":
            raise CanonicalIdentityExtractionError("only canonical BUS legs can be mapped")
        descriptor = leg.transit
        if descriptor is None:
            raise CanonicalIdentityExtractionError("canonical BUS leg has no transit descriptor")

        boarding_sequence = _sequence(
            descriptor.boarding_sequence,
            leg.from_stop.sequence,
            "boarding sequence",
        )
        alighting_sequence = _sequence(
            descriptor.alighting_sequence,
            leg.to_stop.sequence,
            "alighting sequence",
        )
        if (
            boarding_sequence is not None
            and alighting_sequence is not None
            and alighting_sequence <= boarding_sequence
        ):
            raise CanonicalIdentityExtractionError(
                "canonical alighting sequence must follow boarding sequence"
            )

        # A single terminal name has no safe orientation.  Do not guess which
        # endpoint it identifies.
        terminals = descriptor.terminal_names
        origin_terminal = terminals[0] if len(terminals) >= 2 else None
        destination_terminal = terminals[-1] if len(terminals) >= 2 else None
        geometry = tuple(
            Coordinate(lon=float(point.lon), lat=float(point.lat))
            for point in leg.geometry
        )
        return ProviderMappingInput(
            provider=self.provider.value,
            external_route_id=descriptor.external_route_id,
            route_name=descriptor.route_label,
            route_type=descriptor.route_type,
            boarding=_stop(leg.from_stop, boarding_sequence),
            alighting=_stop(leg.to_stop, alighting_sequence),
            direction=descriptor.direction,
            branch_id=descriptor.branch_id,
            origin_terminal=origin_terminal,
            destination_terminal=destination_terminal,
            geometry=geometry,
        )


_EXTRACTORS = {
    provider: CanonicalLegIdentityExtractor(provider)
    for provider in TransitProvider
}


def provider_from_code(provider_code: str) -> TransitProvider:
    normalized = provider_code.strip().upper().replace("-", "_").replace(" ", "_")
    try:
        return _PROVIDER_ALIASES[normalized]
    except KeyError as exc:
        raise CanonicalIdentityExtractionError(
            f"unsupported canonical transit provider: {provider_code!r}"
        ) from exc


def extract_provider_identity(
    provider_code: str,
    leg: CanonicalBusLegLike,
) -> ProviderMappingInput:
    provider = provider_from_code(provider_code)
    return _EXTRACTORS[provider].extract(leg)
