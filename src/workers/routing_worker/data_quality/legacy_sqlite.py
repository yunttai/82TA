"""Packaged read-only legacy SQLite audit and idempotent import planning.

The module deliberately does not know about Django or a destination database.  It
produces immutable evidence and normalized import records which a repository adapter
can upsert transactionally.  This keeps legacy inspection offline-verifiable and
prevents an audit command from mutating the source snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Mapping, Protocol


class LegacyAuditError(ValueError):
    pass


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise LegacyAuditError(f"unsafe SQLite identifier: {value!r}")
    return f'"{value}"'


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class LegacyTableSpec:
    table: str
    primary_key: str
    observed_at_column: str | None = None
    route_column: str | None = None
    direction_column: str | None = None
    remaining_seats_column: str | None = None
    required_columns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value in (
            self.table,
            self.primary_key,
            self.observed_at_column,
            self.route_column,
            self.direction_column,
            self.remaining_seats_column,
            *self.required_columns,
        ):
            if value is not None:
                _identifier(value)


@dataclass(frozen=True, slots=True)
class LegacyTableAudit:
    table: str
    columns: tuple[tuple[str, str, bool], ...]
    row_count: int
    min_observed_at: str | None
    max_observed_at: str | None
    distinct_routes: int | None
    distinct_directions: int | None
    duplicate_primary_keys: int
    missing_required_values: int
    invalid_remaining_seats: int | None
    invalid_observed_at: int | None


@dataclass(frozen=True, slots=True)
class LegacyInventory:
    source_path: str
    source_sha256: str
    sqlite_user_version: int
    tables: tuple[LegacyTableAudit, ...]
    total_rows: int


def _read_only_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise LegacyAuditError("legacy SQLite source must be an existing file")
    uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise LegacyAuditError("cannot open legacy SQLite source read-only") from exc
    connection.row_factory = sqlite3.Row
    return connection


def audit_legacy_sqlite(path: Path, specs: Iterable[LegacyTableSpec]) -> LegacyInventory:
    """Inventory a fixed SQLite snapshot without running source-provided SQL."""

    requested = tuple(specs)
    if not requested:
        raise LegacyAuditError("at least one legacy table specification is required")
    digest = file_sha256(path)
    audits: list[LegacyTableAudit] = []
    connection = _read_only_connection(path)
    try:
        actual_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        for spec in requested:
            if spec.table not in actual_tables:
                raise LegacyAuditError(f"required legacy table is absent: {spec.table}")
            table_sql = _identifier(spec.table)
            columns_raw = connection.execute(f"PRAGMA table_info({table_sql})").fetchall()
            column_names = {str(row[1]) for row in columns_raw}
            referenced = {
                spec.primary_key,
                *(name for name in (
                    spec.observed_at_column,
                    spec.route_column,
                    spec.direction_column,
                    spec.remaining_seats_column,
                ) if name is not None),
                *spec.required_columns,
            }
            missing_columns = sorted(referenced - column_names)
            if missing_columns:
                raise LegacyAuditError(
                    f"legacy table {spec.table} is missing columns: {missing_columns}"
                )
            columns = tuple(
                (str(row[1]), str(row[2] or ""), bool(row[3])) for row in columns_raw
            )
            row_count = int(connection.execute(f"SELECT COUNT(*) FROM {table_sql}").fetchone()[0])
            primary_sql = _identifier(spec.primary_key)
            duplicate_keys = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM (SELECT {primary_sql} FROM {table_sql} "
                    f"GROUP BY {primary_sql} HAVING COUNT(*) > 1)"
                ).fetchone()[0]
            )
            if spec.required_columns:
                null_predicate = " OR ".join(
                    f"{_identifier(name)} IS NULL" for name in spec.required_columns
                )
                missing_required = int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {table_sql} WHERE {null_predicate}"
                    ).fetchone()[0]
                )
            else:
                missing_required = 0

            def scalar_count(column: str | None) -> int | None:
                if column is None:
                    return None
                return int(
                    connection.execute(
                        f"SELECT COUNT(DISTINCT {_identifier(column)}) FROM {table_sql}"
                    ).fetchone()[0]
                )

            minimum: str | None = None
            maximum: str | None = None
            invalid_observed_at: int | None = None
            if spec.observed_at_column is not None:
                observed_sql = _identifier(spec.observed_at_column)
                row = connection.execute(
                    f"SELECT MIN({observed_sql}), MAX({observed_sql}) FROM {table_sql}"
                ).fetchone()
                minimum = None if row[0] is None else str(row[0])
                maximum = None if row[1] is None else str(row[1])
                invalid_observed_at = 0
                for observed_row in connection.execute(
                    f"SELECT {observed_sql} FROM {table_sql} WHERE {observed_sql} IS NOT NULL"
                ):
                    try:
                        parsed = datetime.fromisoformat(str(observed_row[0]).replace("Z", "+00:00"))
                        if parsed.tzinfo is None or parsed.utcoffset() is None:
                            raise ValueError("naive timestamp")
                    except ValueError:
                        invalid_observed_at += 1
            invalid_seats: int | None = None
            if spec.remaining_seats_column is not None:
                seat_sql = _identifier(spec.remaining_seats_column)
                invalid_seats = int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {table_sql} WHERE {seat_sql} < 0"
                    ).fetchone()[0]
                )
            audits.append(
                LegacyTableAudit(
                    table=spec.table,
                    columns=columns,
                    row_count=row_count,
                    min_observed_at=minimum,
                    max_observed_at=maximum,
                    distinct_routes=scalar_count(spec.route_column),
                    distinct_directions=scalar_count(spec.direction_column),
                    duplicate_primary_keys=duplicate_keys,
                    missing_required_values=missing_required,
                    invalid_remaining_seats=invalid_seats,
                    invalid_observed_at=invalid_observed_at,
                )
            )
    finally:
        connection.close()
    if file_sha256(path) != digest:
        raise LegacyAuditError("legacy SQLite source changed during audit")
    return LegacyInventory(
        source_path=path.name,
        source_sha256=digest,
        sqlite_user_version=user_version,
        tables=tuple(audits),
        total_rows=sum(item.row_count for item in audits),
    )


@dataclass(frozen=True, slots=True)
class LegacyImportRecord:
    lineage_key: str
    source_sha256: str
    source_table: str
    source_primary_key: str
    normalized_json: str


def make_import_record(
    *,
    source_sha256: str,
    source_table: str,
    source_primary_key: object,
    normalized: Mapping[str, Any],
) -> LegacyImportRecord:
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise LegacyAuditError("source_sha256 must be lowercase SHA-256")
    _identifier(source_table)
    primary_key = str(source_primary_key)
    if not primary_key:
        raise LegacyAuditError("source primary key must not be blank")
    try:
        normalized_json = json.dumps(
            normalized, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise LegacyAuditError("normalized import record must be canonical JSON") from exc
    lineage = sha256(
        f"{source_sha256}\x1f{source_table}\x1f{primary_key}".encode("utf-8")
    ).hexdigest()
    return LegacyImportRecord(
        lineage_key=lineage,
        source_sha256=source_sha256,
        source_table=source_table,
        source_primary_key=primary_key,
        normalized_json=normalized_json,
    )


class LegacyImportSink(Protocol):
    def insert_if_absent(self, record: LegacyImportRecord) -> bool:
        """Atomically insert on lineage uniqueness; return whether inserted."""
        ...


@dataclass(frozen=True, slots=True)
class LegacyImportResult:
    inserted: int
    duplicate: int


def import_idempotently(
    records: Iterable[LegacyImportRecord], sink: LegacyImportSink
) -> LegacyImportResult:
    inserted = 0
    duplicate = 0
    seen: set[str] = set()
    for record in records:
        if record.lineage_key in seen:
            duplicate += 1
            continue
        seen.add(record.lineage_key)
        if sink.insert_if_absent(record):
            inserted += 1
        else:
            duplicate += 1
    return LegacyImportResult(inserted=inserted, duplicate=duplicate)
