"""Durable sinks for legacy lineage, reconciliation and quality reports."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from .legacy_sqlite import LegacyImportRecord
from .quality_gate import QualityReport
from ..repositories import (
    PostgresWorkerRepository,
    QualityRunRecord,
)


class PostgresLegacyImportSink:
    def __init__(
        self, repository: PostgresWorkerRepository, *, clock: Callable[[], datetime],
    ) -> None:
        self.repository = repository
        self.clock = clock

    def insert_if_absent(self, record: LegacyImportRecord) -> bool:
        return self.repository.insert_legacy_lineage(record, imported_at=self.clock())


class PostgresQualitySink:
    def __init__(
        self, repository: PostgresWorkerRepository, *, clock: Callable[[], datetime],
    ) -> None:
        self.repository = repository
        self.clock = clock

    def persist(self, *, dataset_version: str, report: QualityReport) -> str:
        at = self.clock()
        return self.repository.write_quality_run(
            QualityRunRecord(
                source_id=self.repository.source_id,
                dataset_version=dataset_version,
                status=report.status,
                metrics={
                    "duplicateRate": report.duplicate_rate,
                    "etaLabelCoverage": report.eta_label_coverage,
                    "rowCount": report.row_count,
                    "seatLabelCoverage": report.seat_label_coverage,
                    "trainingEligible": report.training_eligible,
                },
                violations=report.violations,
                started_at=at,
                finished_at=at,
            )
        )
