"""Deterministic data-quality gates; failed periods are training-ineligible."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .dataset_foundation import DatasetInvariantError


@dataclass(frozen=True, slots=True)
class QualityObservation:
    row_id: str
    trip_id: str
    station_sequence: int | None
    observed_at: datetime
    valid_at: datetime
    ingested_at: datetime
    has_eta_target: bool
    has_seat_target: bool

    def __post_init__(self) -> None:
        if not self.row_id.strip() or not self.trip_id.strip():
            raise DatasetInvariantError("quality row identity must not be blank")
        for name in ("observed_at", "valid_at", "ingested_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise DatasetInvariantError(f"{name} must be timezone-aware")
        if self.station_sequence is not None and self.station_sequence < 0:
            raise DatasetInvariantError("station sequence must be non-negative")


@dataclass(frozen=True, slots=True)
class QualityPolicy:
    maximum_duplicate_rate: float = 0.0
    maximum_ingestion_lag_seconds: int = 300
    minimum_eta_label_coverage: float = 0.5
    minimum_seat_label_coverage: float = 0.25

    def __post_init__(self) -> None:
        rates = (
            self.maximum_duplicate_rate,
            self.minimum_eta_label_coverage,
            self.minimum_seat_label_coverage,
        )
        if any(not 0 <= value <= 1 for value in rates):
            raise DatasetInvariantError("quality rates must be in [0, 1]")
        if self.maximum_ingestion_lag_seconds < 0:
            raise DatasetInvariantError("maximum ingestion lag must be non-negative")


@dataclass(frozen=True, slots=True)
class QualityReport:
    status: str
    training_eligible: bool
    row_count: int
    duplicate_rate: float
    eta_label_coverage: float
    seat_label_coverage: float
    violations: tuple[str, ...]


def evaluate_quality(
    observations: Iterable[QualityObservation], policy: QualityPolicy = QualityPolicy()
) -> QualityReport:
    rows = tuple(observations)
    if not rows:
        return QualityReport("FAIL", False, 0, 0.0, 0.0, 0.0, ("EMPTY_DATASET",))
    duplicates = len(rows) - len({item.row_id for item in rows})
    duplicate_rate = duplicates / len(rows)
    eta_coverage = sum(item.has_eta_target for item in rows) / len(rows)
    seat_coverage = sum(item.has_seat_target for item in rows) / len(rows)
    violations: list[str] = []
    if duplicate_rate > policy.maximum_duplicate_rate:
        violations.append("DUPLICATE_RATE")
    if eta_coverage < policy.minimum_eta_label_coverage:
        violations.append("ETA_LABEL_LOW_COVERAGE")
    if seat_coverage < policy.minimum_seat_label_coverage:
        violations.append("SEAT_LABEL_LOW_COVERAGE")
    if any(item.ingested_at < item.observed_at for item in rows):
        violations.append("SOURCE_CLOCK_AHEAD")
    if any(
        (item.ingested_at - item.observed_at).total_seconds() > policy.maximum_ingestion_lag_seconds
        for item in rows
    ):
        violations.append("INGESTION_LAG")
    grouped: dict[str, list[QualityObservation]] = {}
    for item in rows:
        grouped.setdefault(item.trip_id, []).append(item)
    for trip_rows in grouped.values():
        ordered = sorted(trip_rows, key=lambda item: (item.observed_at, item.row_id))
        sequence = [item.station_sequence for item in ordered if item.station_sequence is not None]
        if any(right < left for left, right in zip(sequence, sequence[1:])):
            violations.append("STATION_SEQUENCE_REGRESSION")
            break
    normalized = tuple(sorted(set(violations)))
    return QualityReport(
        "PASS" if not normalized else "FAIL", not normalized, len(rows),
        duplicate_rate, eta_coverage, seat_coverage, normalized,
    )
