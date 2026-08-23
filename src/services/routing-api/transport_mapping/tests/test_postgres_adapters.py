from __future__ import annotations

from collections import deque
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Mapping, Sequence
from uuid import uuid4

import pytest

from transport_mapping.catalog import (
    CatalogQuery,
    DisabledGitsRoadLinkIdentityRepository,
    GitsRoadLinkIdentityRecord,
    InMemoryGbisCatalogRepository,
    InMemoryGitsRoadLinkIdentityRepository,
    enrich_selected_gits_road_link_target,
)
from transport_mapping.fingerprint import candidate_fingerprint, mapping_cache_key
from transport_mapping.models import (
    CanonicalRouteCandidate,
    Coordinate,
    GITS_ROAD_LINK_IDENTITY_VERSION,
    GitsRoadLinkIdentity,
    MappingGrade,
    PersistedMappingResolution,
    ProviderMappingInput,
    ValidityWindow,
    gits_road_link_identity_fingerprint,
    gits_road_link_normalized_identity,
)
from transport_mapping.pipeline import (
    AcceptedHighMappingEntry,
    InMemoryMappingReviewRepository,
    TransportMappingPipeline,
)
from transport_mapping.postgres import (
    MappingDatabaseError,
    MappingDatabaseUnavailable,
    MappingQueryBoundsError,
    MappingRowSchemaError,
    PostgisGbisCatalogRepository,
    PostgisGitsRoadLinkIdentityRepository,
    PostgresAcceptedHighMappingRepository,
    PostgresMappingReviewRepository,
)
from transport_mapping.scoring import map_candidate


class RecordingSession:
    def __init__(self, database: "RecordingDatabase") -> None:
        self.database = database

    def fetch_all(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> Sequence[Mapping[str, object]]:
        self.database.calls.append(("fetch_all", statement, parameters))
        if self.database.fetch_all_batches:
            return self.database.fetch_all_batches.popleft()
        return self.database.fetch_all_rows

    def fetch_one(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> Mapping[str, object] | None:
        self.database.calls.append(("fetch_one", statement, parameters))
        if not self.database.fetch_one_rows:
            raise AssertionError("unexpected fetch_one call")
        return self.database.fetch_one_rows.popleft()

    def execute(self, statement: str, parameters: tuple[object, ...]) -> int:
        self.database.calls.append(("execute", statement, parameters))
        return 1


class RecordingTransaction(AbstractContextManager[RecordingSession]):
    def __init__(self, database: "RecordingDatabase", read_only: bool) -> None:
        self.database = database
        self.read_only = read_only

    def __enter__(self) -> RecordingSession:
        self.database.transactions.append((self.read_only, "BEGIN"))
        return RecordingSession(self.database)

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.database.transactions.append(
            (self.read_only, "ROLLBACK" if exc_type is not None else "COMMIT")
        )


class RecordingDatabase:
    def __init__(
        self,
        *,
        fetch_all_rows: Sequence[Mapping[str, object]] = (),
        fetch_all_batches: Sequence[Sequence[Mapping[str, object]]] = (),
        fetch_one_rows: Sequence[Mapping[str, object] | None] = (),
    ) -> None:
        self.fetch_all_rows = fetch_all_rows
        self.fetch_all_batches = deque(fetch_all_batches)
        self.fetch_one_rows = deque(fetch_one_rows)
        self.calls: list[tuple[str, str, tuple[object, ...]]] = []
        self.transactions: list[tuple[bool, str]] = []

    def transaction(self, *, read_only: bool) -> RecordingTransaction:
        return RecordingTransaction(self, read_only)


def _catalog_row(
    evaluated_at: datetime,
    *,
    route_id: str | None = None,
    direction: str = "상행",
) -> dict[str, object]:
    return {
        "route_id": route_id or str(uuid4()),
        "route_name": "M5107",
        "route_type": "직행좌석",
        "boarding_stop_id": str(uuid4()),
        "boarding_name": "광교중앙역",
        "boarding_lon": Decimal("127.05102"),
        "boarding_lat": Decimal("37.28801"),
        "boarding_sequence": 102,
        "alighting_stop_id": str(uuid4()),
        "alighting_name": "판교역동편",
        "alighting_lon": Decimal("127.11202"),
        "alighting_lat": Decimal("37.39501"),
        "alighting_sequence": 115,
        "direction": direction,
        "branch_id": "A",
        "origin_terminal": "경기대 후문",
        "destination_terminal": "서울역 정류장",
        "turning_point_sequence": None,
        "valid_from": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "valid_to": None,
        "geometry_similarity": Decimal("0.98"),
        "live_vehicle_exists": True,
    }


def _gits_identity_row(
    evaluated_at: datetime,
    route_id: str,
    *,
    direction: str = "상행",
    links: tuple[str, ...] = ("GITS-LINK-001", "GITS-LINK-002"),
) -> dict[str, object]:
    normalized_identities = [
        gits_road_link_normalized_identity(link) for link in links
    ]
    provider_fingerprints = [
        gits_road_link_identity_fingerprint(link) for link in links
    ]
    return {
        "route_id": route_id,
        "direction": direction,
        "matching_count": len(links),
        "unique_count": len(links),
        "identity_version": GITS_ROAD_LINK_IDENTITY_VERSION,
        "identity_version_count": 1,
        "mapping_version": "gits-road-link-map.v1",
        "mapping_version_count": 1,
        "identity_json_valid": True,
        "fingerprints_valid": True,
        "effective_valid_from": evaluated_at.replace(month=1, day=1),
        "effective_valid_to": None,
        "link_external_ids": list(links),
        "normalized_identities": normalized_identities,
        "provider_fingerprints": provider_fingerprints,
    }


def _review_entry(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
):
    review = InMemoryMappingReviewRepository()
    candidate = replace(
        exact_candidate,
        route_id=str(uuid4()),
        direction=None,
    )
    pipeline = TransportMappingPipeline(
        InMemoryGbisCatalogRepository((candidate,)),
        review,
    )
    source = replace(provider_input, direction=None)

    class _Mode:
        value = "BUS"

    class _Descriptor:
        route_label = source.route_name
        external_route_id = source.external_route_id
        route_type = source.route_type
        direction = None
        branch_id = source.branch_id
        boarding_sequence = source.boarding.sequence
        alighting_sequence = source.alighting.sequence
        terminal_names = (source.origin_terminal, source.destination_terminal)
        live_vehicle_observed = None

    class _Stop:
        def __init__(self, stop) -> None:
            self.name = stop.name
            self.coordinate = stop.coordinate
            self.external_id = stop.external_id
            self.sequence = stop.sequence

    class _Leg:
        mode = _Mode()
        from_stop = _Stop(source.boarding)
        to_stop = _Stop(source.alighting)
        transit = _Descriptor()
        geometry = source.geometry

    result = pipeline.map_bus_leg(
        "KAKAO_TRANSIT",
        _Leg(),
        evaluated_at=evaluated_at,
    )
    assert result.selected is not None and result.selected.grade is MappingGrade.MEDIUM
    assert len(review.entries) == 1
    return review.entries[0]


def _accepted_entry(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> AcceptedHighMappingEntry:
    candidate = replace(exact_candidate, route_id=str(uuid4()))
    mapping = map_candidate(
        provider_input,
        candidate,
        evaluated_at=evaluated_at,
    )
    assert mapping.grade is MappingGrade.HIGH
    cache_key = mapping_cache_key(
        mapping.provider_fingerprint,
        mapping.candidate_fingerprint,
        mapping.mapping_version,
        valid_from=mapping.validity.valid_from,
        valid_to=mapping.validity.valid_to,
    )
    return AcceptedHighMappingEntry(
        cache_key=cache_key,
        provider=provider_input.provider,
        provider_external_id=provider_input.external_route_id or mapping.provider_fingerprint,
        provider_identity={"provider": provider_input.provider},
        signal_breakdown={"availableWeight": mapping.breakdown.available_weight},
        direction=provider_input.direction,
        mapping=mapping,
        accepted_at=evaluated_at,
    )


def test_postgis_catalog_uses_parameterized_bounded_server_query(
    provider_input: ProviderMappingInput,
    evaluated_at: datetime,
) -> None:
    row = _catalog_row(evaluated_at)
    database = RecordingDatabase(fetch_all_rows=(row,))
    repository = PostgisGbisCatalogRepository(
        database,
        statement_timeout_ms=650,
        max_rows=8,
        max_radius_meters=600,
    )

    candidates = repository.find_candidates(
        CatalogQuery(provider_input, evaluated_at, max_candidates=5, stop_radius_meters=500)
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.route_id == row["route_id"]
    assert candidate.boarding.sequence < candidate.alighting.sequence
    assert candidate.geometry_similarity_to_provider == 0.98
    assert candidate.traffic_link_external_ids == ()
    assert database.transactions == [(True, "BEGIN"), (True, "COMMIT")]
    timeout_call, query_call = database.calls[:2]
    assert timeout_call[0] == "execute"
    assert timeout_call[2] == ("650ms",)
    assert query_call[0] == "fetch_all"
    statement, parameters = query_call[1], query_call[2]
    assert statement.count("%s") == len(parameters)
    assert "ST_DWithin(bs.coordinate" in statement
    assert "ars.sequence > brs.sequence" in statement
    assert "turningPoint" in statement
    assert "ORDER BY" in statement and "LIMIT" in statement
    assert "M5107" not in statement
    assert parameters[-2:] == (500, 5)


def test_postgis_catalog_bounds_geometry_and_rejects_radius_overrun(
    provider_input: ProviderMappingInput,
    evaluated_at: datetime,
) -> None:
    geometry = tuple(
        Coordinate(127.0 + index / 10_000, 37.0 + index / 10_000)
        for index in range(100)
    )
    source = replace(provider_input, geometry=geometry)
    database = RecordingDatabase()
    repository = PostgisGbisCatalogRepository(database, max_radius_meters=500)

    repository.find_candidates(
        CatalogQuery(source, evaluated_at, stop_radius_meters=500)
    )
    wkt = next(call for call in database.calls if call[0] == "fetch_all")[2][13]
    assert isinstance(wkt, str)
    assert wkt.count(",") <= 63

    with pytest.raises(MappingQueryBoundsError, match="radius"):
        repository.find_candidates(
            CatalogQuery(source, evaluated_at, stop_radius_meters=501)
        )


def test_postgis_catalog_rejects_schema_drift_and_rolls_back(
    evaluated_at: datetime,
    provider_input: ProviderMappingInput,
) -> None:
    drifted = _catalog_row(evaluated_at)
    drifted["unexpected_raw_provider_field"] = "must-not-cross"
    database = RecordingDatabase(fetch_all_rows=(drifted,))
    repository = PostgisGbisCatalogRepository(database)

    with pytest.raises(MappingRowSchemaError, match="schema drift"):
        repository.find_candidates(CatalogQuery(provider_input, evaluated_at))

    # Row decoding occurs after the read-only transaction has committed; no write
    # is possible and drift still fails closed before a candidate is returned.
    assert database.transactions[-1] == (True, "COMMIT")


def test_postgis_candidate_keeps_high_and_direction_blocker_policy(
    evaluated_at: datetime,
    provider_input: ProviderMappingInput,
) -> None:
    high_db = RecordingDatabase(fetch_all_rows=(_catalog_row(evaluated_at),))
    high_candidate = PostgisGbisCatalogRepository(high_db).find_candidates(
        CatalogQuery(provider_input, evaluated_at)
    )[0]
    high = map_candidate(provider_input, high_candidate, evaluated_at=evaluated_at)
    assert high.grade is MappingGrade.HIGH
    assert high.allows_bus_intelligence is True

    low_db = RecordingDatabase(
        fetch_all_rows=(_catalog_row(evaluated_at, direction="하행"),)
    )
    low_candidate = PostgisGbisCatalogRepository(low_db).find_candidates(
        CatalogQuery(provider_input, evaluated_at)
    )[0]
    low = map_candidate(provider_input, low_candidate, evaluated_at=evaluated_at)
    assert "OPPOSITE_DIRECTION" in low.blockers
    assert low.grade is MappingGrade.LOW
    assert low.allows_bus_intelligence is False


def test_in_memory_gits_identity_is_versioned_current_and_deterministic(
    evaluated_at: datetime,
) -> None:
    route_id = str(uuid4())
    identity = GitsRoadLinkIdentity(
        link_external_ids=("GITS-LINK-001", "GITS-LINK-002"),
        mapping_version="gits-road-link-map.v1",
        validity=ValidityWindow(datetime(2026, 1, 1, tzinfo=timezone.utc)),
    )
    repository = InMemoryGitsRoadLinkIdentityRepository(
        (GitsRoadLinkIdentityRecord(route_id, "상행", identity),)
    )

    found = repository.find_for_targets(((route_id, "상행"),), as_of=evaluated_at)

    assert found[(route_id, "상행")] == identity
    assert identity.identity_version == GITS_ROAD_LINK_IDENTITY_VERSION
    assert identity.link_external_ids == tuple(sorted(identity.link_external_ids))
    assert repository.find_for_targets(
        ((route_id, "하행"),), as_of=evaluated_at
    ) == {}


def test_candidate_defaults_to_no_traffic_identity_and_never_infers_from_geometry(
    exact_candidate: CanonicalRouteCandidate,
) -> None:
    candidate = replace(
        exact_candidate,
        geometry=(Coordinate(127.0, 37.0), Coordinate(127.2, 37.2)),
    )

    assert candidate.gits_road_link_identity is None
    assert candidate.traffic_link_external_ids == ()
    enriched = replace(
        candidate,
        gits_road_link_identity=GitsRoadLinkIdentity(
            link_external_ids=("GITS-LINK-001",),
            mapping_version="gits-road-link-map.v1",
            validity=candidate.validity,
        ),
    )
    assert candidate_fingerprint(enriched) == candidate_fingerprint(candidate)


def test_postgis_gits_identity_requires_documented_current_accepted_high_mapping(
    evaluated_at: datetime,
) -> None:
    route_id = str(uuid4())
    row = _gits_identity_row(evaluated_at, route_id)
    database = RecordingDatabase(fetch_all_batches=((row,),))
    repository = PostgisGitsRoadLinkIdentityRepository(
        database,
        statement_timeout_ms=325,
        max_links=4,
    )

    found = repository.find_for_targets(((route_id, "상행"),), as_of=evaluated_at)

    identity = found[(route_id, "상행")]
    assert identity.link_external_ids == ("GITS-LINK-001", "GITS-LINK-002")
    assert identity.mapping_version == "gits-road-link-map.v1"
    assert identity.validity.contains(evaluated_at)
    assert database.transactions == [(True, "BEGIN"), (True, "COMMIT")]
    timeout_call, query_call = database.calls
    assert timeout_call[2] == ("325ms",)
    statement, parameters = query_call[1], query_call[2]
    assert statement.count("%s") == len(parameters)
    assert "p.code = 'GITS'" in statement
    assert "pe.entity_type = 'ROAD_LINK'" in statement
    assert "operation_state.documentation_state = 'DOCUMENTED'" in statement
    assert "em.grade = 'HIGH'" in statement
    assert "em.signal_breakdown->>'reviewDisposition' = 'AUTO_ACCEPT'" in statement
    assert "em.direction = request.direction" in statement
    assert "valid_from <= %s" in statement
    assert 'link_external_id COLLATE "C"' in statement
    assert "pe.normalized_identity = jsonb_build_object" in statement
    assert "'identityVersion'" in statement and "'linkExternalId'" in statement
    assert "ST_DWithin" not in statement and "geometry" not in statement.casefold()
    assert parameters[1] == GITS_ROAD_LINK_IDENTITY_VERSION
    assert parameters[-3:] == (5, 5, 5)
    assert "GITS-LINK" not in parameters[0]


@pytest.mark.parametrize(
    "mutation",
    (
        {"unique_count": 1},
        {"matching_count": 513, "unique_count": 513},
        {"identity_version_count": 2},
        {"mapping_version_count": 2},
        {"identity_json_valid": False},
        {"fingerprints_valid": False},
        {"identity_version": "gits-road-link-identity.v2"},
        {"link_external_ids": ["GITS-LINK-002", "GITS-LINK-001"]},
        {"link_external_ids": [" GITS-LINK-001", "GITS-LINK-002"]},
        {"link_external_ids": ["GITS-LINK-001", 7]},
        {
            "normalized_identities": [
                {
                    "identityVersion": GITS_ROAD_LINK_IDENTITY_VERSION,
                    "linkExternalId": "GITS-LINK-001",
                    "bbox": [127.0, 37.0, 128.0, 38.0],
                },
                {
                    "identityVersion": GITS_ROAD_LINK_IDENTITY_VERSION,
                    "linkExternalId": "GITS-LINK-002",
                },
            ]
        },
        {"provider_fingerprints": ["0" * 64, "0" * 64]},
    ),
)
def test_postgis_gits_identity_rejects_duplicate_oversized_ambiguous_or_malformed_data(
    evaluated_at: datetime,
    mutation: Mapping[str, object],
) -> None:
    route_id = str(uuid4())
    row = _gits_identity_row(evaluated_at, route_id)
    row.update(mutation)
    repository = PostgisGitsRoadLinkIdentityRepository(
        RecordingDatabase(fetch_all_batches=((row,),))
    )

    assert repository.find_for_targets(
        ((route_id, "상행"),), as_of=evaluated_at
    ) == {}


def test_postgis_gits_identity_rejects_stale_and_schema_drift(
    evaluated_at: datetime,
) -> None:
    route_id = str(uuid4())
    stale = _gits_identity_row(evaluated_at, route_id)
    stale["effective_valid_from"] = evaluated_at + timedelta(seconds=1)
    repository = PostgisGitsRoadLinkIdentityRepository(
        RecordingDatabase(fetch_all_batches=((stale,),))
    )
    assert repository.find_for_targets(
        ((route_id, "상행"),), as_of=evaluated_at
    ) == {}

    drifted = _gits_identity_row(evaluated_at, route_id)
    drifted["unexpected"] = "raw"
    repository = PostgisGitsRoadLinkIdentityRepository(
        RecordingDatabase(fetch_all_batches=((drifted,),))
    )
    with pytest.raises(MappingRowSchemaError, match="schema drift"):
        repository.find_for_targets(((route_id, "상행"),), as_of=evaluated_at)


def test_postgis_catalog_attaches_only_repository_gits_identity_and_fails_closed(
    provider_input: ProviderMappingInput,
    evaluated_at: datetime,
) -> None:
    route_id = str(uuid4())
    catalog_row = _catalog_row(evaluated_at, route_id=route_id)
    identity_row = _gits_identity_row(evaluated_at, route_id)
    database = RecordingDatabase(
        fetch_all_batches=((catalog_row,), (identity_row,))
    )

    identity_repository = PostgisGitsRoadLinkIdentityRepository(database)
    candidate = PostgisGbisCatalogRepository(
        database,
        gits_identity_repository=identity_repository,
    ).find_candidates(
        CatalogQuery(provider_input, evaluated_at)
    )[0]

    assert candidate.traffic_link_external_ids == (
        "GITS-LINK-001",
        "GITS-LINK-002",
    )
    assert candidate.gits_road_link_identity is not None
    assert candidate.gits_road_link_identity.validity.contains(evaluated_at)

    drifted = dict(identity_row)
    drifted["unexpected"] = "schema drift"
    database = RecordingDatabase(fetch_all_batches=((catalog_row,), (drifted,)))
    candidate = PostgisGbisCatalogRepository(
        database,
        gits_identity_repository=PostgisGitsRoadLinkIdentityRepository(database),
    ).find_candidates(
        CatalogQuery(provider_input, evaluated_at)
    )[0]
    assert candidate.traffic_link_external_ids == ()


def test_disabled_repository_is_zero_io_and_selected_enricher_queries_once(
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    route_id = str(uuid4())
    target = replace(exact_candidate, route_id=route_id, direction="상행")
    disabled = DisabledGitsRoadLinkIdentityRepository()
    assert disabled.find_for_targets(((route_id, "상행"),), as_of=evaluated_at) == {}

    database = RecordingDatabase(
        fetch_all_batches=((_gits_identity_row(evaluated_at, route_id),),)
    )
    resolution = PersistedMappingResolution(
        entity_mapping_id=str(uuid4()),
        provider_fingerprint="a" * 64,
        candidate_fingerprint="b" * 64,
        route_id=route_id,
        mapping_version="0.1.0-planned",
        validity=target.validity,
        accepted_at=evaluated_at,
    )

    enriched = enrich_selected_gits_road_link_target(
        target,
        resolution,
        PostgisGitsRoadLinkIdentityRepository(database),
        as_of=evaluated_at,
    )

    assert enriched.traffic_link_external_ids == (
        "GITS-LINK-001",
        "GITS-LINK-002",
    )
    assert sum(call[0] == "fetch_all" for call in database.calls) == 1

    mismatched = replace(resolution, route_id=str(uuid4()))
    unchanged = enrich_selected_gits_road_link_target(
        target,
        mismatched,
        PostgisGitsRoadLinkIdentityRepository(database),
        as_of=evaluated_at,
    )
    assert unchanged.traffic_link_external_ids == ()
    assert sum(call[0] == "fetch_all" for call in database.calls) == 1


def test_postgis_gits_identity_enforces_target_and_timeout_bounds(
    evaluated_at: datetime,
) -> None:
    route_id = str(uuid4())
    with pytest.raises(MappingQueryBoundsError, match="timeout"):
        PostgisGitsRoadLinkIdentityRepository(
            RecordingDatabase(), statement_timeout_ms=701
        )
    repository = PostgisGitsRoadLinkIdentityRepository(RecordingDatabase())
    with pytest.raises(MappingQueryBoundsError, match="unique"):
        repository.find_for_targets(
            ((route_id, "상행"), (route_id, "상행")), as_of=evaluated_at
        )
    with pytest.raises(MappingQueryBoundsError, match="UUID"):
        repository.find_for_targets((("caller-route", "상행"),), as_of=evaluated_at)


def test_database_adapters_fail_closed_without_connection() -> None:
    with pytest.raises(MappingDatabaseUnavailable, match="no fallback"):
        PostgisGbisCatalogRepository(None)
    with pytest.raises(MappingDatabaseUnavailable, match="no fallback"):
        PostgresMappingReviewRepository(None)
    with pytest.raises(MappingDatabaseUnavailable, match="no fallback"):
        PostgresAcceptedHighMappingRepository(None)
    with pytest.raises(MappingDatabaseUnavailable, match="no fallback"):
        PostgisGitsRoadLinkIdentityRepository(None)


def test_accepted_high_persistence_is_atomic_current_and_idempotent(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    entry = _accepted_entry(provider_input, exact_candidate, evaluated_at)
    provider_id = str(uuid4())
    provider_entity_id = str(uuid4())
    mapping_id = str(uuid4())
    database = RecordingDatabase(
        fetch_one_rows=(
            {"id": provider_id},
            {"id": entry.mapping.route_id},
            {"id": provider_entity_id},
            None,
            {"id": mapping_id},
            {"id": provider_id},
            {"id": entry.mapping.route_id},
            {"id": provider_entity_id},
            {"id": mapping_id},
        )
    )
    repository = PostgresAcceptedHighMappingRepository(
        database,
        statement_timeout_ms=500,
    )

    first = repository.persist(entry)
    second = repository.persist(entry)

    assert first == second
    assert first.entity_mapping_id == mapping_id
    assert first.grade is MappingGrade.HIGH
    assert first.validity.contains(first.accepted_at)
    assert database.transactions == [
        (False, "BEGIN"),
        (False, "COMMIT"),
        (False, "BEGIN"),
        (False, "COMMIT"),
    ]
    statements = [statement for _, statement, _ in database.calls]
    assert sum("INSERT INTO entity_mapping" in statement for statement in statements) == 1
    assert not any("INSERT INTO mapping_review" in statement for statement in statements)
    lookup = next(
        call
        for call in database.calls
        if "reviewDisposition" in call[1] and "FROM entity_mapping" in call[1]
    )
    assert "grade = 'HIGH'" in lookup[1]
    assert "valid_from <=" in lookup[1]
    assert lookup[2][-4:] == (
        entry.cache_key,
        entry.mapping.provider_fingerprint,
        entry.mapping.candidate_fingerprint,
        entry.mapping.mapping_version,
    )
    insert = next(call for call in database.calls if "INSERT INTO entity_mapping" in call[1])
    assert insert[2][5] == "HIGH"
    assert '"reviewDisposition":"AUTO_ACCEPT"' in insert[2][6]
    assert entry.mapping.provider_fingerprint in insert[2][6]
    for operation, statement, parameters in database.calls:
        if operation in {"fetch_one", "fetch_all"}:
            assert statement.count("%s") == len(parameters)


def test_accepted_repository_rejects_non_high_before_database_call(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    entry = _accepted_entry(provider_input, exact_candidate, evaluated_at)

    with pytest.raises(ValueError, match="HIGH"):
        replace(entry, mapping=replace(entry.mapping, grade=MappingGrade.MEDIUM))

    with pytest.raises(ValueError, match="current"):
        replace(
            entry,
            accepted_at=entry.mapping.validity.valid_from.replace(year=2025),
        )


def test_accepted_high_schema_drift_rolls_back_without_exposing_id(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    entry = _accepted_entry(provider_input, exact_candidate, evaluated_at)
    database = RecordingDatabase(
        fetch_one_rows=({"id": str(uuid4()), "unexpected": "drift"},)
    )
    repository = PostgresAcceptedHighMappingRepository(database)

    with pytest.raises(MappingRowSchemaError, match="schema drift"):
        repository.persist(entry)

    assert database.transactions == [(False, "BEGIN"), (False, "ROLLBACK")]
    assert not any("INSERT INTO entity_mapping" in call[1] for call in database.calls)


def test_review_enqueue_is_atomic_parameterized_and_idempotent(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    entry = _review_entry(provider_input, exact_candidate, evaluated_at)
    provider_id = str(uuid4())
    provider_entity_id = str(uuid4())
    mapping_id = str(uuid4())
    review_id = str(uuid4())
    database = RecordingDatabase(
        fetch_one_rows=(
            {"id": provider_id},
            {"id": entry.route_id},
            {"id": provider_entity_id},
            None,
            {"id": mapping_id},
            None,
            {"id": review_id},
            {"id": provider_id},
            {"id": entry.route_id},
            {"id": provider_entity_id},
            {"id": mapping_id},
            {"id": review_id},
        )
    )
    repository = PostgresMappingReviewRepository(database, statement_timeout_ms=500)

    first = repository.enqueue(entry)
    second = repository.enqueue(entry)

    assert first == review_id == second
    assert database.transactions == [
        (False, "BEGIN"),
        (False, "COMMIT"),
        (False, "BEGIN"),
        (False, "COMMIT"),
    ]
    statements = [statement for _, statement, _ in database.calls]
    assert any("pg_advisory_xact_lock" in statement for statement in statements)
    assert any("INSERT INTO provider_entity" in statement for statement in statements)
    assert any("INSERT INTO entity_mapping" in statement for statement in statements)
    assert sum("INSERT INTO mapping_review" in statement for statement in statements) == 1
    assert all(entry.cache_key not in statement for statement in statements)
    for operation, statement, parameters in database.calls:
        if operation in {"fetch_one", "fetch_all"}:
            assert statement.count("%s") == len(parameters)
    json_parameters = [
        parameter
        for _, _, parameters in database.calls
        for parameter in parameters
        if isinstance(parameter, str) and parameter.startswith("{")
    ]
    assert any(entry.cache_key in value for value in json_parameters)


def test_review_state_is_append_only_in_one_transaction(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    mapping_id = str(uuid4())
    state_id = str(uuid4())
    database = RecordingDatabase(
        fetch_one_rows=(
            {"entity_mapping_id": mapping_id},
            {"id": state_id},
        )
    )
    repository = PostgresMappingReviewRepository(database)

    result = repository.append_review_state(
        str(uuid4()),
        status="approved",
        reviewer="routing-reviewer-role",
        note="independently corroborated",
        reviewed_at=evaluated_at,
    )

    assert result == state_id
    assert database.transactions == [(False, "BEGIN"), (False, "COMMIT")]
    insert = next(call for call in database.calls if "INSERT INTO mapping_review" in call[1])
    assert insert[2][2:5] == (
        "APPROVED",
        "routing-reviewer-role",
        "independently corroborated",
    )


def test_review_schema_drift_rolls_back_atomic_transaction(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    entry = _review_entry(provider_input, exact_candidate, evaluated_at)
    database = RecordingDatabase(
        fetch_one_rows=({"id": str(uuid4()), "unexpected": "drift"},)
    )
    repository = PostgresMappingReviewRepository(database)

    with pytest.raises(MappingRowSchemaError, match="schema drift"):
        repository.enqueue(entry)

    assert database.transactions[-1] == (False, "ROLLBACK")


def test_review_rejects_high_mapping_and_unbounded_timeout(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    entry = _review_entry(provider_input, exact_candidate, evaluated_at)
    repository = PostgresMappingReviewRepository(RecordingDatabase())
    with pytest.raises(MappingDatabaseError, match="HIGH"):
        repository.enqueue(replace(entry, grade=MappingGrade.HIGH))
    with pytest.raises(MappingQueryBoundsError, match="timeout"):
        PostgresMappingReviewRepository(RecordingDatabase(), statement_timeout_ms=701)
