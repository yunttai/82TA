"""Sanitized, deterministic transit fixture adapter.

This adapter is intentionally incapable of network access. Fixture names are an
enum and resolve under the packaged fixture directory, so callers cannot inject a
path or URL.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from ..canonical import (
    CanonicalItinerary,
    CanonicalLeg,
    CanonicalStop,
    Coordinate,
    DataOrigin,
    MoneyRange,
    TimeEstimate,
    TransitDescriptor,
    TravelMode,
)
from ..envelope import Freshness, ProviderEnvelope, ProviderStatus, QualityFlag, classify_freshness
from ..requests import TransitSearchRequest
from ..resilience import Deadline
from ..validation import (
    ObjectSchema,
    SchemaValidationError,
    is_aware_iso8601,
    is_list,
    is_non_negative_int,
    is_number,
    is_optional_string,
    is_string,
)


class FixtureScenario(StrEnum):
    SUCCESS = "success"
    R1_SUCCESS = "r1_success"
    R2_SUCCESS = "r2_success"
    R3_SUCCESS = "r3_success"
    R4_SUCCESS = "r4_success"
    EMPTY = "empty"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    SCHEMA_DRIFT = "schema_drift"


_FIXTURE_FILES = {
    FixtureScenario.SUCCESS: "transit_success.json",
    FixtureScenario.R1_SUCCESS: "transit_r1_success.json",
    FixtureScenario.R2_SUCCESS: "transit_r2_success.json",
    FixtureScenario.R3_SUCCESS: "transit_r3_success.json",
    FixtureScenario.R4_SUCCESS: "transit_r4_success.json",
    FixtureScenario.EMPTY: "transit_empty.json",
    FixtureScenario.TIMEOUT: "transit_timeout.json",
    FixtureScenario.RATE_LIMITED: "transit_429.json",
    FixtureScenario.SCHEMA_DRIFT: "transit_schema_drift.json",
}

_ROOT_SCHEMA = ObjectSchema(
    required={
        "fixtureVersion": is_string,
        "scenario": is_string,
        "provider": is_string,
        "operation": is_string,
        "fetchedAt": is_aware_iso8601,
        "receivedAt": is_aware_iso8601,
        "observedAt": lambda value: value is None or is_aware_iso8601(value),
        "schemaVersion": is_optional_string,
        "status": is_string,
        "results": is_list,
    }
)
_ITINERARY_SCHEMA = ObjectSchema(required={"id": is_string, "legs": is_list})
_STOP_SCHEMA = ObjectSchema(
    required={"name": is_string, "lon": is_number, "lat": is_number},
    optional={"externalId": is_optional_string, "sequence": lambda value: value is None or is_non_negative_int(value)},
)
_LEG_SCHEMA = ObjectSchema(
    required={
        "id": is_string,
        "sequence": is_non_negative_int,
        "mode": is_string,
        "from": lambda value: isinstance(value, dict),
        "to": lambda value: isinstance(value, dict),
        "p50Seconds": is_non_negative_int,
        "p90Seconds": is_non_negative_int,
        "distanceMeters": is_non_negative_int,
        "fareExpectedKrw": is_non_negative_int,
        "fareLowerKrw": is_non_negative_int,
        "fareUpperKrw": is_non_negative_int,
        "geometry": is_list,
    },
    optional={
        "expectedStartAt": lambda value: value is None or is_aware_iso8601(value),
        "expectedEndAt": lambda value: value is None or is_aware_iso8601(value),
        "transit": lambda value: value is None or isinstance(value, dict),
    },
)
_TRANSIT_SCHEMA = ObjectSchema(
    required={},
    optional={
        "routeLabel": is_optional_string,
        "externalRouteId": is_optional_string,
        "routeType": is_optional_string,
        "direction": is_optional_string,
        "branchId": is_optional_string,
        "boardingSequence": lambda value: value is None or is_non_negative_int(value),
        "alightingSequence": lambda value: value is None or is_non_negative_int(value),
        "terminalNames": lambda value: isinstance(value, list) and all(is_string(item) for item in value),
        "liveVehicleObserved": lambda value: value is None or isinstance(value, bool),
    },
)
_COORD_SCHEMA = ObjectSchema(required={"lon": is_number, "lat": is_number})


def _parse_time(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


class FixtureTransitAdapter:
    provider = "SANITIZED_TRANSIT_FIXTURE"
    operation = "search"

    def __init__(self, scenario: FixtureScenario) -> None:
        self._fixture_dir = Path(__file__).resolve().parents[1] / "fixtures"
        self._scenario = scenario

    def search(
        self,
        request: TransitSearchRequest,
        *,
        deadline: Deadline,
    ) -> ProviderEnvelope[tuple[CanonicalItinerary, ...]]:
        deadline.require()
        scenario = self._scenario
        raw_bytes = self._read_fixture(scenario)
        fingerprint = request.fingerprint()
        try:
            document = json.loads(raw_bytes)
            root = _ROOT_SCHEMA.validate(document)
            if root["provider"] != self.provider or root["operation"] != self.operation:
                raise SchemaValidationError("fixture provider or operation does not match adapter")
            if root["scenario"] != scenario.value:
                raise SchemaValidationError("fixture scenario does not match requested scenario")
            status = ProviderStatus(root["status"])
            fetched_at = _parse_time(root["fetchedAt"])
            received_at = _parse_time(root["receivedAt"])
            observed_at = _parse_time(root["observedAt"])
            assert fetched_at is not None and received_at is not None
            if status is not ProviderStatus.OK:
                return ProviderEnvelope(
                    provider=self.provider,
                    operation=self.operation,
                    fingerprint=fingerprint,
                    fetched_at=fetched_at,
                    received_at=received_at,
                    observed_at=observed_at,
                    status=status,
                    schema_version=root["schemaVersion"],
                    freshness=Freshness.UNKNOWN,
                    normalized_count=0,
                    quality_flags=(QualityFlag.SANITIZED_FIXTURE,),
                    payload=None,
                    message_code=self._message_code(status),
                )
            itineraries = tuple(self._normalize_itinerary(item) for item in root["results"])
            flags = [QualityFlag.SCHEMA_VALIDATED, QualityFlag.SANITIZED_FIXTURE]
            if not itineraries:
                flags.append(QualityFlag.EMPTY_RESULT)
            if observed_at is None:
                flags.append(QualityFlag.OBSERVED_AT_MISSING)
            return ProviderEnvelope(
                provider=self.provider,
                operation=self.operation,
                fingerprint=fingerprint,
                fetched_at=fetched_at,
                received_at=received_at,
                observed_at=observed_at,
                status=status,
                schema_version=root["schemaVersion"],
                freshness=classify_freshness(
                    received_at=received_at,
                    observed_at=observed_at,
                    maximum_age_seconds=120,
                ),
                normalized_count=len(itineraries),
                quality_flags=tuple(flags),
                payload=itineraries,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, SchemaValidationError):
            timestamp = datetime.fromisoformat("2026-08-23T00:00:00+09:00")
            return ProviderEnvelope(
                provider=self.provider,
                operation=self.operation,
                fingerprint=fingerprint,
                fetched_at=timestamp,
                received_at=timestamp,
                observed_at=None,
                status=ProviderStatus.BAD_RESPONSE,
                schema_version=None,
                freshness=Freshness.UNKNOWN,
                normalized_count=0,
                quality_flags=(QualityFlag.SCHEMA_DRIFT, QualityFlag.SANITIZED_FIXTURE),
                payload=None,
                message_code="PROVIDER_BAD_RESPONSE",
            )

    def _read_fixture(self, scenario: FixtureScenario) -> bytes:
        path = self._fixture_dir / _FIXTURE_FILES[scenario]
        data = path.read_bytes()
        if len(data) > 64 * 1024:
            raise ValueError("fixture exceeds the response-size limit")
        return data

    @staticmethod
    def _message_code(status: ProviderStatus) -> str | None:
        return {
            ProviderStatus.RATE_LIMITED: "RATE_LIMITED",
            ProviderStatus.UNAVAILABLE: "TRANSIT_PROVIDER_UNAVAILABLE",
            ProviderStatus.BAD_RESPONSE: "PROVIDER_BAD_RESPONSE",
            ProviderStatus.DISABLED: "TRANSIT_PROVIDER_UNAVAILABLE",
        }.get(status)

    def _normalize_itinerary(self, value: Any) -> CanonicalItinerary:
        item = _ITINERARY_SCHEMA.validate(value, path="$.results[]")
        legs = tuple(self._normalize_leg(leg) for leg in item["legs"])
        return CanonicalItinerary(itinerary_id=item["id"], legs=legs)

    def _normalize_stop(self, value: Any, path: str) -> CanonicalStop:
        stop = _STOP_SCHEMA.validate(value, path=path)
        return CanonicalStop(
            name=stop["name"],
            external_id=stop.get("externalId"),
            coordinate=Coordinate(lon=float(stop["lon"]), lat=float(stop["lat"])),
            sequence=stop.get("sequence"),
        )

    def _normalize_leg(self, value: Any) -> CanonicalLeg:
        leg = _LEG_SCHEMA.validate(value, path="$.results[].legs[]")
        mode = TravelMode(leg["mode"])
        transit = None
        if leg.get("transit") is not None:
            raw = _TRANSIT_SCHEMA.validate(leg["transit"], path="$.results[].legs[].transit")
            transit = TransitDescriptor(
                route_label=raw.get("routeLabel"),
                external_route_id=raw.get("externalRouteId"),
                route_type=raw.get("routeType"),
                direction=raw.get("direction"),
                branch_id=raw.get("branchId"),
                boarding_sequence=raw.get("boardingSequence"),
                alighting_sequence=raw.get("alightingSequence"),
                terminal_names=tuple(raw.get("terminalNames", ())),
                live_vehicle_observed=raw.get("liveVehicleObserved"),
            )
        geometry = tuple(
            Coordinate(lon=float(_COORD_SCHEMA.validate(point, path="$.geometry[].lon")["lon"]), lat=float(point["lat"]))
            for point in leg["geometry"]
        )
        return CanonicalLeg(
            leg_id=leg["id"],
            sequence=leg["sequence"],
            mode=mode,
            from_stop=self._normalize_stop(leg["from"], "$.leg.from"),
            to_stop=self._normalize_stop(leg["to"], "$.leg.to"),
            duration=TimeEstimate(leg["p50Seconds"], leg["p90Seconds"], DataOrigin.PROVIDER_ESTIMATE),
            distance_meters=leg["distanceMeters"],
            fare=MoneyRange(
                expected_krw=leg["fareExpectedKrw"],
                lower_krw=leg["fareLowerKrw"],
                upper_krw=leg["fareUpperKrw"],
                origin=DataOrigin.PROVIDER_ESTIMATE,
            ),
            expected_start_at=_parse_time(leg.get("expectedStartAt")),
            expected_end_at=_parse_time(leg.get("expectedEndAt")),
            transit=transit,
            geometry=geometry,
        )
