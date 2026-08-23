from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

WORKERS = Path(__file__).parents[1]
if str(WORKERS) not in sys.path:
    sys.path.insert(0, str(WORKERS))

from legacy_sqlite import make_import_record
from data_quality_postgres_adapter import PostgresLegacyImportSink, PostgresQualitySink
from quality_gate import QualityReport


UTC = timezone.utc
NOW = datetime(2026, 8, 23, tzinfo=UTC)


class RecordingRepository:
    source_id = "11111111-1111-1111-1111-111111111111"

    def __init__(self):
        self.lineages = []
        self.quality = []

    def insert_legacy_lineage(self, record, *, imported_at):
        self.lineages.append((record, imported_at))
        return True

    def write_quality_run(self, record):
        self.quality.append(record)
        return "run-id"


class PostgresDataQualityAdapterTest(unittest.TestCase):
    def test_legacy_sink_uses_injected_clock_and_atomic_repository_primitive(self):
        repository = RecordingRepository()
        sink = PostgresLegacyImportSink(repository, clock=lambda: NOW)
        record = make_import_record(
            source_sha256="a" * 64, source_table="arrival", source_primary_key=1,
            normalized={"remainingSeats": None},
        )
        self.assertTrue(sink.insert_if_absent(record))
        self.assertEqual(repository.lineages[0][1], NOW)

    def test_quality_sink_persists_training_eligibility_and_null_coverage_truth(self):
        repository = RecordingRepository()
        sink = PostgresQualitySink(repository, clock=lambda: NOW)
        report = QualityReport(
            "FAIL", False, 10, 0.0, 0.8, 0.0, ("SEAT_LABEL_LOW_COVERAGE",),
        )
        self.assertEqual(sink.persist(dataset_version="seat-v1", report=report), "run-id")
        stored = repository.quality[0]
        self.assertFalse(stored.metrics["trainingEligible"])
        self.assertEqual(stored.metrics["seatLabelCoverage"], 0.0)


if __name__ == "__main__":
    unittest.main()
