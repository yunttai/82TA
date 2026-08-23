from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from bus_intelligence_core import EtaPredictorInput, SeatRiskPredictorInput

from routing_worker.feature_builder import build_eta_features, build_seat_features
from routing_worker.postgres_serving import (
    ETA_POINT_IN_TIME_SQL,
    SEAT_RISK_POINT_IN_TIME_SQL,
    PostgresEtaServingFeatureSource,
    PostgresSeatRiskServingFeatureSource,
)
from routing_worker.serving_features import (
    DurableEtaCompleteVectorBuilder,
    DurableSeatRiskCompleteVectorBuilder,
)


UTC = timezone.utc
AS_OF = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
OBSERVED_AT = AS_OF - timedelta(seconds=10)
TRIP_ID = UUID("00000000-0000-0000-0000-000000000011")
ROUTE_ID = UUID("00000000-0000-0000-0000-000000000012")
BOARDING_ID = UUID("00000000-0000-0000-0000-000000000013")
TARGET_ID = UUID("00000000-0000-0000-0000-000000000014")


class FakeCursor:
    def __init__(
        self,
        rows: list[tuple[Any, ...]],
        *,
        fail_on_select: bool = False,
        fail_on_close: bool = False,
    ) -> None:
        self.rows = rows
        self.fail_on_select = fail_on_select
        self.fail_on_close = fail_on_close
        self.executions: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False
        self.rowcount = 0

    def execute(
        self, operation: str, parameters: tuple[Any, ...] = ()
    ) -> None:
        self.executions.append((operation, parameters))
        if self.fail_on_select and operation in {
            ETA_POINT_IN_TIME_SQL,
            SEAT_RISK_POINT_IN_TIME_SQL,
        }:
            raise TimeoutError("statement timeout")

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def close(self) -> None:
        self.closed = True
        if self.fail_on_close:
            raise RuntimeError("cursor close failed")


class FakeConnection:
    def __init__(
        self,
        cursor: FakeCursor,
        *,
        fail_on_rollback: bool = False,
        fail_on_close: bool = False,
    ) -> None:
        self.fake_cursor = cursor
        self.autocommit = True
        self.fail_on_rollback = fail_on_rollback
        self.fail_on_close = fail_on_close
        self.rollbacks = 0
        self.commits = 0
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.fake_cursor

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1
        if self.fail_on_rollback:
            raise RuntimeError("rollback failed")

    def close(self) -> None:
        self.closed = True
        if self.fail_on_close:
            raise RuntimeError("connection close failed")


class Factory:
    def __init__(
        self,
        rows: list[tuple[Any, ...]],
        *,
        fail: bool = False,
        fail_on_rollback: bool = False,
        fail_on_cursor_close: bool = False,
        fail_on_connection_close: bool = False,
    ) -> None:
        self.cursor = FakeCursor(
            rows,
            fail_on_select=fail,
            fail_on_close=fail_on_cursor_close,
        )
        self.connection = FakeConnection(
            self.cursor,
            fail_on_rollback=fail_on_rollback,
            fail_on_close=fail_on_connection_close,
        )
        self.calls = 0

    def __call__(self) -> FakeConnection:
        self.calls += 1
        return self.connection


def eta_input(**changes: object) -> EtaPredictorInput:
    values: dict[str, object] = {
        "vehicle_ref": "vehicle-token",
        "route_id": str(ROUTE_ID),
        "direction": "UP",
        "boarding_stop_id": str(BOARDING_ID),
        "observed_at": OBSERVED_AT,
        "remain_seat_observed": 0,
        "prediction_at": AS_OF,
    }
    values.update(changes)
    return EtaPredictorInput(**values)  # type: ignore[arg-type]


def seat_input(**changes: object) -> SeatRiskPredictorInput:
    values: dict[str, object] = {
        "vehicle_ref": "vehicle-token",
        "route_id": str(ROUTE_ID),
        "direction": "UP",
        "boarding_stop_id": str(BOARDING_ID),
        "target_stop_id": str(TARGET_ID),
        "observed_at": OBSERVED_AT,
        "prediction_at": AS_OF,
        "remain_seat_observed": 0,
    }
    values.update(changes)
    return SeatRiskPredictorInput(**values)  # type: ignore[arg-type]


def eta_row(**changes: object) -> tuple[Any, ...]:
    values: list[Any] = [
        TRIP_ID,
        ROUTE_ID,
        "UP",
        "vehicle-token",
        BOARDING_ID,
        4,
        8,
        OBSERVED_AT,
        OBSERVED_AT + timedelta(seconds=1),
        Decimal("0"),
        Decimal("180"),
        Decimal("300"),
        Decimal("64"),
        Decimal("0"),
        [],
    ]
    indexes = {
        "trip_id": 0,
        "route_id": 1,
        "direction": 2,
        "vehicle_ref": 3,
        "boarding_stop_id": 4,
        "observed_at": 7,
        "ingested_at": 8,
        "recent_1": 9,
        "quality_flags": 14,
    }
    for key, value in changes.items():
        values[indexes[key]] = value
    return tuple(values)


def seat_row(**changes: object) -> tuple[Any, ...]:
    values: list[Any] = [
        TRIP_ID,
        ROUTE_ID,
        "UP",
        "vehicle-token",
        BOARDING_ID,
        TARGET_ID,
        4,
        8,
        OBSERVED_AT,
        OBSERVED_AT + timedelta(seconds=1),
        0,
        0,
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        [],
        1,
        2,
    ]
    indexes = {
        "trip_id": 0,
        "route_id": 1,
        "direction": 2,
        "vehicle_ref": 3,
        "boarding_stop_id": 4,
        "target_stop_id": 5,
        "observed_at": 8,
        "ingested_at": 9,
        "remaining": 10,
        "crowded": 11,
        "confidence": 12,
        "delta": 13,
        "headway": 14,
        "quality_flags": 15,
        "assertion_count": 16,
        "evidence_count": 17,
    }
    for key, value in changes.items():
        values[indexes[key]] = value
    return tuple(values)


def assert_snapshot_closed(factory: Factory) -> None:
    assert factory.calls == 1
    assert factory.connection.rollbacks == 1
    assert factory.connection.commits == 0
    assert factory.cursor.closed
    assert factory.connection.closed
    statements = [statement for statement, _ in factory.cursor.executions]
    assert statements[0] == "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert "statement_timeout" in statements[1]
    assert "lock_timeout" in statements[2]
    assert "idle_in_transaction_session_timeout" in statements[3]


def test_eta_source_uses_one_fixed_snapshot_preserves_zero_and_matches_training() -> None:
    factory = Factory([eta_row()])
    source = PostgresEtaServingFeatureSource(factory)
    request = eta_input()

    record = source.load(request)

    assert record is not None
    assert record.observation.recent_segment_seconds_1 == 0.0
    assert record.observation.headway_seconds == 0.0
    statement, parameters = factory.cursor.executions[-1]
    assert statement is ETA_POINT_IN_TIME_SQL
    assert parameters == (
        ROUTE_ID,
        "UP",
        "vehicle-token",
        BOARDING_ID,
        OBSERVED_AT,
        AS_OF,
    )
    assert_snapshot_closed(factory)
    serving = DurableEtaCompleteVectorBuilder(source)
    second_factory = Factory([eta_row()])
    serving = DurableEtaCompleteVectorBuilder(
        PostgresEtaServingFeatureSource(second_factory)
    )
    served = serving.build(request)
    trained = build_eta_features(record.observation)
    assert served is not None
    assert (served.schema_version, served.feature_names, served.values, served.missing_flags) == (
        trained.schema_version,
        trained.feature_names,
        trained.values,
        trained.missing_flags,
    )


def test_seat_source_is_separate_preserves_zero_and_matches_training() -> None:
    factory = Factory([seat_row()])
    source = PostgresSeatRiskServingFeatureSource(factory)
    request = seat_input()

    record = source.load(request)

    assert record is not None
    assert record.observation.current_remaining_seats == 0
    assert record.observation.current_crowded_code == 0
    assert record.observation.capacity_confidence == 0.0
    assert record.observation.recent_seat_delta == 0.0
    assert record.observation.headway_seconds == 0.0
    statement, parameters = factory.cursor.executions[-1]
    assert statement is SEAT_RISK_POINT_IN_TIME_SQL
    assert parameters == (
        ROUTE_ID,
        "UP",
        "vehicle-token",
        BOARDING_ID,
        TARGET_ID,
        OBSERVED_AT,
        AS_OF,
    )
    assert ETA_POINT_IN_TIME_SQL not in [item[0] for item in factory.cursor.executions]
    assert "target_stop_id" in SEAT_RISK_POINT_IN_TIME_SQL
    assert "future_target" not in SEAT_RISK_POINT_IN_TIME_SQL
    assert_snapshot_closed(factory)

    second_factory = Factory([seat_row()])
    served = DurableSeatRiskCompleteVectorBuilder(
        PostgresSeatRiskServingFeatureSource(second_factory)
    ).build(request)
    trained = build_seat_features(record.observation)
    assert served is not None
    assert (served.schema_version, served.feature_names, served.values, served.missing_flags) == (
        trained.schema_version,
        trained.feature_names,
        trained.values,
        trained.missing_flags,
    )


def test_point_in_time_sql_requires_canonical_route_and_stop_validity() -> None:
    for statement in (ETA_POINT_IN_TIME_SQL, SEAT_RISK_POINT_IN_TIME_SQL):
        assert "JOIN transport_route AS canonical_route" in statement
        assert "canonical_route.valid_from <= request.observed_at" in statement
        assert "canonical_route.valid_to > request.observed_at" in statement
        assert "JOIN transport_stop AS current_stop" in statement
        assert "current_stop.valid_from <= request.observed_at" in statement
        assert "current_stop.valid_to > request.observed_at" in statement
        assert "JOIN transport_stop AS boarding_canonical_stop" in statement
        assert "boarding_canonical_stop.valid_from <= request.observed_at" in statement
        assert "boarding_canonical_stop.valid_to > request.observed_at" in statement
    assert "JOIN transport_stop AS target_canonical_stop" in SEAT_RISK_POINT_IN_TIME_SQL
    assert "target_canonical_stop.valid_from <= request.observed_at" in SEAT_RISK_POINT_IN_TIME_SQL
    assert "target_canonical_stop.valid_to > request.observed_at" in SEAT_RISK_POINT_IN_TIME_SQL


def test_invalid_uuid_is_rejected_before_database_io() -> None:
    eta_factory = Factory([eta_row()])
    seat_factory = Factory([seat_row()])
    assert PostgresEtaServingFeatureSource(eta_factory).load(
        eta_input(route_id="route-1")
    ) is None
    assert PostgresSeatRiskServingFeatureSource(seat_factory).load(
        seat_input(target_stop_id="target-1")
    ) is None
    assert eta_factory.calls == 0
    assert seat_factory.calls == 0


def test_timeout_and_ambiguous_identity_fail_closed_per_family() -> None:
    eta_timeout = Factory([], fail=True)
    seat_timeout = Factory([], fail=True)
    assert PostgresEtaServingFeatureSource(eta_timeout).load(eta_input()) is None
    assert PostgresSeatRiskServingFeatureSource(seat_timeout).load(seat_input()) is None
    assert_snapshot_closed(eta_timeout)
    assert_snapshot_closed(seat_timeout)

    eta_ambiguous = Factory([eta_row(), eta_row()])
    seat_ambiguous = Factory([seat_row(), seat_row()])
    assert PostgresEtaServingFeatureSource(eta_ambiguous).load(eta_input()) is None
    assert PostgresSeatRiskServingFeatureSource(seat_ambiguous).load(seat_input()) is None


def test_cleanup_failures_still_close_and_fail_closed_per_family() -> None:
    eta_factory = Factory(
        [eta_row()],
        fail_on_rollback=True,
        fail_on_cursor_close=True,
    )
    seat_factory = Factory(
        [seat_row()],
        fail_on_rollback=True,
        fail_on_connection_close=True,
    )
    assert PostgresEtaServingFeatureSource(eta_factory).load(eta_input()) is None
    assert PostgresSeatRiskServingFeatureSource(seat_factory).load(seat_input()) is None
    assert eta_factory.connection.rollbacks == 1
    assert eta_factory.cursor.closed and eta_factory.connection.closed
    assert seat_factory.connection.rollbacks == 1
    assert seat_factory.cursor.closed and seat_factory.connection.closed


def test_malformed_and_post_as_of_rows_fail_closed_without_zero_coercion() -> None:
    cases = (
        PostgresEtaServingFeatureSource(Factory([eta_row(recent_1="0")])),
        PostgresEtaServingFeatureSource(
            Factory([eta_row(observed_at=AS_OF + timedelta(seconds=1))])
        ),
        PostgresSeatRiskServingFeatureSource(Factory([seat_row(remaining=False)])),
        PostgresSeatRiskServingFeatureSource(
            Factory([seat_row(ingested_at=AS_OF + timedelta(seconds=1))])
        ),
    )
    assert cases[0].load(eta_input()) is None
    assert cases[1].load(eta_input()) is None
    assert cases[2].load(seat_input()) is None
    assert cases[3].load(seat_input()) is None


def test_missing_derived_evidence_and_capacity_ambiguity_return_none() -> None:
    assert PostgresEtaServingFeatureSource(
        Factory([eta_row(recent_1=None)])
    ).load(eta_input()) is None
    assert PostgresSeatRiskServingFeatureSource(
        Factory([seat_row(assertion_count=2)])
    ).load(seat_input()) is None
    assert PostgresSeatRiskServingFeatureSource(
        Factory([seat_row(evidence_count=1)])
    ).load(seat_input()) is None


def test_fixed_sql_has_no_dynamic_formatting_or_service_identity_tables() -> None:
    for statement in (ETA_POINT_IN_TIME_SQL, SEAT_RISK_POINT_IN_TIME_SQL):
        lowered = statement.lower()
        assert "{" not in statement and "}" not in statement
        assert "service_" not in lowered
        assert "auth_user" not in lowered
        assert "email" not in lowered
        assert "saved_place" not in lowered
        assert statement.count("%s") in {6, 7}
