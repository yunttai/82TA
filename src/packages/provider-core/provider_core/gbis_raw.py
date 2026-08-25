"""Normalize the two reviewed GBIS v2 response shapes.

Only fields needed by the canonical bus observations cross this boundary. Vehicle
plates and provider crowding codes are deliberately ignored.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Mapping

from .canonical import Coordinate, require_aware
from .context import (
    BusArrivalObservation,
    BusLocationObservation,
    OpaqueVehicleTokenIssuer,
)
from .validation import SchemaValidationError


GBIS_ARRIVALS_SCHEMA_VERSION = "gbis.bus-arrival.rest.v2.2026-08-25"
GBIS_LOCATIONS_SCHEMA_VERSION = "gbis.bus-location.rest.v2.2026-08-25"

_SUCCESS_CODES = {"0", "00"}
_NO_RESULT_CODE = "4"
_NO_RESULT_MESSAGE = "결과가 존재하지 않습니다"
_MAX_ITEMS = 256


def parse_gbis_arrivals(
    body: Any,
    *,
    observed_at: datetime,
    token_issuer: OpaqueVehicleTokenIssuer,
) -> tuple[BusArrivalObservation, ...]:
    """Normalize slot 1 and slot 2 from an official arrival-list response."""

    _validate_inputs(observed_at, token_issuer)
    result: list[BusArrivalObservation] = []
    for item in _response_items(body, "busArrivalList"):
        route_id = _identifier(item.get("routeId"), "routeId")
        station_id = _identifier(item.get("stationId"), "stationId")
        for slot in (1, 2):
            eta_seconds = _arrival_eta_seconds(item, slot)
            if eta_seconds is None:
                continue
            vehicle_id = _optional_identifier(item.get(f"vehId{slot}"), f"vehId{slot}")
            result.append(BusArrivalObservation(
                route_external_id=route_id,
                station_external_id=station_id,
                eta_seconds=eta_seconds,
                remaining_seats=_remaining_seats(
                    item.get(f"remainSeatCnt{slot}"), f"remainSeatCnt{slot}"
                ),
                observed_at=observed_at,
                vehicle_token=(
                    token_issuer.issue("GBIS_V2", vehicle_id)
                    if vehicle_id is not None
                    else None
                ),
            ))
    return tuple(result)


def parse_gbis_locations(
    body: Any,
    *,
    observed_at: datetime,
    token_issuer: OpaqueVehicleTokenIssuer,
) -> tuple[BusLocationObservation, ...]:
    """Normalize an official location-list response without retaining raw IDs."""

    _validate_inputs(observed_at, token_issuer)
    result: list[BusLocationObservation] = []
    for item in _response_items(body, "busLocationList"):
        vehicle_id = _identifier(item.get("vehId"), "vehId")
        result.append(BusLocationObservation(
            route_external_id=_identifier(item.get("routeId"), "routeId"),
            vehicle_token=token_issuer.issue("GBIS_V2", vehicle_id),
            stop_sequence=_integer(item.get("stationSeq"), "stationSeq", minimum=0),
            coordinate=Coordinate(
                lon=_number(item.get("x"), "x"),
                lat=_number(item.get("y"), "y"),
            ),
            observed_at=observed_at,
        ))
    return tuple(result)


def _validate_inputs(
    observed_at: datetime, token_issuer: OpaqueVehicleTokenIssuer
) -> None:
    try:
        require_aware(observed_at, "GBIS observed_at")
    except (AttributeError, TypeError, ValueError):
        raise SchemaValidationError("GBIS observed timestamp is invalid") from None
    if not isinstance(token_issuer, OpaqueVehicleTokenIssuer):
        raise SchemaValidationError("GBIS vehicle token issuer is required")


def _response_items(body: Any, item_name: str) -> tuple[Mapping[str, Any], ...]:
    root = _mapping(body, "GBIS body")
    response = _mapping(root.get("response"), "GBIS response")
    header = _mapping(response.get("msgHeader"), "GBIS msgHeader")
    result_code = str(header.get("resultCode", "")).strip()
    if result_code not in _SUCCESS_CODES:
        message = header.get("resultMessage") or header.get("resultMsg")
        if (
            result_code == _NO_RESULT_CODE
            and isinstance(message, str)
            and _NO_RESULT_MESSAGE in message
        ):
            return ()
        # Provider messages can contain request details. Do not echo them.
        raise SchemaValidationError("GBIS request was not successful")

    raw_body = response.get("msgBody")
    if raw_body is None or raw_body == "":
        return ()
    message_body = _mapping(raw_body, "GBIS msgBody")
    raw_items = message_body.get(item_name)
    if raw_items is None or raw_items == "":
        return ()
    if isinstance(raw_items, Mapping):
        items = (raw_items,)
    elif isinstance(raw_items, list):
        if len(raw_items) > _MAX_ITEMS:
            raise SchemaValidationError("GBIS response item count exceeds the bound")
        items = tuple(raw_items)
    else:
        raise SchemaValidationError("GBIS response items have an invalid shape")
    if len(items) > _MAX_ITEMS or any(not isinstance(item, Mapping) for item in items):
        raise SchemaValidationError("GBIS response items have an invalid shape")
    return items


def _arrival_eta_seconds(item: Mapping[str, Any], slot: int) -> int | None:
    seconds = item.get(f"predictTimeSec{slot}")
    if not _blank(seconds):
        return _integer(seconds, f"predictTimeSec{slot}", minimum=0)
    minutes = item.get(f"predictTime{slot}")
    if _blank(minutes):
        return None
    return _integer(minutes, f"predictTime{slot}", minimum=0) * 60


def _remaining_seats(raw: Any, name: str) -> int | None:
    if _blank(raw):
        return None
    value = _integer(raw, name, minimum=-1)
    return None if value == -1 else value


def _identifier(raw: Any, name: str) -> str:
    value = _optional_identifier(raw, name)
    if value is None:
        raise SchemaValidationError(f"GBIS {name} is required")
    return value


def _optional_identifier(raw: Any, name: str) -> str | None:
    if _blank(raw):
        return None
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise SchemaValidationError(f"GBIS {name} is invalid")
    value = str(raw).strip()
    if len(value) > 128 or any(ord(character) < 32 for character in value):
        raise SchemaValidationError(f"GBIS {name} is invalid")
    return value


def _integer(raw: Any, name: str, *, minimum: int) -> int:
    if isinstance(raw, bool):
        raise SchemaValidationError(f"GBIS {name} is invalid")
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            value = int(raw.strip(), 10)
        except ValueError:
            raise SchemaValidationError(f"GBIS {name} is invalid") from None
    else:
        raise SchemaValidationError(f"GBIS {name} is invalid")
    if value < minimum or value > 2_147_483_647:
        raise SchemaValidationError(f"GBIS {name} is outside the supported range")
    return value


def _number(raw: Any, name: str) -> float:
    if isinstance(raw, bool):
        raise SchemaValidationError(f"GBIS {name} is invalid")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise SchemaValidationError(f"GBIS {name} is invalid") from None
    if not math.isfinite(value):
        raise SchemaValidationError(f"GBIS {name} is invalid")
    return value


def _mapping(raw: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise SchemaValidationError(f"{name} must be an object")
    return raw


def _blank(raw: Any) -> bool:
    return raw is None or (isinstance(raw, str) and not raw.strip())


__all__ = [
    "GBIS_ARRIVALS_SCHEMA_VERSION",
    "GBIS_LOCATIONS_SCHEMA_VERSION",
    "parse_gbis_arrivals",
    "parse_gbis_locations",
]
