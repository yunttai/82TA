"""Packaged leakage-safe label and split primitives for offline datasets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, Iterable, TypeVar


class DatasetInvariantError(ValueError):
    """Raised when dataset construction would violate a temporal invariant."""


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DatasetInvariantError(f"{field_name} must be timezone-aware")


T = TypeVar("T")


@dataclass(frozen=True)
class NullableTarget(Generic[T]):
    has_target: bool
    value: T | None
    observed_at: datetime | None

    def __post_init__(self) -> None:
        if self.has_target != (self.value is not None):
            raise DatasetInvariantError(
                "has_target must be true exactly when target value is present"
            )
        if self.has_target != (self.observed_at is not None):
            raise DatasetInvariantError(
                "target observation time must be present exactly with its value"
            )
        if self.observed_at is not None:
            _require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class TargetStopObservation:
    trip_id: str
    stop_id: str
    observed_at: datetime
    remaining_seats: int | None
    eligible: bool = True

    def __post_init__(self) -> None:
        if not self.trip_id.strip() or not self.stop_id.strip():
            raise DatasetInvariantError("trip_id and stop_id must not be blank")
        _require_aware(self.observed_at, "observed_at")
        if self.remaining_seats is not None and self.remaining_seats < 0:
            raise DatasetInvariantError("remaining_seats must be >= 0 when observed")


@dataclass(frozen=True)
class TargetStopLabels:
    eta_seconds: NullableTarget[int]
    no_seat: NullableTarget[bool]
    low_seat_le_2: NullableTarget[bool]
    low_seat_le_5: NullableTarget[bool]
    seat_ordinal_class: NullableTarget[int]

    def __post_init__(self) -> None:
        targets = (
            self.eta_seconds,
            self.no_seat,
            self.low_seat_le_2,
            self.low_seat_le_5,
            self.seat_ordinal_class,
        )
        if any(type(value) is not NullableTarget for value in targets):
            raise DatasetInvariantError("target labels must use NullableTarget")
        eta = self.eta_seconds
        if eta.has_target and (
            isinstance(eta.value, bool)
            or not isinstance(eta.value, int)
            or eta.value < 0
        ):
            raise DatasetInvariantError("ETA target must be a non-negative integer")
        seats = targets[1:]
        if len({value.has_target for value in seats}) != 1:
            raise DatasetInvariantError(
                "Seat threshold and ordinal targets must be all-present or all-missing"
            )
        if not seats[0].has_target:
            return
        if not eta.has_target:
            raise DatasetInvariantError("observed Seat targets require an ETA target")
        observed = {value.observed_at for value in seats}
        if len(observed) != 1 or eta.observed_at not in observed:
            raise DatasetInvariantError(
                "ETA, Seat threshold, and ordinal targets must share observed_at"
            )
        threshold_values = tuple(value.value for value in seats[:3])
        if any(type(value) is not bool for value in threshold_values):
            raise DatasetInvariantError("Seat threshold targets must be booleans")
        ordinal = self.seat_ordinal_class.value
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal not in range(4):
            raise DatasetInvariantError("Seat ordinal target must be an integer in 0..3")
        expected = {
            (True, True, True): 0,
            (False, True, True): 1,
            (False, False, True): 2,
            (False, False, False): 3,
        }.get(threshold_values)
        if expected is None or ordinal != expected:
            raise DatasetInvariantError(
                "Seat thresholds must be nested and exactly match the ordinal class"
            )


def _missing_target() -> NullableTarget:
    return NullableTarget(has_target=False, value=None, observed_at=None)


def build_target_stop_labels(
    *,
    trip_id: str,
    target_stop_id: str,
    feature_observed_at: datetime,
    observations: Iterable[TargetStopObservation],
) -> TargetStopLabels:
    """Build labels only from the first eligible observation after feature time."""

    _require_aware(feature_observed_at, "feature_observed_at")
    future = sorted(
        (
            item
            for item in observations
            if item.eligible
            and item.trip_id == trip_id
            and item.stop_id == target_stop_id
            and item.observed_at > feature_observed_at
        ),
        key=lambda item: item.observed_at,
    )
    if not future:
        missing = _missing_target()
        return TargetStopLabels(missing, missing, missing, missing, missing)

    target = future[0]
    eta_seconds = int((target.observed_at - feature_observed_at).total_seconds())
    eta = NullableTarget(True, eta_seconds, target.observed_at)
    if target.remaining_seats is None:
        missing = _missing_target()
        return TargetStopLabels(eta, missing, missing, missing, missing)

    remaining = target.remaining_seats
    return TargetStopLabels(
        eta_seconds=eta,
        no_seat=NullableTarget(True, remaining == 0, target.observed_at),
        low_seat_le_2=NullableTarget(True, remaining <= 2, target.observed_at),
        low_seat_le_5=NullableTarget(True, remaining <= 5, target.observed_at),
        seat_ordinal_class=NullableTarget(
            True,
            0 if remaining == 0 else 1 if remaining <= 2 else 2 if remaining <= 5 else 3,
            target.observed_at,
        ),
    )


@dataclass(frozen=True)
class DatasetSample:
    row_id: str
    trip_id: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.row_id.strip() or not self.trip_id.strip():
            raise DatasetInvariantError("row_id and trip_id must not be blank")
        _require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class TemporalTripSplit:
    train: tuple[str, ...]
    validation: tuple[str, ...]
    test: tuple[str, ...]
    purged: tuple[str, ...]
    purged_trip_ids: tuple[str, ...]


def temporal_trip_group_split(
    samples: Iterable[DatasetSample],
    *,
    validation_start: datetime,
    test_start: datetime,
) -> TemporalTripSplit:
    """Split by time while purging any trip that crosses a split boundary."""

    _require_aware(validation_start, "validation_start")
    _require_aware(test_start, "test_start")
    if validation_start >= test_start:
        raise DatasetInvariantError("validation_start must precede test_start")

    grouped: dict[str, list[DatasetSample]] = {}
    seen_rows: set[str] = set()
    for sample in samples:
        if sample.row_id in seen_rows:
            raise DatasetInvariantError(f"duplicate row_id: {sample.row_id}")
        seen_rows.add(sample.row_id)
        grouped.setdefault(sample.trip_id, []).append(sample)

    buckets: dict[str, list[str]] = {
        "train": [],
        "validation": [],
        "test": [],
        "purged": [],
    }
    purged_trips: list[str] = []

    def window(observed_at: datetime) -> str:
        if observed_at < validation_start:
            return "train"
        if observed_at < test_start:
            return "validation"
        return "test"

    for trip_id in sorted(grouped):
        group = sorted(grouped[trip_id], key=lambda item: (item.observed_at, item.row_id))
        windows = {window(item.observed_at) for item in group}
        bucket = next(iter(windows)) if len(windows) == 1 else "purged"
        buckets[bucket].extend(item.row_id for item in group)
        if bucket == "purged":
            purged_trips.append(trip_id)

    return TemporalTripSplit(
        train=tuple(buckets["train"]),
        validation=tuple(buckets["validation"]),
        test=tuple(buckets["test"]),
        purged=tuple(buckets["purged"]),
        purged_trip_ids=tuple(purged_trips),
    )
