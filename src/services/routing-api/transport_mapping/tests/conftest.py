from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

# provider-core is an optional Routing API integration dependency.  Source-tree
# component tests add its package root explicitly; an installed deployment gets
# the same import through the ``integration`` extra.
_SRC = Path(__file__).resolve().parents[4]
_PROVIDER_CORE = _SRC / "packages" / "provider-core"
if str(_PROVIDER_CORE) not in sys.path:
    sys.path.insert(0, str(_PROVIDER_CORE))

from transport_mapping.models import (
    CanonicalRouteCandidate,
    Coordinate,
    ProviderMappingInput,
    StopSignal,
    ValidityWindow,
)


@pytest.fixture
def evaluated_at() -> datetime:
    return datetime(2026, 8, 23, 3, 0, tzinfo=timezone.utc)


@pytest.fixture
def provider_input() -> ProviderMappingInput:
    return ProviderMappingInput(
        provider="KAKAO_TRANSIT",
        external_route_id="kakao-m5107",
        route_name="M5107번 버스",
        route_type="직행좌석",
        boarding=StopSignal(
            name="광교중앙역 정류장",
            coordinate=Coordinate(lon=127.0510, lat=37.2880),
            external_id="k-board",
            sequence=12,
        ),
        alighting=StopSignal(
            name="판교역동편 버스정류장",
            coordinate=Coordinate(lon=127.1120, lat=37.3950),
            external_id="k-alight",
            sequence=25,
        ),
        direction="상행선",
        branch_id="A",
        origin_terminal="경기대후문",
        destination_terminal="서울역",
    )


@pytest.fixture
def exact_candidate(evaluated_at: datetime) -> CanonicalRouteCandidate:
    return CanonicalRouteCandidate(
        route_id="gbis-route-m5107-a",
        route_name="M5107",
        route_type="직행좌석",
        boarding=StopSignal(
            name="광교중앙역",
            coordinate=Coordinate(lon=127.05102, lat=37.28801),
            external_id="gbis-board",
            sequence=102,
        ),
        alighting=StopSignal(
            name="판교역동편",
            coordinate=Coordinate(lon=127.11202, lat=37.39501),
            external_id="gbis-alight",
            sequence=115,
        ),
        direction="상행",
        branch_id="a",
        origin_terminal="경기대 후문",
        destination_terminal="서울역 정류장",
        validity=ValidityWindow(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        geometry_similarity_to_provider=0.98,
        live_vehicle_exists=True,
    )
