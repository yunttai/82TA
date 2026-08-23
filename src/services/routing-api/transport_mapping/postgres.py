"""Django-independent PostgreSQL/PostGIS adapters for transport mapping.

All identifiers are closed constants below.  The injected database port owns
driver/connection lifecycle; this module supplies only parameterized statements,
strict row decoding and transaction boundaries.
"""

from __future__ import annotations

import json
import re
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from math import isfinite
from typing import Mapping, Protocol, Sequence
from uuid import UUID, uuid4

from .catalog import (
    MAX_CANDIDATES,
    MAX_GEOMETRY_SAMPLE_POINTS,
    CatalogQuery,
    DisabledGitsRoadLinkIdentityRepository,
    GbisCatalogRepository,
    GitsRoadLinkIdentityRepository,
)
from .models import (
    CanonicalRouteCandidate,
    Coordinate,
    GITS_ROAD_LINK_IDENTITY_VERSION,
    GitsRoadLinkIdentity,
    MAX_GITS_ROAD_LINK_IDS,
    MappingGrade,
    PersistedMappingResolution,
    StopSignal,
    ValidityWindow,
    gits_road_link_identity_fingerprint,
    gits_road_link_normalized_identity,
)
from .normalization import (
    normalize_branch,
    normalize_direction,
    normalize_route_name,
    normalize_stop_name,
    normalize_type,
)
from .pipeline import (
    AcceptedHighMappingEntry,
    AcceptedHighMappingRepository,
    MappingReviewRepository,
    ReviewQueueEntry,
)


MAX_STATEMENT_TIMEOUT_MS = 700
MAX_QUERY_RADIUS_METERS = 1_000
MAX_REVIEW_NOTE_LENGTH = 2_000
MAX_IDENTITY_JSON_BYTES = 32 * 1024
MAX_QUERY_TEXT_LENGTH = 255
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MappingDatabaseError(RuntimeError):
    pass


class MappingDatabaseUnavailable(MappingDatabaseError):
    pass


class MappingRowSchemaError(MappingDatabaseError):
    pass


class MappingQueryBoundsError(MappingDatabaseError):
    pass


class SqlSession(Protocol):
    def fetch_all(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> Sequence[Mapping[str, object]]: ...

    def fetch_one(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> Mapping[str, object] | None: ...

    def execute(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> int: ...


class SqlDatabase(Protocol):
    def transaction(
        self,
        *,
        read_only: bool,
    ) -> AbstractContextManager[SqlSession]: ...


_SET_TIMEOUT_SQL = "SELECT set_config('statement_timeout', %s, true)"

_CATALOG_SQL = r"""
WITH input AS (
    SELECT
        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS boarding_point,
        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS alighting_point,
        %s::timestamptz AS validity_at,
        %s::text AS route_name,
        %s::text AS route_type,
        %s::text AS boarding_name,
        %s::text AS alighting_name,
        %s::text AS direction_name,
        %s::text AS branch_id,
        %s::text AS origin_terminal,
        %s::text AS destination_terminal,
        ST_GeomFromText(%s, 4326) AS provider_geometry,
        %s::double precision AS stop_radius_meters,
        %s::integer AS row_limit
), candidates AS (
    SELECT
        tr.id::text AS route_id,
        tr.canonical_name AS route_name,
        tr.route_type AS route_type,
        bs.id::text AS boarding_stop_id,
        bs.canonical_name AS boarding_name,
        ST_X(bs.coordinate::geometry) AS boarding_lon,
        ST_Y(bs.coordinate::geometry) AS boarding_lat,
        brs.sequence AS boarding_sequence,
        als.id::text AS alighting_stop_id,
        als.canonical_name AS alighting_name,
        ST_X(als.coordinate::geometry) AS alighting_lon,
        ST_Y(als.coordinate::geometry) AS alighting_lat,
        ars.sequence AS alighting_sequence,
        brs.direction AS direction,
        COALESCE(bs.attributes->>'branchId', als.attributes->>'branchId') AS branch_id,
        origin_stop.canonical_name AS origin_terminal,
        destination_stop.canonical_name AS destination_terminal,
        turning.turning_point_sequence AS turning_point_sequence,
        GREATEST(tr.valid_from, bs.valid_from, als.valid_from) AS valid_from,
        NULLIF(
            LEAST(
                COALESCE(tr.valid_to, 'infinity'::timestamptz),
                COALESCE(bs.valid_to, 'infinity'::timestamptz),
                COALESCE(als.valid_to, 'infinity'::timestamptz)
            ),
            'infinity'::timestamptz
        ) AS valid_to,
        CASE
            WHEN tr.geometry IS NULL OR ST_IsEmpty(i.provider_geometry) THEN NULL
            ELSE GREATEST(
                0.0,
                1.0 - LEAST(
                    ST_HausdorffDistance(
                        ST_Transform(tr.geometry::geometry, 5179),
                        ST_Transform(i.provider_geometry, 5179)
                    ) / 1000.0,
                    1.0
                )
            )
        END AS geometry_similarity,
        EXISTS (
            SELECT 1
            FROM bus_vehicle_trip bvt
            WHERE bvt.route_id = tr.id
              AND bvt.direction = brs.direction
              AND bvt.inferred_end_at IS NULL
        ) AS live_vehicle_exists,
        CASE WHEN lower(regexp_replace(tr.canonical_name, '[^0-9A-Za-z가-힣]+', '', 'g')) = i.route_name THEN 1 ELSE 0 END AS route_exact,
        CASE WHEN lower(regexp_replace(COALESCE(tr.route_type, ''), '[^0-9A-Za-z가-힣]+', '', 'g')) = i.route_type THEN 1 ELSE 0 END AS type_exact,
        CASE WHEN lower(regexp_replace(bs.canonical_name, '[^0-9A-Za-z가-힣]+', '', 'g')) = i.boarding_name THEN 1 ELSE 0 END AS boarding_name_exact,
        CASE WHEN lower(regexp_replace(als.canonical_name, '[^0-9A-Za-z가-힣]+', '', 'g')) = i.alighting_name THEN 1 ELSE 0 END AS alighting_name_exact,
        CASE WHEN lower(regexp_replace(brs.direction, '[^0-9A-Za-z가-힣]+', '', 'g')) = i.direction_name THEN 1 ELSE 0 END AS direction_exact,
        CASE WHEN lower(regexp_replace(COALESCE(bs.attributes->>'branchId', als.attributes->>'branchId', ''), '[^0-9A-Za-z가-힣]+', '', 'g')) = i.branch_id THEN 1 ELSE 0 END AS branch_exact,
        CASE WHEN lower(regexp_replace(origin_stop.canonical_name, '[^0-9A-Za-z가-힣]+', '', 'g')) = i.origin_terminal THEN 1 ELSE 0 END AS origin_exact,
        CASE WHEN lower(regexp_replace(destination_stop.canonical_name, '[^0-9A-Za-z가-힣]+', '', 'g')) = i.destination_terminal THEN 1 ELSE 0 END AS destination_exact,
        ST_Distance(bs.coordinate, i.boarding_point) AS boarding_distance,
        ST_Distance(als.coordinate, i.alighting_point) AS alighting_distance
    FROM transport_route tr
    CROSS JOIN input i
    JOIN route_stop brs ON brs.route_id = tr.id
    JOIN route_stop ars
      ON ars.route_id = tr.id
     AND ars.direction = brs.direction
     AND ars.sequence > brs.sequence
    JOIN transport_stop bs ON bs.id = brs.stop_id
    JOIN transport_stop als ON als.id = ars.stop_id
    JOIN LATERAL (
        SELECT terminal.canonical_name
        FROM route_stop first_rs
        JOIN transport_stop terminal ON terminal.id = first_rs.stop_id
        WHERE first_rs.route_id = tr.id
          AND first_rs.direction = brs.direction
          AND terminal.valid_from <= i.validity_at
          AND (terminal.valid_to IS NULL OR terminal.valid_to > i.validity_at)
        ORDER BY first_rs.sequence ASC, terminal.id ASC
        LIMIT 1
    ) origin_stop ON TRUE
    JOIN LATERAL (
        SELECT terminal.canonical_name
        FROM route_stop last_rs
        JOIN transport_stop terminal ON terminal.id = last_rs.stop_id
        WHERE last_rs.route_id = tr.id
          AND last_rs.direction = brs.direction
          AND terminal.valid_from <= i.validity_at
          AND (terminal.valid_to IS NULL OR terminal.valid_to > i.validity_at)
        ORDER BY last_rs.sequence DESC, terminal.id ASC
        LIMIT 1
    ) destination_stop ON TRUE
    LEFT JOIN LATERAL (
        SELECT turn_rs.sequence AS turning_point_sequence
        FROM route_stop turn_rs
        JOIN transport_stop turn_stop ON turn_stop.id = turn_rs.stop_id
        WHERE turn_rs.route_id = tr.id
          AND turn_rs.direction = brs.direction
          AND turn_stop.valid_from <= i.validity_at
          AND (turn_stop.valid_to IS NULL OR turn_stop.valid_to > i.validity_at)
          AND lower(COALESCE(turn_stop.attributes->>'turningPoint', 'false')) IN ('true', '1', 'yes')
        ORDER BY turn_rs.sequence ASC, turn_stop.id ASC
        LIMIT 1
    ) turning ON TRUE
    WHERE tr.mode = 'BUS'
      AND tr.valid_from <= i.validity_at
      AND (tr.valid_to IS NULL OR tr.valid_to > i.validity_at)
      AND bs.valid_from <= i.validity_at
      AND (bs.valid_to IS NULL OR bs.valid_to > i.validity_at)
      AND als.valid_from <= i.validity_at
      AND (als.valid_to IS NULL OR als.valid_to > i.validity_at)
      AND ST_DWithin(bs.coordinate, i.boarding_point, i.stop_radius_meters)
      AND ST_DWithin(als.coordinate, i.alighting_point, i.stop_radius_meters)
      AND (
          i.route_name IS NULL
          OR strpos(lower(regexp_replace(tr.canonical_name, '[^0-9A-Za-z가-힣]+', '', 'g')), i.route_name) > 0
          OR strpos(i.route_name, lower(regexp_replace(tr.canonical_name, '[^0-9A-Za-z가-힣]+', '', 'g'))) > 0
      )
)
SELECT
    route_id, route_name, route_type,
    boarding_stop_id, boarding_name, boarding_lon, boarding_lat, boarding_sequence,
    alighting_stop_id, alighting_name, alighting_lon, alighting_lat, alighting_sequence,
    direction, branch_id, origin_terminal, destination_terminal, turning_point_sequence,
    valid_from, valid_to, geometry_similarity, live_vehicle_exists
FROM candidates
ORDER BY
    route_exact DESC,
    type_exact DESC,
    boarding_name_exact DESC,
    alighting_name_exact DESC,
    direction_exact DESC,
    branch_exact DESC,
    origin_exact DESC,
    destination_exact DESC,
    geometry_similarity DESC NULLS LAST,
    boarding_distance ASC,
    alighting_distance ASC,
    route_id ASC,
    direction ASC,
    boarding_sequence ASC,
    alighting_sequence ASC
LIMIT (SELECT row_limit FROM input)
""".strip()

_CATALOG_COLUMNS = frozenset(
    {
        "route_id",
        "route_name",
        "route_type",
        "boarding_stop_id",
        "boarding_name",
        "boarding_lon",
        "boarding_lat",
        "boarding_sequence",
        "alighting_stop_id",
        "alighting_name",
        "alighting_lon",
        "alighting_lat",
        "alighting_sequence",
        "direction",
        "branch_id",
        "origin_terminal",
        "destination_terminal",
        "turning_point_sequence",
        "valid_from",
        "valid_to",
        "geometry_similarity",
        "live_vehicle_exists",
    }
)

_GITS_ROAD_LINK_SQL = r"""
WITH requested AS (
    SELECT route_id, direction
    FROM jsonb_to_recordset(%s::jsonb)
         AS item(route_id uuid, direction text)
), qualified AS (
    SELECT
        em.transport_route_id::text AS route_id,
        em.direction AS direction,
        pe.id::text AS provider_entity_id,
        em.id::text AS entity_mapping_id,
        pe.external_id AS link_external_id,
        pe.normalized_identity AS normalized_identity,
        pe.fingerprint AS fingerprint,
        pe.normalized_identity->>'identityVersion' AS identity_version,
        em.algorithm_version AS mapping_version,
        COALESCE(
            pe.normalized_identity = jsonb_build_object(
                'identityVersion', %s::text,
                'linkExternalId', pe.external_id
            ),
            FALSE
        ) AS identity_json_valid,
        (pe.fingerprint ~ '^[0-9a-f]{64}$') AS fingerprint_valid,
        GREATEST(tr.valid_from, pe.valid_from, em.valid_from) AS effective_valid_from,
        NULLIF(
            LEAST(
                COALESCE(tr.valid_to, 'infinity'::timestamptz),
                COALESCE(pe.valid_to, 'infinity'::timestamptz),
                COALESCE(em.valid_to, 'infinity'::timestamptz)
            ),
            'infinity'::timestamptz
        ) AS effective_valid_to
    FROM requested request
    JOIN transport_route tr ON tr.id = request.route_id
    JOIN entity_mapping em
      ON em.transport_route_id = request.route_id
     AND em.direction = request.direction
    JOIN provider_entity pe ON pe.id = em.provider_entity_id
    JOIN provider p ON p.id = pe.provider_id
    JOIN provider_operation_state operation_state
      ON operation_state.provider_id = p.id
     AND operation_state.operation = 'traffic_context'
     AND operation_state.documentation_state = 'DOCUMENTED'
    WHERE p.code = 'GITS'
      AND p.enabled = TRUE
      AND pe.entity_type = 'ROAD_LINK'
      AND em.transport_stop_id IS NULL
      AND em.grade = 'HIGH'
      AND em.score >= 0.92
      AND em.score <= 1.0
      AND em.signal_breakdown->>'reviewDisposition' = 'AUTO_ACCEPT'
      AND em.signal_breakdown->>'mappingVersion' = em.algorithm_version
      AND em.signal_breakdown->>'providerFingerprint' = pe.fingerprint
      AND tr.valid_from <= %s
      AND (tr.valid_to IS NULL OR tr.valid_to > %s)
      AND pe.valid_from <= %s
      AND (pe.valid_to IS NULL OR pe.valid_to > %s)
      AND em.valid_from <= %s
      AND (em.valid_to IS NULL OR em.valid_to > %s)
), ranked AS (
    SELECT
        qualified.*,
        row_number() OVER (
            PARTITION BY route_id, direction
            ORDER BY link_external_id COLLATE "C", provider_entity_id, entity_mapping_id
        ) AS ordinal
    FROM qualified
)
SELECT
    route_id,
    direction,
    COUNT(*)::integer AS matching_count,
    COUNT(DISTINCT link_external_id)::integer AS unique_count,
    MIN(identity_version) AS identity_version,
    COUNT(DISTINCT identity_version)::integer AS identity_version_count,
    MIN(mapping_version) AS mapping_version,
    COUNT(DISTINCT mapping_version)::integer AS mapping_version_count,
    BOOL_AND(identity_json_valid) AS identity_json_valid,
    BOOL_AND(fingerprint_valid) AS fingerprints_valid,
    MAX(effective_valid_from) AS effective_valid_from,
    NULLIF(
        MIN(COALESCE(effective_valid_to, 'infinity'::timestamptz)),
        'infinity'::timestamptz
    ) AS effective_valid_to,
    ARRAY_AGG(
        link_external_id
        ORDER BY link_external_id COLLATE "C", provider_entity_id, entity_mapping_id
    ) FILTER (WHERE ordinal <= %s) AS link_external_ids,
    ARRAY_AGG(
        normalized_identity
        ORDER BY link_external_id COLLATE "C", provider_entity_id, entity_mapping_id
    ) FILTER (WHERE ordinal <= %s) AS normalized_identities,
    ARRAY_AGG(
        fingerprint
        ORDER BY link_external_id COLLATE "C", provider_entity_id, entity_mapping_id
    ) FILTER (WHERE ordinal <= %s) AS provider_fingerprints
FROM ranked
GROUP BY route_id, direction
ORDER BY route_id, direction
""".strip()

_GITS_ROAD_LINK_COLUMNS = frozenset(
    {
        "route_id",
        "direction",
        "matching_count",
        "unique_count",
        "identity_version",
        "identity_version_count",
        "mapping_version",
        "mapping_version_count",
        "identity_json_valid",
        "fingerprints_valid",
        "effective_valid_from",
        "effective_valid_to",
        "link_external_ids",
        "normalized_identities",
        "provider_fingerprints",
    }
)

_ADVISORY_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"
_PROVIDER_SQL = "SELECT id::text AS id FROM provider WHERE code = %s AND enabled = TRUE FOR SHARE"
_ROUTE_SQL = "SELECT id::text AS id FROM transport_route WHERE id = %s AND valid_from <= %s AND (valid_to IS NULL OR valid_to > %s) FOR SHARE"
_UPSERT_PROVIDER_ENTITY_SQL = """
INSERT INTO provider_entity (
    id, provider_id, entity_type, external_id, fingerprint,
    normalized_identity, valid_from, valid_to
) VALUES (%s, %s, 'BUS_LEG', %s, %s, %s::jsonb, %s, %s)
ON CONFLICT (provider_id, entity_type, external_id, valid_from)
DO UPDATE SET
    fingerprint = EXCLUDED.fingerprint,
    normalized_identity = EXCLUDED.normalized_identity,
    valid_to = EXCLUDED.valid_to
RETURNING id::text AS id
""".strip()
_FIND_MAPPING_SQL = """
SELECT id::text AS id
FROM entity_mapping
WHERE provider_entity_id = %s
  AND transport_route_id = %s
  AND transport_stop_id IS NULL
  AND algorithm_version = %s
  AND valid_from = %s
  AND valid_to IS NOT DISTINCT FROM %s
  AND signal_breakdown->>'mappingCacheKey' = %s
FOR UPDATE
""".strip()
_FIND_ACCEPTED_HIGH_MAPPING_SQL = """
SELECT id::text AS id
FROM entity_mapping
WHERE provider_entity_id = %s
  AND transport_route_id = %s
  AND transport_stop_id IS NULL
  AND direction IS NOT DISTINCT FROM %s
  AND score = %s
  AND grade = 'HIGH'
  AND algorithm_version = %s
  AND valid_from = %s
  AND valid_to IS NOT DISTINCT FROM %s
  AND valid_from <= %s
  AND (valid_to IS NULL OR valid_to > %s)
  AND signal_breakdown->>'mappingCacheKey' = %s
  AND signal_breakdown->>'providerFingerprint' = %s
  AND signal_breakdown->>'candidateFingerprint' = %s
  AND signal_breakdown->>'mappingVersion' = %s
  AND signal_breakdown->>'reviewDisposition' = 'AUTO_ACCEPT'
FOR UPDATE
""".strip()
_INSERT_MAPPING_SQL = """
INSERT INTO entity_mapping (
    id, provider_entity_id, transport_route_id, transport_stop_id,
    direction, score, grade, signal_breakdown, algorithm_version,
    valid_from, valid_to
) VALUES (%s, %s, %s, NULL, %s, %s, %s, %s::jsonb, %s, %s, %s)
RETURNING id::text AS id
""".strip()
_FIND_PENDING_REVIEW_SQL = """
SELECT id::text AS id
FROM mapping_review
WHERE entity_mapping_id = %s
  AND status = 'PENDING'
  AND note = %s
FOR UPDATE
""".strip()
_INSERT_REVIEW_SQL = """
INSERT INTO mapping_review (
    id, entity_mapping_id, status, reviewer, note, reviewed_at
) VALUES (%s, %s, %s, %s, %s, %s)
RETURNING id::text AS id
""".strip()
_FIND_REVIEW_MAPPING_SQL = """
SELECT entity_mapping_id::text AS entity_mapping_id
FROM mapping_review
WHERE id = %s
FOR UPDATE
""".strip()


def _require_database(database: SqlDatabase | None) -> SqlDatabase:
    if database is None:
        raise MappingDatabaseUnavailable(
            "Routing PostGIS database connection is required; no fallback is allowed"
        )
    return database


def _require_timeout(value: int) -> int:
    if not 1 <= value <= MAX_STATEMENT_TIMEOUT_MS:
        raise MappingQueryBoundsError(
            f"statement timeout must be between 1 and {MAX_STATEMENT_TIMEOUT_MS} ms"
        )
    return value


def _set_timeout(session: SqlSession, timeout_ms: int) -> None:
    session.execute(_SET_TIMEOUT_SQL, (f"{timeout_ms}ms",))


def _sample_geometry(points: tuple[Coordinate, ...]) -> tuple[Coordinate, ...]:
    if len(points) <= MAX_GEOMETRY_SAMPLE_POINTS:
        return points
    last = len(points) - 1
    indices = {
        round(index * last / (MAX_GEOMETRY_SAMPLE_POINTS - 1))
        for index in range(MAX_GEOMETRY_SAMPLE_POINTS)
    }
    return tuple(points[index] for index in sorted(indices))


def _geometry_wkt(points: tuple[Coordinate, ...]) -> str:
    sampled = _sample_geometry(points)
    if len(sampled) < 2:
        return "LINESTRING EMPTY"
    body = ",".join(f"{point.lon:.7f} {point.lat:.7f}" for point in sampled)
    return f"LINESTRING({body})"


def _normalized(value: str | None, normalizer) -> str | None:
    result = normalizer(value)
    if result is None:
        return None
    normalized = result.casefold()
    if len(normalized) > MAX_QUERY_TEXT_LENGTH:
        raise MappingQueryBoundsError(
            f"normalized query text exceeds {MAX_QUERY_TEXT_LENGTH} characters"
        )
    return normalized


def _integer(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MappingRowSchemaError(f"{field_name} must be a non-negative integer")
    return value


def _optional_integer(value: object, field_name: str) -> int | None:
    return None if value is None else _integer(value, field_name)


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MappingRowSchemaError(f"{field_name} must be non-blank text")
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    return None if value is None else _text(value, field_name)


def _uuid_text(value: object, field_name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise MappingRowSchemaError(f"{field_name} must be a UUID") from exc


def _aware_time(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MappingRowSchemaError(f"{field_name} must be timezone-aware datetime")
    return value


def _optional_time(value: object, field_name: str) -> datetime | None:
    return None if value is None else _aware_time(value, field_name)


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise MappingRowSchemaError(f"{field_name} must be numeric")
    result = float(value)
    if not isfinite(result):
        raise MappingRowSchemaError(f"{field_name} must be finite")
    return result


def _gits_targets_json(targets: tuple[tuple[str, str], ...]) -> str:
    if not 1 <= len(targets) <= MAX_CANDIDATES:
        raise MappingQueryBoundsError("GITS identity target count is outside the bound")
    if len(set(targets)) != len(targets):
        raise MappingQueryBoundsError("GITS identity targets must be unique")
    values: list[dict[str, str]] = []
    for route_id, direction in sorted(targets):
        try:
            canonical_route_id = str(UUID(route_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise MappingQueryBoundsError(
                "GITS identity target route_id must be a UUID"
            ) from exc
        if canonical_route_id != route_id:
            raise MappingQueryBoundsError(
                "GITS identity target route_id must use canonical UUID text"
            )
        if not direction.strip() or len(direction) > 128:
            raise MappingQueryBoundsError(
                "GITS identity target direction must be bounded non-blank text"
            )
        values.append({"direction": direction, "route_id": route_id})
    encoded = json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(encoded.encode("utf-8")) > MAX_IDENTITY_JSON_BYTES:
        raise MappingQueryBoundsError("GITS identity target JSON exceeds the bound")
    return encoded


def _decode_gits_road_link_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    requested: frozenset[tuple[str, str]],
    as_of: datetime,
    max_links: int,
) -> dict[tuple[str, str], GitsRoadLinkIdentity]:
    result: dict[tuple[str, str], GitsRoadLinkIdentity] = {}
    ambiguous: set[tuple[str, str]] = set()
    for row in rows:
        if frozenset(row) != _GITS_ROAD_LINK_COLUMNS:
            missing = sorted(_GITS_ROAD_LINK_COLUMNS - frozenset(row))
            extra = sorted(frozenset(row) - _GITS_ROAD_LINK_COLUMNS)
            raise MappingRowSchemaError(
                f"GITS road-link row schema drift; missing={missing}, extra={extra}"
            )
        key = (
            _uuid_text(row["route_id"], "GITS route_id"),
            _text(row["direction"], "GITS direction"),
        )
        if key not in requested:
            raise MappingRowSchemaError(
                "GITS road-link query returned an unrequested route direction"
            )
        if key in result or key in ambiguous:
            result.pop(key, None)
            ambiguous.add(key)
            continue

        matching_count = _integer(row["matching_count"], "GITS matching_count")
        unique_count = _integer(row["unique_count"], "GITS unique_count")
        identity_version_count = _integer(
            row["identity_version_count"], "GITS identity_version_count"
        )
        mapping_version_count = _integer(
            row["mapping_version_count"], "GITS mapping_version_count"
        )
        identity_json_valid = row["identity_json_valid"]
        fingerprints_valid = row["fingerprints_valid"]
        if not isinstance(identity_json_valid, bool) or not isinstance(
            fingerprints_valid, bool
        ):
            raise MappingRowSchemaError("GITS aggregate validity flags must be boolean")
        links_value = row["link_external_ids"]
        identities_value = row["normalized_identities"]
        fingerprints_value = row["provider_fingerprints"]
        if not all(
            isinstance(value, (list, tuple))
            for value in (links_value, identities_value, fingerprints_value)
        ):
            raise MappingRowSchemaError(
                "GITS identity content columns must be arrays"
            )
        links = tuple(links_value)
        normalized_identities = tuple(identities_value)
        provider_fingerprints = tuple(fingerprints_value)

        # Every invalid, stale, oversized, duplicated, or version-ambiguous
        # aggregate is rejected as a unit.  Partial traffic identity would be
        # more dangerous than no traffic enrichment.
        if (
            matching_count == 0
            or matching_count > max_links
            or unique_count != matching_count
            or len(links) != matching_count
            or len(normalized_identities) != matching_count
            or len(provider_fingerprints) != matching_count
            or identity_version_count != 1
            or mapping_version_count != 1
            or not identity_json_valid
            or not fingerprints_valid
            or row["identity_version"] != GITS_ROAD_LINK_IDENTITY_VERSION
            or not isinstance(row["mapping_version"], str)
        ):
            continue
        content_valid = True
        for link_external_id, normalized_identity, fingerprint in zip(
            links,
            normalized_identities,
            provider_fingerprints,
            strict=True,
        ):
            if not isinstance(link_external_id, str):
                content_valid = False
                break
            try:
                expected_identity = gits_road_link_normalized_identity(
                    link_external_id
                )
                expected_fingerprint = gits_road_link_identity_fingerprint(
                    link_external_id
                )
            except ValueError:
                content_valid = False
                break
            if (
                not isinstance(normalized_identity, Mapping)
                or dict(normalized_identity) != expected_identity
                or not isinstance(fingerprint, str)
                or _SHA256.fullmatch(fingerprint) is None
                or fingerprint != expected_fingerprint
            ):
                content_valid = False
                break
        if not content_valid:
            continue
        valid_from = _aware_time(
            row["effective_valid_from"], "GITS effective_valid_from"
        )
        valid_to = _optional_time(
            row["effective_valid_to"], "GITS effective_valid_to"
        )
        try:
            identity = GitsRoadLinkIdentity(
                link_external_ids=links,  # type: ignore[arg-type]
                mapping_version=row["mapping_version"],
                validity=ValidityWindow(valid_from, valid_to),
                identity_version=GITS_ROAD_LINK_IDENTITY_VERSION,
            )
        except ValueError:
            continue
        if identity.validity.contains(as_of):
            result[key] = identity
    return result


class PostgisGitsRoadLinkIdentityRepository(GitsRoadLinkIdentityRepository):
    """Read accepted, current GITS link mappings without spatial inference."""

    def __init__(
        self,
        database: SqlDatabase | None,
        *,
        statement_timeout_ms: int = 350,
        max_links: int = MAX_GITS_ROAD_LINK_IDS,
    ) -> None:
        self._database = _require_database(database)
        self._statement_timeout_ms = _require_timeout(statement_timeout_ms)
        if not 1 <= max_links <= MAX_GITS_ROAD_LINK_IDS:
            raise MappingQueryBoundsError(
                f"GITS link bound must be between 1 and {MAX_GITS_ROAD_LINK_IDS}"
            )
        self._max_links = max_links

    def find_for_targets(
        self,
        targets: tuple[tuple[str, str], ...],
        *,
        as_of: datetime,
    ) -> Mapping[tuple[str, str], GitsRoadLinkIdentity]:
        if not targets:
            return {}
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise MappingQueryBoundsError("GITS identity as_of must be timezone-aware")
        encoded_targets = _gits_targets_json(targets)
        requested = frozenset(targets)
        parameters: tuple[object, ...] = (
            encoded_targets,
            GITS_ROAD_LINK_IDENTITY_VERSION,
            as_of,
            as_of,
            as_of,
            as_of,
            as_of,
            as_of,
            self._max_links + 1,
            self._max_links + 1,
            self._max_links + 1,
        )
        with self._database.transaction(read_only=True) as session:
            _set_timeout(session, self._statement_timeout_ms)
            rows = session.fetch_all(_GITS_ROAD_LINK_SQL, parameters)
        if len(rows) > len(targets):
            raise MappingRowSchemaError(
                "GITS road-link adapter returned more aggregates than targets"
            )
        return _decode_gits_road_link_rows(
            rows,
            requested=requested,
            as_of=as_of,
            max_links=self._max_links,
        )


def _decode_catalog_row(row: Mapping[str, object]) -> CanonicalRouteCandidate:
    if frozenset(row) != _CATALOG_COLUMNS:
        missing = sorted(_CATALOG_COLUMNS - frozenset(row))
        extra = sorted(frozenset(row) - _CATALOG_COLUMNS)
        raise MappingRowSchemaError(
            f"GBIS catalog row schema drift; missing={missing}, extra={extra}"
        )
    geometry = row["geometry_similarity"]
    geometry_similarity = None if geometry is None else _number(geometry, "geometry_similarity")
    if geometry_similarity is not None and not 0 <= geometry_similarity <= 1:
        raise MappingRowSchemaError("geometry_similarity must be between 0 and 1")
    live = row["live_vehicle_exists"]
    if not isinstance(live, bool):
        raise MappingRowSchemaError("live_vehicle_exists must be boolean")
    valid_from = _aware_time(row["valid_from"], "valid_from")
    valid_to = _optional_time(row["valid_to"], "valid_to")
    return CanonicalRouteCandidate(
        route_id=_uuid_text(row["route_id"], "route_id"),
        route_name=_text(row["route_name"], "route_name"),
        route_type=_optional_text(row["route_type"], "route_type"),
        boarding=StopSignal(
            name=_text(row["boarding_name"], "boarding_name"),
            coordinate=Coordinate(
                lon=_number(row["boarding_lon"], "boarding_lon"),
                lat=_number(row["boarding_lat"], "boarding_lat"),
            ),
            external_id=_uuid_text(row["boarding_stop_id"], "boarding_stop_id"),
            sequence=_integer(row["boarding_sequence"], "boarding_sequence"),
        ),
        alighting=StopSignal(
            name=_text(row["alighting_name"], "alighting_name"),
            coordinate=Coordinate(
                lon=_number(row["alighting_lon"], "alighting_lon"),
                lat=_number(row["alighting_lat"], "alighting_lat"),
            ),
            external_id=_uuid_text(row["alighting_stop_id"], "alighting_stop_id"),
            sequence=_integer(row["alighting_sequence"], "alighting_sequence"),
        ),
        direction=_text(row["direction"], "direction"),
        branch_id=_optional_text(row["branch_id"], "branch_id"),
        origin_terminal=_text(row["origin_terminal"], "origin_terminal"),
        destination_terminal=_text(row["destination_terminal"], "destination_terminal"),
        validity=ValidityWindow(valid_from, valid_to),
        geometry_similarity_to_provider=geometry_similarity,
        live_vehicle_exists=live,
        turning_point_sequence=_optional_integer(
            row["turning_point_sequence"],
            "turning_point_sequence",
        ),
    )


class PostgisGbisCatalogRepository(GbisCatalogRepository):
    def __init__(
        self,
        database: SqlDatabase | None,
        *,
        statement_timeout_ms: int = 600,
        max_rows: int = 32,
        max_radius_meters: int = 750,
        gits_identity_repository: GitsRoadLinkIdentityRepository | None = None,
    ) -> None:
        self._database = _require_database(database)
        self._statement_timeout_ms = _require_timeout(statement_timeout_ms)
        if not 1 <= max_rows <= MAX_CANDIDATES:
            raise MappingQueryBoundsError(
                f"max_rows must be between 1 and {MAX_CANDIDATES}"
            )
        if not 1 <= max_radius_meters <= MAX_QUERY_RADIUS_METERS:
            raise MappingQueryBoundsError(
                f"max_radius_meters must be between 1 and {MAX_QUERY_RADIUS_METERS}"
            )
        self._max_rows = max_rows
        self._max_radius_meters = max_radius_meters
        self._gits_identity_repository = (
            gits_identity_repository
            if gits_identity_repository is not None
            else DisabledGitsRoadLinkIdentityRepository()
        )

    def find_candidates(
        self,
        query: CatalogQuery,
    ) -> tuple[CanonicalRouteCandidate, ...]:
        boarding = query.source.boarding.coordinate
        alighting = query.source.alighting.coordinate
        if boarding is None or alighting is None:
            raise MappingQueryBoundsError(
                "PostGIS candidate lookup requires both canonical stop coordinates"
            )
        if query.stop_radius_meters > self._max_radius_meters:
            raise MappingQueryBoundsError(
                "query stop radius exceeds the configured production bound"
            )
        row_limit = min(query.max_candidates, self._max_rows)
        parameters: tuple[object, ...] = (
            boarding.lon,
            boarding.lat,
            alighting.lon,
            alighting.lat,
            query.as_of,
            _normalized(query.source.route_name, normalize_route_name),
            _normalized(query.source.route_type, normalize_type),
            _normalized(query.source.boarding.name, normalize_stop_name),
            _normalized(query.source.alighting.name, normalize_stop_name),
            _normalized(query.source.direction, normalize_direction),
            _normalized(query.source.branch_id, normalize_branch),
            _normalized(query.source.origin_terminal, normalize_stop_name),
            _normalized(query.source.destination_terminal, normalize_stop_name),
            _geometry_wkt(query.source.geometry),
            query.stop_radius_meters,
            row_limit,
        )
        with self._database.transaction(read_only=True) as session:
            _set_timeout(session, self._statement_timeout_ms)
            rows = session.fetch_all(_CATALOG_SQL, parameters)
        if len(rows) > row_limit:
            raise MappingRowSchemaError(
                "GBIS catalog adapter returned more rows than the server-side cap"
            )
        candidates = tuple(_decode_catalog_row(row) for row in rows)
        targets = tuple(
            sorted(
                {
                    (candidate.route_id, candidate.direction)
                    for candidate in candidates
                    if candidate.direction is not None
                }
            )
        )
        if not targets:
            return candidates
        try:
            identities = self._gits_identity_repository.find_for_targets(
                targets,
                as_of=query.as_of,
            )
        except (MappingDatabaseError, ValueError, TimeoutError, ConnectionError):
            # Traffic context is optional.  Mapping remains usable, while no
            # caller-controlled geometry/bbox can substitute for durable link
            # identity if the repository is unavailable or rejects its data.
            identities = {}
        return tuple(
            replace(
                candidate,
                gits_road_link_identity=identities.get(
                    (candidate.route_id, candidate.direction)
                ),
            )
            for candidate in candidates
        )


def _strict_id(row: Mapping[str, object] | None, operation: str) -> str:
    if row is None:
        raise MappingDatabaseError(f"{operation} returned no row")
    if frozenset(row) != {"id"}:
        raise MappingRowSchemaError(f"{operation} result schema drift")
    return _uuid_text(row["id"], f"{operation}.id")


def _json(value: Mapping[str, object]) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise MappingDatabaseError("mapping persistence JSON is not serializable") from exc
    if len(encoded.encode("utf-8")) > MAX_IDENTITY_JSON_BYTES:
        raise MappingQueryBoundsError("mapping persistence JSON exceeds the hard bound")
    return encoded


def _require_sha256(value: str, field_name: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise MappingDatabaseError(f"{field_name} must be a lowercase SHA-256 hex digest")


def _bounded_text(
    value: str,
    field_name: str,
    maximum: int,
) -> str:
    if not value.strip() or len(value) > maximum:
        raise MappingQueryBoundsError(
            f"{field_name} must be non-blank and at most {maximum} characters"
        )
    return value


class PostgresAcceptedHighMappingRepository(AcceptedHighMappingRepository):
    """Atomically persist and return an AUTO_ACCEPT, current HIGH resolution."""

    def __init__(
        self,
        database: SqlDatabase | None,
        *,
        statement_timeout_ms: int = 600,
    ) -> None:
        self._database = _require_database(database)
        self._statement_timeout_ms = _require_timeout(statement_timeout_ms)

    def persist(
        self,
        entry: AcceptedHighMappingEntry,
    ) -> PersistedMappingResolution:
        mapping = entry.mapping
        _require_sha256(entry.cache_key, "cache_key")
        _require_sha256(mapping.provider_fingerprint, "provider_fingerprint")
        _require_sha256(mapping.candidate_fingerprint, "candidate_fingerprint")
        _bounded_text(entry.provider, "provider", 255)
        _bounded_text(entry.provider_external_id, "provider_external_id", 255)
        _bounded_text(mapping.mapping_version, "mapping_version", 128)
        if entry.direction is not None:
            _bounded_text(entry.direction, "direction", 128)
        if mapping.grade is not MappingGrade.HIGH:
            raise MappingDatabaseError("only HIGH mappings can be persisted as accepted")
        if mapping.review.disposition.value != "AUTO_ACCEPT":
            raise MappingDatabaseError("accepted HIGH mapping must be AUTO_ACCEPT")
        if mapping.blockers or not mapping.allows_bus_intelligence:
            raise MappingDatabaseError("blocked mapping cannot be persisted as accepted")
        if not mapping.validity.contains(entry.accepted_at):
            raise MappingDatabaseError("accepted mapping must be current")

        route_id = _uuid_text(mapping.route_id, "route_id")
        normalized_identity = dict(entry.provider_identity)
        normalized_identity["mappingCacheKey"] = entry.cache_key
        signal_breakdown = dict(entry.signal_breakdown)
        signal_breakdown.update(
            {
                "mappingCacheKey": entry.cache_key,
                "providerFingerprint": mapping.provider_fingerprint,
                "candidateFingerprint": mapping.candidate_fingerprint,
                "mappingVersion": mapping.mapping_version,
                "reviewDisposition": "AUTO_ACCEPT",
            }
        )
        score = str(Decimal(str(mapping.score)))

        with self._database.transaction(read_only=False) as session:
            _set_timeout(session, self._statement_timeout_ms)
            session.execute(_ADVISORY_LOCK_SQL, (entry.cache_key,))
            provider_id = _strict_id(
                session.fetch_one(_PROVIDER_SQL, (entry.provider,)),
                "provider lookup",
            )
            _strict_id(
                session.fetch_one(
                    _ROUTE_SQL,
                    (route_id, entry.accepted_at, entry.accepted_at),
                ),
                "transport route lookup",
            )
            provider_entity_id = _strict_id(
                session.fetch_one(
                    _UPSERT_PROVIDER_ENTITY_SQL,
                    (
                        str(uuid4()),
                        provider_id,
                        entry.provider_external_id,
                        mapping.provider_fingerprint,
                        _json(normalized_identity),
                        mapping.validity.valid_from,
                        mapping.validity.valid_to,
                    ),
                ),
                "provider entity upsert",
            )
            lookup_parameters: tuple[object, ...] = (
                provider_entity_id,
                route_id,
                entry.direction,
                score,
                mapping.mapping_version,
                mapping.validity.valid_from,
                mapping.validity.valid_to,
                entry.accepted_at,
                entry.accepted_at,
                entry.cache_key,
                mapping.provider_fingerprint,
                mapping.candidate_fingerprint,
                mapping.mapping_version,
            )
            mapping_row = session.fetch_one(
                _FIND_ACCEPTED_HIGH_MAPPING_SQL,
                lookup_parameters,
            )
            if mapping_row is None:
                mapping_id = _strict_id(
                    session.fetch_one(
                        _INSERT_MAPPING_SQL,
                        (
                            str(uuid4()),
                            provider_entity_id,
                            route_id,
                            entry.direction,
                            score,
                            MappingGrade.HIGH.value,
                            _json(signal_breakdown),
                            mapping.mapping_version,
                            mapping.validity.valid_from,
                            mapping.validity.valid_to,
                        ),
                    ),
                    "accepted entity mapping insert",
                )
            else:
                mapping_id = _strict_id(
                    mapping_row,
                    "accepted entity mapping lookup",
                )

        return PersistedMappingResolution(
            entity_mapping_id=mapping_id,
            provider_fingerprint=mapping.provider_fingerprint,
            candidate_fingerprint=mapping.candidate_fingerprint,
            route_id=mapping.route_id,
            mapping_version=mapping.mapping_version,
            validity=mapping.validity,
            accepted_at=entry.accepted_at,
        )


class PostgresMappingReviewRepository(MappingReviewRepository):
    def __init__(
        self,
        database: SqlDatabase | None,
        *,
        statement_timeout_ms: int = 600,
    ) -> None:
        self._database = _require_database(database)
        self._statement_timeout_ms = _require_timeout(statement_timeout_ms)

    def enqueue(self, entry: ReviewQueueEntry) -> str:
        _require_sha256(entry.cache_key, "cache_key")
        _require_sha256(entry.provider_fingerprint, "provider_fingerprint")
        _require_sha256(entry.candidate_fingerprint, "candidate_fingerprint")
        if entry.grade is MappingGrade.HIGH:
            raise MappingDatabaseError("HIGH mappings must not enter the review queue")
        if entry.requested_at.tzinfo is None or entry.requested_at.utcoffset() is None:
            raise MappingDatabaseError("requested_at must be timezone-aware")
        _bounded_text(entry.provider, "provider", 255)
        _bounded_text(entry.provider_external_id, "provider_external_id", 255)
        _bounded_text(entry.mapping_version, "mapping_version", 128)
        if entry.direction is not None:
            _bounded_text(entry.direction, "direction", 128)
        if not 0 <= entry.score <= 1:
            raise MappingDatabaseError("review mapping score must be between 0 and 1")
        if not entry.validity.contains(entry.requested_at):
            raise MappingDatabaseError("review request must fall inside mapping validity")
        route_id = _uuid_text(entry.route_id, "route_id")
        normalized_identity = dict(entry.provider_identity)
        normalized_identity["mappingCacheKey"] = entry.cache_key
        signal_breakdown = dict(entry.signal_breakdown)
        signal_breakdown["mappingCacheKey"] = entry.cache_key
        review_note = json.dumps(
            {
                "mappingCacheKey": entry.cache_key,
                "reasons": list(entry.reasons),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(review_note) > MAX_REVIEW_NOTE_LENGTH:
            raise MappingQueryBoundsError("review queue note exceeds the hard bound")
        with self._database.transaction(read_only=False) as session:
            _set_timeout(session, self._statement_timeout_ms)
            session.execute(_ADVISORY_LOCK_SQL, (entry.cache_key,))
            provider_id = _strict_id(
                session.fetch_one(_PROVIDER_SQL, (entry.provider,)),
                "provider lookup",
            )
            _strict_id(
                session.fetch_one(
                    _ROUTE_SQL,
                    (route_id, entry.requested_at, entry.requested_at),
                ),
                "transport route lookup",
            )
            provider_entity_id = _strict_id(
                session.fetch_one(
                    _UPSERT_PROVIDER_ENTITY_SQL,
                    (
                        str(uuid4()),
                        provider_id,
                        entry.provider_external_id,
                        entry.provider_fingerprint,
                        _json(normalized_identity),
                        entry.validity.valid_from,
                        entry.validity.valid_to,
                    ),
                ),
                "provider entity upsert",
            )
            mapping_row = session.fetch_one(
                _FIND_MAPPING_SQL,
                (
                    provider_entity_id,
                    route_id,
                    entry.mapping_version,
                    entry.validity.valid_from,
                    entry.validity.valid_to,
                    entry.cache_key,
                ),
            )
            if mapping_row is None:
                mapping_id = _strict_id(
                    session.fetch_one(
                        _INSERT_MAPPING_SQL,
                        (
                            str(uuid4()),
                            provider_entity_id,
                            route_id,
                            entry.direction,
                            str(Decimal(str(entry.score))),
                            entry.grade.value,
                            _json(signal_breakdown),
                            entry.mapping_version,
                            entry.validity.valid_from,
                            entry.validity.valid_to,
                        ),
                    ),
                    "entity mapping insert",
                )
            else:
                mapping_id = _strict_id(mapping_row, "entity mapping lookup")
            review_row = session.fetch_one(
                _FIND_PENDING_REVIEW_SQL,
                (mapping_id, review_note),
            )
            if review_row is not None:
                return _strict_id(review_row, "pending review lookup")
            return _strict_id(
                session.fetch_one(
                    _INSERT_REVIEW_SQL,
                    (
                        str(uuid4()),
                        mapping_id,
                        "PENDING",
                        None,
                        review_note,
                        None,
                    ),
                ),
                "mapping review insert",
            )

    def append_review_state(
        self,
        review_ticket_id: str,
        *,
        status: str,
        reviewer: str,
        note: str | None,
        reviewed_at: datetime,
    ) -> str:
        ticket_id = _uuid_text(review_ticket_id, "review_ticket_id")
        normalized_status = status.strip().upper()
        if normalized_status not in {"APPROVED", "REJECTED"}:
            raise MappingDatabaseError("review status must be APPROVED or REJECTED")
        if not reviewer.strip() or len(reviewer) > 255:
            raise MappingDatabaseError("reviewer must be non-blank and at most 255 characters")
        if note is not None and len(note) > MAX_REVIEW_NOTE_LENGTH:
            raise MappingDatabaseError("review note exceeds the bounded length")
        if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
            raise MappingDatabaseError("reviewed_at must be timezone-aware")
        with self._database.transaction(read_only=False) as session:
            _set_timeout(session, self._statement_timeout_ms)
            row = session.fetch_one(_FIND_REVIEW_MAPPING_SQL, (ticket_id,))
            if row is None:
                raise MappingDatabaseError("review ticket was not found")
            if frozenset(row) != {"entity_mapping_id"}:
                raise MappingRowSchemaError("review ticket lookup result schema drift")
            mapping_id = _uuid_text(row["entity_mapping_id"], "entity_mapping_id")
            return _strict_id(
                session.fetch_one(
                    _INSERT_REVIEW_SQL,
                    (
                        str(uuid4()),
                        mapping_id,
                        normalized_status,
                        reviewer,
                        note,
                        reviewed_at,
                    ),
                ),
                "mapping review state insert",
            )
