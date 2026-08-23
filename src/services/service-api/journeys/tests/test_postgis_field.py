from __future__ import annotations

import importlib
import struct
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from journeys.models import WGS84PointField


class WGS84PointFieldTests(SimpleTestCase):
    def setUp(self) -> None:
        self.field = WGS84PointField()
        self.postgresql = SimpleNamespace(vendor="postgresql")

    def test_postgis_ewkt_is_restored_as_a_public_coordinate(self) -> None:
        value = self.field.from_db_value(
            "SRID=4326;POINT(127.05 37.29)",
            None,
            self.postgresql,
        )
        self.assertEqual(value, {"lon": 127.05, "lat": 37.29})

    def test_psycopg_text_and_binary_ewkb_are_restored(self) -> None:
        ewkb = struct.pack("<BIIdd", 1, 0x20000001, 4326, 127.05, 37.29)
        for value in (ewkb, memoryview(ewkb), ewkb.hex(), f"\\x{ewkb.hex()}"):
            with self.subTest(representation=type(value).__name__):
                self.assertEqual(
                    self.field.from_db_value(value, None, self.postgresql),
                    {"lon": 127.05, "lat": 37.29},
                )

    def test_non_wgs84_or_non_finite_database_values_are_rejected(self) -> None:
        wrong_srid = struct.pack("<BIIdd", 1, 0x20000001, 3857, 127.05, 37.29)
        for value in (wrong_srid, "SRID=3857;POINT(127.05 37.29)", "POINT(nan 37.29)"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.field.from_db_value(value, None, self.postgresql)

    def test_initial_migration_enables_postgis_only_on_postgresql(self) -> None:
        migration = importlib.import_module("journeys.migrations.0001_initial")

        class SchemaEditor:
            def __init__(self, vendor: str) -> None:
                self.connection = SimpleNamespace(vendor=vendor)
                self.statements: list[str] = []

            def execute(self, statement: str) -> None:
                self.statements.append(statement)

        postgresql = SchemaEditor("postgresql")
        sqlite = SchemaEditor("sqlite")
        migration.ensure_postgis(None, postgresql)
        migration.ensure_postgis(None, sqlite)

        self.assertEqual(postgresql.statements, ["CREATE EXTENSION IF NOT EXISTS postgis"])
        self.assertEqual(sqlite.statements, [])
