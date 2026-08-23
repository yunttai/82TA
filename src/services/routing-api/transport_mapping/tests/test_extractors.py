from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from provider_core.canonical import (
    CanonicalLeg,
    CanonicalStop,
    Coordinate,
    DataOrigin,
    MoneyRange,
    TimeEstimate,
    TransitDescriptor,
    TravelMode,
)

from transport_mapping.extractors import (
    CanonicalIdentityExtractionError,
    TransitProvider,
    extract_provider_identity,
)


def _leg(
    *,
    direction: str | None = "상행",
    terminal_names: tuple[str, ...] = ("남부차고지", "서울도심"),
    stop_boarding_sequence: int | None = 10,
    descriptor_boarding_sequence: int | None = 10,
) -> CanonicalLeg:
    start = datetime(2026, 8, 23, 8, 0, tzinfo=timezone(timedelta(hours=9)))
    boarding = CanonicalStop(
        "기점환승센터",
        Coordinate(127.05, 37.28),
        "provider-board",
        stop_boarding_sequence,
    )
    alighting = CanonicalStop(
        "도착역동편",
        Coordinate(127.11, 37.39),
        "provider-alight",
        20,
    )
    return CanonicalLeg(
        leg_id="canonical-bus-leg",
        sequence=0,
        mode=TravelMode.BUS,
        from_stop=boarding,
        to_stop=alighting,
        duration=TimeEstimate(600, 720, DataOrigin.PROVIDER_ESTIMATE),
        distance_meters=10_000,
        fare=MoneyRange(2_800, 2_800, 2_800, DataOrigin.PROVIDER_ESTIMATE),
        expected_start_at=start,
        expected_end_at=start + timedelta(seconds=600),
        transit=TransitDescriptor(
            route_label="M5107",
            external_route_id="provider-route",
            route_type="직행좌석",
            direction=direction,
            branch_id="A",
            boarding_sequence=descriptor_boarding_sequence,
            alighting_sequence=20,
            terminal_names=terminal_names,
            live_vehicle_observed=None,
        ),
        geometry=(boarding.coordinate, alighting.coordinate),
    )


@pytest.mark.parametrize(
    ("provider_code", "expected"),
    [
        ("Kakao Maps Transit", TransitProvider.KAKAO),
        ("tmap", TransitProvider.TMAP),
        ("ODSAY_TRANSIT", TransitProvider.ODSAY),
    ],
)
def test_provider_specific_extractors_accept_only_canonical_bus_values(
    provider_code: str,
    expected: TransitProvider,
) -> None:
    identity = extract_provider_identity(provider_code, _leg())

    assert identity.provider == expected.value
    assert identity.route_name == "M5107"
    assert identity.boarding.sequence == 10
    assert identity.alighting.sequence == 20
    assert identity.origin_terminal == "남부차고지"
    assert identity.destination_terminal == "서울도심"
    assert len(identity.geometry) == 2


def test_extractor_rejects_conflicting_canonical_sequences() -> None:
    with pytest.raises(CanonicalIdentityExtractionError, match="conflicting"):
        extract_provider_identity(
            "KAKAO_TRANSIT",
            _leg(stop_boarding_sequence=9, descriptor_boarding_sequence=10),
        )


def test_extractor_does_not_guess_orientation_from_one_terminal() -> None:
    identity = extract_provider_identity(
        "TMAP_TRANSIT",
        _leg(terminal_names=("서울도심",)),
    )
    assert identity.origin_terminal is None
    assert identity.destination_terminal is None


def test_extractor_rejects_non_bus_and_unknown_provider() -> None:
    bus = _leg()
    walk = CanonicalLeg(
        leg_id="walk",
        sequence=0,
        mode=TravelMode.WALK,
        from_stop=bus.from_stop,
        to_stop=bus.to_stop,
        duration=bus.duration,
        distance_meters=100,
        fare=MoneyRange(0, 0, 0, DataOrigin.PROVIDER_ESTIMATE),
    )
    with pytest.raises(CanonicalIdentityExtractionError, match="BUS"):
        extract_provider_identity("KAKAO_TRANSIT", walk)
    with pytest.raises(CanonicalIdentityExtractionError, match="unsupported"):
        extract_provider_identity("UNVERIFIED_PROVIDER", bus)
