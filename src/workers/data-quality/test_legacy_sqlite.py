from pathlib import Path
import sqlite3
import tempfile
import unittest

from legacy_sqlite import (
    LegacyAuditError,
    LegacyTableSpec,
    audit_legacy_sqlite,
    import_idempotently,
    make_import_record,
)


class MemorySink:
    def __init__(self) -> None:
        self.records = {}

    def insert_if_absent(self, record):
        if record.lineage_key in self.records:
            return False
        self.records[record.lineage_key] = record
        return True


class LegacySqliteTest(unittest.TestCase):
    def make_database(self, root: Path) -> Path:
        path = root / "legacy.sqlite"
        db = sqlite3.connect(path)
        try:
            db.execute("PRAGMA user_version=7")
            db.execute(
                "CREATE TABLE arrival (row_id TEXT, route TEXT, direction TEXT, "
                "observed_at TEXT, remaining_seats INTEGER)"
            )
            db.executemany(
                "INSERT INTO arrival VALUES (?, ?, ?, ?, ?)",
                [
                    ("1", "R1", "UP", "2026-08-01T01:00:00+00:00", 3),
                    ("2", "R1", "UP", "2026-08-02T01:00:00+00:00", 0),
                    ("2", "R2", None, "2026-08-03T01:00:00+00:00", -1),
                ],
            )
            db.commit()
        finally:
            db.close()
        return path

    def test_inventory_captures_hash_schema_rows_dates_coverage_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_database(Path(directory))
            before = path.read_bytes()
            inventory = audit_legacy_sqlite(
                path,
                [LegacyTableSpec(
                    "arrival", "row_id", "observed_at", "route", "direction",
                    "remaining_seats", ("route", "direction", "observed_at"),
                )],
            )
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(inventory.sqlite_user_version, 7)
            self.assertEqual(inventory.total_rows, 3)
            table = inventory.tables[0]
            self.assertEqual(table.row_count, 3)
            self.assertEqual(table.distinct_routes, 2)
            self.assertEqual(table.distinct_directions, 1)
            self.assertEqual(table.duplicate_primary_keys, 1)
            self.assertEqual(table.missing_required_values, 1)
            self.assertEqual(table.invalid_remaining_seats, 1)
            self.assertEqual(table.invalid_observed_at, 0)
            self.assertEqual(table.min_observed_at, "2026-08-01T01:00:00+00:00")

    def test_schema_mismatch_and_identifier_injection_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_database(Path(directory))
            with self.assertRaises(LegacyAuditError):
                audit_legacy_sqlite(path, [LegacyTableSpec("arrival", "absent")])
            with self.assertRaises(LegacyAuditError):
                LegacyTableSpec("arrival; DROP TABLE arrival", "row_id")

    def test_import_lineage_is_idempotent(self):
        record = make_import_record(
            source_sha256="a" * 64,
            source_table="arrival",
            source_primary_key=1,
            normalized={"trip_id": "trip-1", "remaining_seats": None},
        )
        sink = MemorySink()
        first = import_idempotently((record, record), sink)
        second = import_idempotently((record,), sink)
        self.assertEqual((first.inserted, first.duplicate), (1, 1))
        self.assertEqual((second.inserted, second.duplicate), (0, 1))


if __name__ == "__main__":
    unittest.main()
