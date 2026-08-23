"""Stable identity and version-aware cache fingerprints."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from .models import CanonicalRouteCandidate, Coordinate, ProviderMappingInput, StopSignal
from .normalization import (
    normalize_branch,
    normalize_direction,
    normalize_route_name,
    normalize_stop_name,
    normalize_type,
)


def _digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _coordinate(value: Coordinate | None) -> list[float] | None:
    if value is None:
        return None
    return [round(value.lon, 6), round(value.lat, 6)]


def _stop(value: StopSignal) -> dict[str, Any]:
    return {
        "name": normalize_stop_name(value.name),
        "coordinate": _coordinate(value.coordinate),
        "external_id": normalize_branch(value.external_id),
        "sequence": value.sequence,
    }


def provider_fingerprint(value: ProviderMappingInput) -> str:
    return _digest(
        {
            "entity_type": "BUS_LEG",
            "provider": normalize_type(value.provider),
            "external_route_id": normalize_branch(value.external_route_id),
            "route_name": normalize_route_name(value.route_name),
            "route_type": normalize_type(value.route_type),
            "boarding": _stop(value.boarding),
            "alighting": _stop(value.alighting),
            "direction": normalize_direction(value.direction),
            "branch_id": normalize_branch(value.branch_id),
            "origin_terminal": normalize_stop_name(value.origin_terminal),
            "destination_terminal": normalize_stop_name(value.destination_terminal),
            "turning_point_sequence": value.turning_point_sequence,
        }
    )


def candidate_fingerprint(value: CanonicalRouteCandidate) -> str:
    # Volatile live-vehicle evidence and mapping-relative geometry similarity
    # are intentionally excluded from the catalog identity.
    return _digest(
        {
            "entity_type": "CANONICAL_BUS_ROUTE_LEG",
            "route_id": value.route_id,
            "route_name": normalize_route_name(value.route_name),
            "route_type": normalize_type(value.route_type),
            "boarding": _stop(value.boarding),
            "alighting": _stop(value.alighting),
            "direction": normalize_direction(value.direction),
            "branch_id": normalize_branch(value.branch_id),
            "origin_terminal": normalize_stop_name(value.origin_terminal),
            "destination_terminal": normalize_stop_name(value.destination_terminal),
            "turning_point_sequence": value.turning_point_sequence,
        }
    )


def _time(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("mapping validity timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def mapping_cache_key(
    provider_identity: str,
    candidate_identity: str,
    mapping_version: str,
    *,
    valid_from: datetime,
    valid_to: datetime | None,
) -> str:
    if not mapping_version.strip():
        raise ValueError("mapping_version must be non-blank")
    return _digest(
        {
            "provider_fingerprint": provider_identity,
            "candidate_fingerprint": candidate_identity,
            "mapping_version": mapping_version,
            "valid_from": _time(valid_from),
            "valid_to": _time(valid_to),
        }
    )
