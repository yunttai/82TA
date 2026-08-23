"""Routing-DB point-in-time feature sources for verified online models.

Each load owns one read-only ``REPEATABLE READ`` snapshot, applies local timeout
limits, executes one family-specific fixed statement, and strictly decodes one
identity row.  The statements only use tables present in ``routing-db.dbml``.
They deliberately return no feature record when the database cannot prove every
required core feature from evidence available at the caller's as-of timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
from math import isfinite
from typing import Any, Callable, Protocol
from uuid import UUID

from bus_intelligence_core import EtaPredictorInput, SeatRiskPredictorInput

from .dbapi import Connection, Cursor
from .feature_builder import NormalizedFeatureObservation
from .serving_features import (
    EtaServingFeatureRecord,
    SeatRiskServingFeatureRecord,
    ServingFeatureSourceError,
)


class PostgresServingFeatureSourceError(ServingFeatureSourceError):
    """Base error for an unprovable or malformed Routing-DB serving read."""


class EtaPostgresServingFeatureSourceError(PostgresServingFeatureSourceError):
    """ETA-specific read failure; never aliases the Seat Risk failure path."""


class SeatRiskPostgresServingFeatureSourceError(PostgresServingFeatureSourceError):
    """Seat-specific read failure; never aliases the ETA failure path."""


ServingConnectionFactory = Callable[[], Connection]


@dataclass(frozen=True, slots=True)
class ServingSnapshotTimeouts:
    """Hard online lookup limits; callers may only tighten the frozen maxima."""

    statement_ms: int = 120
    lock_ms: int = 50
    idle_in_transaction_ms: int = 250

    def __post_init__(self) -> None:
        limits = (
            (self.statement_ms, 120, "statement"),
            (self.lock_ms, 50, "lock"),
            (self.idle_in_transaction_ms, 250, "idle-in-transaction"),
        )
        for value, maximum, name in limits:
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                or value > maximum
            ):
                raise PostgresServingFeatureSourceError(
                    f"{name} timeout must be an integer in [1, {maximum}] ms"
                )


_BEGIN_READ_SNAPSHOT_SQL = (
    "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
)
_SET_STATEMENT_TIMEOUT_SQL = (
    "SELECT set_config('statement_timeout', %s, true)"
)
_SET_LOCK_TIMEOUT_SQL = "SELECT set_config('lock_timeout', %s, true)"
_SET_IDLE_TIMEOUT_SQL = (
    "SELECT set_config('idle_in_transaction_session_timeout', %s, true)"
)


# The row shape is documented by ``_decode_eta_row`` below.  All identifiers and
# timestamps are typed parameters; no caller value is interpolated into SQL text.
ETA_POINT_IN_TIME_SQL = """
WITH requested AS (
    SELECT
        %s::uuid AS route_id,
        %s::varchar AS direction,
        %s::varchar AS vehicle_token,
        %s::uuid AS boarding_stop_id,
        %s::timestamptz AS observed_at,
        %s::timestamptz AS as_of
),
identity_candidates AS (
    SELECT
        trip.id AS trip_id,
        trip.route_id,
        trip.direction,
        vehicle.provider_vehicle_token AS vehicle_ref,
        request.boarding_stop_id,
        current_location.station_sequence AS current_sequence,
        boarding.sequence AS target_sequence,
        current_location.observed_at,
        current_location.ingested_at,
        current_location.quality_flags
    FROM requested AS request
    JOIN bus_vehicle AS vehicle
      ON vehicle.provider_vehicle_token = request.vehicle_token
    JOIN bus_vehicle_trip AS trip
      ON trip.vehicle_id = vehicle.id
     AND trip.route_id = request.route_id
     AND trip.direction = request.direction
     AND trip.inferred_start_at <= request.observed_at
     AND (trip.inferred_end_at IS NULL OR trip.inferred_end_at >= request.observed_at)
    JOIN transport_route AS canonical_route
      ON canonical_route.id = trip.route_id
     AND canonical_route.valid_from <= request.observed_at
     AND (canonical_route.valid_to IS NULL OR canonical_route.valid_to > request.observed_at)
    JOIN bus_location_observation AS current_location
      ON current_location.trip_id = trip.id
     AND current_location.observed_at = request.observed_at
     AND current_location.ingested_at <= request.as_of
     AND current_location.station_sequence IS NOT NULL
     AND current_location.stop_id IS NOT NULL
    JOIN route_stop AS current_route_stop
      ON current_route_stop.route_id = trip.route_id
     AND current_route_stop.direction = trip.direction
     AND current_route_stop.sequence = current_location.station_sequence
     AND current_route_stop.stop_id = current_location.stop_id
    JOIN transport_stop AS current_stop
      ON current_stop.id = current_route_stop.stop_id
     AND current_stop.valid_from <= request.observed_at
     AND (current_stop.valid_to IS NULL OR current_stop.valid_to > request.observed_at)
    JOIN route_stop AS boarding
      ON boarding.route_id = trip.route_id
     AND boarding.direction = trip.direction
     AND boarding.stop_id = request.boarding_stop_id
     AND boarding.sequence >= current_location.station_sequence
    JOIN transport_stop AS boarding_canonical_stop
      ON boarding_canonical_stop.id = boarding.stop_id
     AND boarding_canonical_stop.valid_from <= request.observed_at
     AND (boarding_canonical_stop.valid_to IS NULL OR boarding_canonical_stop.valid_to > request.observed_at)
),
location_points AS (
    SELECT DISTINCT ON (identity.trip_id, location.station_sequence)
        identity.trip_id,
        location.station_sequence,
        location.observed_at
    FROM identity_candidates AS identity
    JOIN requested AS request ON true
    JOIN bus_location_observation AS location
     ON location.trip_id = identity.trip_id
     AND location.station_sequence IS NOT NULL
     AND location.observed_at <= identity.observed_at
     AND location.ingested_at <= request.as_of
    ORDER BY identity.trip_id, location.station_sequence,
             location.observed_at DESC, location.id DESC
),
segments AS (
    SELECT
        trip_id,
        station_sequence,
        EXTRACT(EPOCH FROM (
            observed_at - LAG(observed_at) OVER (
                PARTITION BY trip_id ORDER BY station_sequence
            )
        )) / NULLIF(
            station_sequence - LAG(station_sequence) OVER (
                PARTITION BY trip_id ORDER BY station_sequence
            ),
            0
        ) AS segment_seconds
    FROM location_points
),
ranked_segments AS (
    SELECT
        trip_id,
        segment_seconds,
        ROW_NUMBER() OVER (
            PARTITION BY trip_id ORDER BY station_sequence DESC
        ) AS recency_rank
    FROM segments
    WHERE segment_seconds > 0
),
recent AS (
    SELECT
        trip_id,
        AVG(segment_seconds) FILTER (WHERE recency_rank <= 1) AS recent_1,
        AVG(segment_seconds) FILTER (WHERE recency_rank <= 3) AS recent_3,
        AVG(segment_seconds) FILTER (WHERE recency_rank <= 5) AS recent_5,
        COUNT(*) FILTER (WHERE recency_rank <= 5) AS recent_count
    FROM ranked_segments
    GROUP BY trip_id
),
historical_points AS (
    SELECT DISTINCT ON (
        reference.trip_id,
        historical_trip.id,
        location.station_sequence
    )
        reference.trip_id AS reference_trip_id,
        historical_trip.id AS historical_trip_id,
        location.station_sequence,
        location.observed_at
    FROM identity_candidates AS reference
    JOIN requested AS request ON true
    JOIN bus_vehicle_trip AS historical_trip
      ON historical_trip.route_id = reference.route_id
     AND historical_trip.direction = reference.direction
     AND historical_trip.id <> reference.trip_id
     AND historical_trip.inferred_start_at < reference.observed_at
    JOIN bus_location_observation AS location
      ON location.trip_id = historical_trip.id
     AND location.station_sequence BETWEEN reference.current_sequence
                                       AND reference.target_sequence
     AND location.observed_at < reference.observed_at
     AND location.observed_at >= reference.observed_at - INTERVAL '28 days'
     AND location.ingested_at <= request.as_of
    ORDER BY reference.trip_id, historical_trip.id, location.station_sequence,
             location.observed_at DESC, location.id DESC
),
historical_segments AS (
    SELECT
        reference_trip_id,
        EXTRACT(EPOCH FROM (
            observed_at - LAG(observed_at) OVER (
                PARTITION BY reference_trip_id, historical_trip_id
                ORDER BY station_sequence
            )
        )) / NULLIF(
            station_sequence - LAG(station_sequence) OVER (
                PARTITION BY reference_trip_id, historical_trip_id
                ORDER BY station_sequence
            ),
            0
        ) AS segment_seconds
    FROM historical_points
),
historical AS (
    SELECT reference_trip_id AS trip_id, AVG(segment_seconds) AS segment_seconds
    FROM historical_segments
    WHERE segment_seconds > 0
    GROUP BY reference_trip_id
),
arrival_estimates AS (
    SELECT DISTINCT ON (reference.trip_id, arrival.trip_id)
        reference.trip_id AS reference_trip_id,
        arrival.trip_id,
        COALESCE(
            arrival.predicted_arrival_at,
            CASE
                WHEN arrival.provider_eta_seconds IS NOT NULL
                 AND arrival.provider_eta_seconds >= 0
                THEN arrival.observed_at
                     + arrival.provider_eta_seconds * INTERVAL '1 second'
            END
        ) AS estimated_arrival_at
    FROM identity_candidates AS reference
    JOIN requested AS request ON true
    JOIN bus_vehicle_trip AS compared_trip
      ON compared_trip.route_id = reference.route_id
     AND compared_trip.direction = reference.direction
    JOIN bus_arrival_observation AS arrival
      ON arrival.trip_id = compared_trip.id
     AND arrival.stop_id = reference.boarding_stop_id
     AND arrival.observed_at <= reference.observed_at
     AND arrival.ingested_at <= request.as_of
    WHERE arrival.predicted_arrival_at IS NOT NULL
       OR arrival.provider_eta_seconds IS NOT NULL
    ORDER BY reference.trip_id, arrival.trip_id,
             arrival.observed_at DESC, arrival.id DESC
),
headway AS (
    SELECT
        own.reference_trip_id AS trip_id,
        MIN(ABS(EXTRACT(EPOCH FROM (
            compared.estimated_arrival_at - own.estimated_arrival_at
        )))) AS headway_seconds
    FROM arrival_estimates AS own
    JOIN arrival_estimates AS compared
      ON compared.reference_trip_id = own.reference_trip_id
     AND compared.trip_id <> own.trip_id
    WHERE own.trip_id = own.reference_trip_id
      AND own.estimated_arrival_at IS NOT NULL
      AND compared.estimated_arrival_at IS NOT NULL
    GROUP BY own.reference_trip_id
)
SELECT
    identity.trip_id,
    identity.route_id,
    identity.direction,
    identity.vehicle_ref,
    identity.boarding_stop_id,
    identity.current_sequence,
    identity.target_sequence,
    identity.observed_at,
    identity.ingested_at,
    CASE WHEN recent.recent_count >= 1 THEN recent.recent_1 END,
    CASE WHEN recent.recent_count >= 3 THEN recent.recent_3 END,
    CASE WHEN recent.recent_count >= 5 THEN recent.recent_5 END,
    historical.segment_seconds,
    headway.headway_seconds,
    identity.quality_flags
FROM identity_candidates AS identity
LEFT JOIN recent ON recent.trip_id = identity.trip_id
LEFT JOIN historical ON historical.trip_id = identity.trip_id
LEFT JOIN headway ON headway.trip_id = identity.trip_id
ORDER BY identity.trip_id
LIMIT 2
""".strip()


# Seat Risk never reads a later target-stop observation.  It uses only the current
# exact location snapshot, the immediately preceding observed seat value, an exact
# currently-valid capacity assertion, and as-of arrival estimates for headway.
SEAT_RISK_POINT_IN_TIME_SQL = """
WITH requested AS (
    SELECT
        %s::uuid AS route_id,
        %s::varchar AS direction,
        %s::varchar AS vehicle_token,
        %s::uuid AS boarding_stop_id,
        %s::uuid AS target_stop_id,
        %s::timestamptz AS observed_at,
        %s::timestamptz AS as_of
),
identity_candidates AS (
    SELECT
        trip.id AS trip_id,
        trip.route_id,
        trip.direction,
        vehicle.id AS vehicle_id,
        vehicle.provider_vehicle_token AS vehicle_ref,
        request.boarding_stop_id,
        request.target_stop_id,
        current_location.station_sequence AS current_sequence,
        target_stop.sequence AS target_sequence,
        current_location.observed_at,
        current_location.ingested_at,
        current_location.remaining_seats,
        current_location.crowded_code,
        current_location.quality_flags
    FROM requested AS request
    JOIN bus_vehicle AS vehicle
      ON vehicle.provider_vehicle_token = request.vehicle_token
    JOIN bus_vehicle_trip AS trip
      ON trip.vehicle_id = vehicle.id
     AND trip.route_id = request.route_id
     AND trip.direction = request.direction
     AND trip.inferred_start_at <= request.observed_at
     AND (trip.inferred_end_at IS NULL OR trip.inferred_end_at >= request.observed_at)
    JOIN transport_route AS canonical_route
      ON canonical_route.id = trip.route_id
     AND canonical_route.valid_from <= request.observed_at
     AND (canonical_route.valid_to IS NULL OR canonical_route.valid_to > request.observed_at)
    JOIN bus_location_observation AS current_location
      ON current_location.trip_id = trip.id
     AND current_location.observed_at = request.observed_at
     AND current_location.ingested_at <= request.as_of
     AND current_location.station_sequence IS NOT NULL
     AND current_location.stop_id IS NOT NULL
    JOIN route_stop AS current_route_stop
      ON current_route_stop.route_id = trip.route_id
     AND current_route_stop.direction = trip.direction
     AND current_route_stop.sequence = current_location.station_sequence
     AND current_route_stop.stop_id = current_location.stop_id
    JOIN transport_stop AS current_stop
      ON current_stop.id = current_route_stop.stop_id
     AND current_stop.valid_from <= request.observed_at
     AND (current_stop.valid_to IS NULL OR current_stop.valid_to > request.observed_at)
    JOIN route_stop AS boarding_stop
      ON boarding_stop.route_id = trip.route_id
     AND boarding_stop.direction = trip.direction
     AND boarding_stop.stop_id = request.boarding_stop_id
     AND boarding_stop.sequence >= current_location.station_sequence
    JOIN transport_stop AS boarding_canonical_stop
      ON boarding_canonical_stop.id = boarding_stop.stop_id
     AND boarding_canonical_stop.valid_from <= request.observed_at
     AND (boarding_canonical_stop.valid_to IS NULL OR boarding_canonical_stop.valid_to > request.observed_at)
    JOIN route_stop AS target_stop
      ON target_stop.route_id = trip.route_id
     AND target_stop.direction = trip.direction
     AND target_stop.stop_id = request.target_stop_id
     AND target_stop.sequence >= boarding_stop.sequence
    JOIN transport_stop AS target_canonical_stop
      ON target_canonical_stop.id = target_stop.stop_id
     AND target_canonical_stop.valid_from <= request.observed_at
     AND (target_canonical_stop.valid_to IS NULL OR target_canonical_stop.valid_to > request.observed_at)
),
seat_history AS (
    SELECT
        identity.trip_id AS reference_trip_id,
        location.remaining_seats,
        ROW_NUMBER() OVER (
            PARTITION BY identity.trip_id
            ORDER BY location.observed_at DESC, location.id DESC
        ) AS recency_rank
    FROM identity_candidates AS identity
    JOIN requested AS request ON true
    JOIN bus_location_observation AS location
      ON location.trip_id = identity.trip_id
     AND location.remaining_seats IS NOT NULL
     AND location.observed_at <= identity.observed_at
     AND location.ingested_at <= request.as_of
),
seat_delta AS (
    SELECT
        reference_trip_id AS trip_id,
        MAX(remaining_seats) FILTER (WHERE recency_rank = 1)
        - MAX(remaining_seats) FILTER (WHERE recency_rank = 2) AS recent_delta,
        COUNT(*) FILTER (WHERE recency_rank <= 2) AS evidence_count
    FROM seat_history
    GROUP BY reference_trip_id
),
capacity AS (
    SELECT
        identity.trip_id,
        COUNT(assertion.id) AS assertion_count,
        MAX(assertion.confidence) AS confidence
    FROM identity_candidates AS identity
    JOIN requested AS request ON true
    LEFT JOIN vehicle_capacity_assertion AS assertion
      ON assertion.vehicle_id = identity.vehicle_id
     AND assertion.valid_from <= identity.observed_at
     AND (assertion.valid_to IS NULL OR assertion.valid_to > identity.observed_at)
    GROUP BY identity.trip_id
),
arrival_estimates AS (
    SELECT DISTINCT ON (reference.trip_id, arrival.trip_id)
        reference.trip_id AS reference_trip_id,
        arrival.trip_id,
        COALESCE(
            arrival.predicted_arrival_at,
            CASE
                WHEN arrival.provider_eta_seconds IS NOT NULL
                 AND arrival.provider_eta_seconds >= 0
                THEN arrival.observed_at
                     + arrival.provider_eta_seconds * INTERVAL '1 second'
            END
        ) AS estimated_arrival_at
    FROM identity_candidates AS reference
    JOIN requested AS request ON true
    JOIN bus_vehicle_trip AS compared_trip
      ON compared_trip.route_id = reference.route_id
     AND compared_trip.direction = reference.direction
    JOIN bus_arrival_observation AS arrival
      ON arrival.trip_id = compared_trip.id
     AND arrival.stop_id = reference.boarding_stop_id
     AND arrival.observed_at <= reference.observed_at
     AND arrival.ingested_at <= request.as_of
    WHERE arrival.predicted_arrival_at IS NOT NULL
       OR arrival.provider_eta_seconds IS NOT NULL
    ORDER BY reference.trip_id, arrival.trip_id,
             arrival.observed_at DESC, arrival.id DESC
),
headway AS (
    SELECT
        own.reference_trip_id AS trip_id,
        MIN(ABS(EXTRACT(EPOCH FROM (
            compared.estimated_arrival_at - own.estimated_arrival_at
        )))) AS headway_seconds
    FROM arrival_estimates AS own
    JOIN arrival_estimates AS compared
      ON compared.reference_trip_id = own.reference_trip_id
     AND compared.trip_id <> own.trip_id
    WHERE own.trip_id = own.reference_trip_id
      AND own.estimated_arrival_at IS NOT NULL
      AND compared.estimated_arrival_at IS NOT NULL
    GROUP BY own.reference_trip_id
)
SELECT
    identity.trip_id,
    identity.route_id,
    identity.direction,
    identity.vehicle_ref,
    identity.boarding_stop_id,
    identity.target_stop_id,
    identity.current_sequence,
    identity.target_sequence,
    identity.observed_at,
    identity.ingested_at,
    identity.remaining_seats,
    identity.crowded_code,
    capacity.confidence,
    seat_delta.recent_delta,
    headway.headway_seconds,
    identity.quality_flags,
    capacity.assertion_count,
    seat_delta.evidence_count
FROM identity_candidates AS identity
LEFT JOIN capacity ON capacity.trip_id = identity.trip_id
LEFT JOIN seat_delta ON seat_delta.trip_id = identity.trip_id
LEFT JOIN headway ON headway.trip_id = identity.trip_id
ORDER BY identity.trip_id
LIMIT 2
""".strip()


def _uuid_parameter(value: object, field: str) -> UUID:
    if not isinstance(value, str) or value != value.strip():
        raise PostgresServingFeatureSourceError(f"{field} must be canonical UUID text")
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise PostgresServingFeatureSourceError(
            f"{field} must be canonical UUID text"
        ) from exc
    if str(parsed) != value:
        raise PostgresServingFeatureSourceError(f"{field} must be canonical UUID text")
    return parsed


def _bounded_identity(value: object, field: str, maximum: int = 128) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value.encode("utf-8")) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise PostgresServingFeatureSourceError(f"{field} is invalid")
    return value


def _aware(value: object, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise PostgresServingFeatureSourceError(f"{field} must be timezone-aware")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PostgresServingFeatureSourceError(f"{field} must be an integer >= {minimum}")
    return value


def _number(value: object, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise PostgresServingFeatureSourceError(f"{field} must be numeric")
    result = float(value)
    if not isfinite(result) or (minimum is not None and result < minimum):
        raise PostgresServingFeatureSourceError(f"{field} is outside its valid range")
    return result


def _quality_flags(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise PostgresServingFeatureSourceError(
                "quality_flags is not valid JSON"
            ) from exc
    if not isinstance(value, (list, tuple)) or len(value) > 64:
        raise PostgresServingFeatureSourceError("quality_flags must be a bounded array")
    flags: list[str] = []
    for item in value:
        if (
            not isinstance(item, str)
            or not item.strip()
            or item != item.strip()
            or len(item.encode("utf-8")) > 128
        ):
            raise PostgresServingFeatureSourceError("quality_flags contains an invalid flag")
        flags.append(item)
    if len(set(flags)) != len(flags):
        raise PostgresServingFeatureSourceError("quality_flags contains duplicates")
    return tuple(sorted(flags))


def _row_uuid(value: object, expected: UUID, field: str) -> str:
    if type(value) is not UUID or value != expected:
        raise PostgresServingFeatureSourceError(f"{field} identity mismatch")
    return str(value)


def _snapshot_rows(
    factory: ServingConnectionFactory,
    statement: str,
    parameters: tuple[Any, ...],
    timeouts: ServingSnapshotTimeouts,
    error_type: type[PostgresServingFeatureSourceError],
) -> tuple[tuple[Any, ...], ...]:
    connection: Connection | None = None
    cursor: Cursor | None = None
    try:
        connection = factory()
        cursor = connection.cursor()
        cursor.execute(_BEGIN_READ_SNAPSHOT_SQL)
        cursor.execute(
            _SET_STATEMENT_TIMEOUT_SQL,
            (f"{timeouts.statement_ms}ms",),
        )
        cursor.execute(_SET_LOCK_TIMEOUT_SQL, (f"{timeouts.lock_ms}ms",))
        cursor.execute(
            _SET_IDLE_TIMEOUT_SQL,
            (f"{timeouts.idle_in_transaction_ms}ms",),
        )
        cursor.execute(statement, parameters)
        rows = cursor.fetchall()
        if not isinstance(rows, list) or any(type(row) is not tuple for row in rows):
            raise error_type("database driver returned a non-tuple row collection")
        return tuple(rows)
    except PostgresServingFeatureSourceError:
        raise
    except Exception as exc:
        raise error_type("Routing-DB point-in-time read failed") from exc
    finally:
        if connection is not None:
            try:
                connection.rollback()
            finally:
                try:
                    if cursor is not None:
                        cursor.close()
                finally:
                    connection.close()


def _decode_eta_row(
    row: tuple[Any, ...],
    *,
    value: EtaPredictorInput,
    route_id: UUID,
    boarding_stop_id: UUID,
    as_of: datetime,
) -> EtaServingFeatureRecord | None:
    if len(row) != 15:
        raise EtaPostgresServingFeatureSourceError("ETA row schema drift")
    trip_id = row[0]
    if type(trip_id) is not UUID:
        raise EtaPostgresServingFeatureSourceError("ETA trip_id must be UUID")
    decoded_route_id = _row_uuid(row[1], route_id, "ETA route_id")
    direction = _bounded_identity(row[2], "ETA direction")
    vehicle_ref = _bounded_identity(row[3], "ETA vehicle_ref")
    decoded_boarding = _row_uuid(row[4], boarding_stop_id, "ETA boarding_stop_id")
    current_sequence = _integer(row[5], "ETA current_sequence")
    target_sequence = _integer(row[6], "ETA target_sequence")
    observed_at = _aware(row[7], "ETA observed_at")
    ingested_at = _aware(row[8], "ETA ingested_at")
    if (
        direction != value.direction
        or vehicle_ref != value.vehicle_ref
        or observed_at != value.observed_at
        or observed_at > as_of
        or ingested_at > as_of
        or target_sequence < current_sequence
    ):
        raise EtaPostgresServingFeatureSourceError(
            "ETA row identity or as-of bound mismatch"
        )
    core = row[9:14]
    if any(item is None for item in core):
        return None
    recent_1, recent_3, recent_5, historical, headway = (
        _number(item, f"ETA core[{index}]", minimum=0.0)
        for index, item in enumerate(core)
    )
    observation = NormalizedFeatureObservation(
        trip_id=str(trip_id),
        route_id=decoded_route_id,
        direction=direction,
        observed_at=observed_at,
        ingested_at=ingested_at,
        valid_at=observed_at,
        query_at=as_of,
        current_station_sequence=current_sequence,
        target_station_sequence=target_sequence,
        recent_segment_seconds_1=recent_1,
        recent_segment_seconds_3=recent_3,
        recent_segment_seconds_5=recent_5,
        historical_segment_seconds=historical,
        headway_seconds=headway,
        quality_flags=_quality_flags(row[14]),
    )
    return EtaServingFeatureRecord(vehicle_ref, decoded_boarding, observation)


def _decode_seat_row(
    row: tuple[Any, ...],
    *,
    value: SeatRiskPredictorInput,
    route_id: UUID,
    boarding_stop_id: UUID,
    target_stop_id: UUID,
    as_of: datetime,
) -> SeatRiskServingFeatureRecord | None:
    if len(row) != 18:
        raise SeatRiskPostgresServingFeatureSourceError("Seat Risk row schema drift")
    trip_id = row[0]
    if type(trip_id) is not UUID:
        raise SeatRiskPostgresServingFeatureSourceError("Seat Risk trip_id must be UUID")
    decoded_route_id = _row_uuid(row[1], route_id, "Seat Risk route_id")
    direction = _bounded_identity(row[2], "Seat Risk direction")
    vehicle_ref = _bounded_identity(row[3], "Seat Risk vehicle_ref")
    decoded_boarding = _row_uuid(
        row[4], boarding_stop_id, "Seat Risk boarding_stop_id"
    )
    decoded_target = _row_uuid(row[5], target_stop_id, "Seat Risk target_stop_id")
    current_sequence = _integer(row[6], "Seat Risk current_sequence")
    target_sequence = _integer(row[7], "Seat Risk target_sequence")
    observed_at = _aware(row[8], "Seat Risk observed_at")
    ingested_at = _aware(row[9], "Seat Risk ingested_at")
    if (
        direction != value.direction
        or vehicle_ref != value.vehicle_ref
        or observed_at != value.observed_at
        or observed_at > as_of
        or ingested_at > as_of
        or target_sequence < current_sequence
    ):
        raise SeatRiskPostgresServingFeatureSourceError(
            "Seat Risk row identity or as-of bound mismatch"
        )
    if row[10:15] == (None, None, None, None, None):
        return None
    if any(item is None for item in row[10:15]):
        return None
    current_remaining = _integer(row[10], "Seat Risk current_remaining_seats")
    current_crowded = _integer(row[11], "Seat Risk current_crowded_code")
    capacity_confidence = _number(
        row[12], "Seat Risk capacity_confidence", minimum=0.0
    )
    if capacity_confidence > 1.0:
        raise SeatRiskPostgresServingFeatureSourceError(
            "Seat Risk capacity_confidence exceeds one"
        )
    recent_delta = _number(row[13], "Seat Risk recent_seat_delta")
    headway = _number(row[14], "Seat Risk headway_seconds", minimum=0.0)
    assertion_count = _integer(row[16], "Seat Risk assertion_count")
    evidence_count = _integer(row[17], "Seat Risk seat evidence_count")
    if assertion_count != 1 or evidence_count < 2:
        return None
    if (
        value.remain_seat_observed is not None
        and current_remaining != value.remain_seat_observed
    ):
        raise SeatRiskPostgresServingFeatureSourceError(
            "Seat Risk current remaining-seat evidence mismatch"
        )
    observation = NormalizedFeatureObservation(
        trip_id=str(trip_id),
        route_id=decoded_route_id,
        direction=direction,
        observed_at=observed_at,
        ingested_at=ingested_at,
        valid_at=observed_at,
        query_at=as_of,
        current_station_sequence=current_sequence,
        target_station_sequence=target_sequence,
        headway_seconds=headway,
        current_remaining_seats=current_remaining,
        current_crowded_code=current_crowded,
        capacity_confidence=capacity_confidence,
        recent_seat_delta=recent_delta,
        quality_flags=_quality_flags(row[15]),
    )
    return SeatRiskServingFeatureRecord(
        vehicle_ref,
        decoded_boarding,
        decoded_target,
        observation,
    )


class PostgresEtaServingFeatureSource:
    """Concrete ETA source using one immutable Routing-DB snapshot per load."""

    def __init__(
        self,
        connection_factory: ServingConnectionFactory,
        *,
        timeouts: ServingSnapshotTimeouts = ServingSnapshotTimeouts(),
    ) -> None:
        if not callable(connection_factory):
            raise EtaPostgresServingFeatureSourceError(
                "ETA connection factory must be callable"
            )
        if type(timeouts) is not ServingSnapshotTimeouts:
            raise EtaPostgresServingFeatureSourceError(
                "ETA snapshot timeouts must be ServingSnapshotTimeouts"
            )
        self._connection_factory = connection_factory
        self._timeouts = timeouts

    def load(self, value: EtaPredictorInput) -> EtaServingFeatureRecord | None:
        try:
            if type(value) is not EtaPredictorInput:
                raise EtaPostgresServingFeatureSourceError("ETA input family mismatch")
            route_id = _uuid_parameter(value.route_id, "ETA route_id")
            boarding_stop_id = _uuid_parameter(
                value.boarding_stop_id, "ETA boarding_stop_id"
            )
            direction = _bounded_identity(value.direction, "ETA direction")
            vehicle_ref = _bounded_identity(value.vehicle_ref, "ETA vehicle_ref")
            observed_at = _aware(value.observed_at, "ETA observed_at")
            as_of = _aware(value.prediction_at, "ETA prediction_at")
            if observed_at > as_of:
                raise EtaPostgresServingFeatureSourceError(
                    "ETA observation cannot follow prediction_at"
                )
            rows = _snapshot_rows(
                self._connection_factory,
                ETA_POINT_IN_TIME_SQL,
                (
                    route_id,
                    direction,
                    vehicle_ref,
                    boarding_stop_id,
                    observed_at,
                    as_of,
                ),
                self._timeouts,
                EtaPostgresServingFeatureSourceError,
            )
            if len(rows) != 1:
                return None
            return _decode_eta_row(
                rows[0],
                value=value,
                route_id=route_id,
                boarding_stop_id=boarding_stop_id,
                as_of=as_of,
            )
        except Exception:
            return None


class PostgresSeatRiskServingFeatureSource:
    """Concrete Seat source that never reads a future target-stop outcome."""

    def __init__(
        self,
        connection_factory: ServingConnectionFactory,
        *,
        timeouts: ServingSnapshotTimeouts = ServingSnapshotTimeouts(),
    ) -> None:
        if not callable(connection_factory):
            raise SeatRiskPostgresServingFeatureSourceError(
                "Seat Risk connection factory must be callable"
            )
        if type(timeouts) is not ServingSnapshotTimeouts:
            raise SeatRiskPostgresServingFeatureSourceError(
                "Seat Risk snapshot timeouts must be ServingSnapshotTimeouts"
            )
        self._connection_factory = connection_factory
        self._timeouts = timeouts

    def load(
        self, value: SeatRiskPredictorInput
    ) -> SeatRiskServingFeatureRecord | None:
        try:
            if type(value) is not SeatRiskPredictorInput:
                raise SeatRiskPostgresServingFeatureSourceError(
                    "Seat Risk input family mismatch"
                )
            route_id = _uuid_parameter(value.route_id, "Seat Risk route_id")
            boarding_stop_id = _uuid_parameter(
                value.boarding_stop_id, "Seat Risk boarding_stop_id"
            )
            target_stop_id = _uuid_parameter(
                value.target_stop_id, "Seat Risk target_stop_id"
            )
            direction = _bounded_identity(value.direction, "Seat Risk direction")
            vehicle_ref = _bounded_identity(
                value.vehicle_ref, "Seat Risk vehicle_ref"
            )
            observed_at = _aware(value.observed_at, "Seat Risk observed_at")
            as_of = _aware(value.prediction_at, "Seat Risk prediction_at")
            if observed_at > as_of:
                raise SeatRiskPostgresServingFeatureSourceError(
                    "Seat Risk observation cannot follow prediction_at"
                )
            rows = _snapshot_rows(
                self._connection_factory,
                SEAT_RISK_POINT_IN_TIME_SQL,
                (
                    route_id,
                    direction,
                    vehicle_ref,
                    boarding_stop_id,
                    target_stop_id,
                    observed_at,
                    as_of,
                ),
                self._timeouts,
                SeatRiskPostgresServingFeatureSourceError,
            )
            if len(rows) != 1:
                return None
            return _decode_seat_row(
                rows[0],
                value=value,
                route_id=route_id,
                boarding_stop_id=boarding_stop_id,
                target_stop_id=target_stop_id,
                as_of=as_of,
            )
        except Exception:
            return None


__all__ = [
    "ETA_POINT_IN_TIME_SQL",
    "SEAT_RISK_POINT_IN_TIME_SQL",
    "EtaPostgresServingFeatureSourceError",
    "PostgresEtaServingFeatureSource",
    "PostgresSeatRiskServingFeatureSource",
    "PostgresServingFeatureSourceError",
    "SeatRiskPostgresServingFeatureSourceError",
    "ServingSnapshotTimeouts",
]
