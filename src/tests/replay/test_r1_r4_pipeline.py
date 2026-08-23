from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from provider_core import foundation_capability_registry
from routing_domain.replay_fixtures import build_r1_r4_scenarios

from replay_support import build_integrated_application, invoke_integrated_private_api


SCENARIOS = build_r1_r4_scenarios()


@pytest.mark.parametrize(
    ("scenario", "corridor"),
    tuple(
        zip(
            SCENARIOS,
            (
                "MYONGJI_TO_PANGYO",
                "PANGYO_TO_MYONGJI",
                "GWANGGYO_TO_PANGYO",
                "PANGYO_TO_GWANGGYO",
            ),
        )
    ),
    ids=("R1", "R2", "R3", "R4"),
)
def test_r1_r4_fixture_chain_is_deterministic_and_semantically_valid(
    scenario: object,
    corridor: str,
) -> None:
    assert scenario.corridor == corridor
    first_api = invoke_integrated_private_api(scenario, scenario.replay_id)
    second_api = invoke_integrated_private_api(scenario, scenario.replay_id)

    assert first_api.status_code == 200
    assert first_api.body == second_api.body
    assert first_api.body["status"] == "PARTIAL"
    # The normalized GBIS fixture is intentionally for a different route/time.
    # It must not be reused as future target-stop evidence.
    assert first_api.body["modelVersions"] == []
    assert "BUS_DATA_UNAVAILABLE" in first_api.body["warningCodes"]

    routes = first_api.body["routes"]
    generated_at = datetime.fromisoformat(first_api.body["generatedAt"])
    returned = {route["routeId"] for route in routes}
    recommendations = first_api.body["recommendations"]
    assert set(recommendations) == {"fastest", "stable", "efficient", "publicTransitOnly"}
    assert all(value is not None and value in returned for value in recommendations.values())
    assert set(first_api.body["paretoRouteIds"]) <= returned
    assert recommendations["publicTransitOnly"] in returned
    public = next(route for route in routes if route["routeId"] == recommendations["publicTransitOnly"])
    assert public["taxiCost"]["upper"] == 0

    for route in routes:
        assert route["totalDuration"]["p90Seconds"] >= route["totalDuration"]["p50Seconds"]
        assert route["taxiCost"]["upper"] <= scenario.constraints.taxi_budget_krw
        taxi_upper_sum = sum(
            leg["fare"]["upper"] for leg in route["legs"] if leg["mode"] == "TAXI"
        )
        assert taxi_upper_sum == route["taxiCost"]["upper"]
        assert route["dominance"]["onParetoFrontier"] == (
            route["routeId"] in first_api.body["paretoRouteIds"]
        )
        provenance = [
            *route["provenance"],
            *(item for leg in route["legs"] for item in leg["provenance"]),
        ]
        assert provenance
        for item in provenance:
            received_at = datetime.fromisoformat(item["receivedAt"])
            assert received_at <= generated_at
            if item["observedAt"] is not None:
                assert datetime.fromisoformat(item["observedAt"]) <= received_at
            if item["ageSeconds"] is not None:
                assert item["ageSeconds"] >= 0
        for leg in route["legs"]:
            assert leg["duration"]["p90Seconds"] >= leg["duration"]["p50Seconds"]
            assert datetime.fromisoformat(leg["expectedStartAt"]) <= datetime.fromisoformat(
                leg["expectedEndAt"]
            )
            if leg["mode"] == "BUS":
                assert leg["busIntelligence"] is None
        for previous, current in zip(route["legs"], route["legs"][1:]):
            assert datetime.fromisoformat(current["expectedStartAt"]) >= datetime.fromisoformat(
                previous["expectedEndAt"]
            )

    fixture_status = next(
        item
        for item in first_api.body["providerStatus"]
        if item["provider"] == "SANITIZED_TRANSIT_FIXTURE"
    )
    assert fixture_status["status"] == "OK"
    live_statuses = [
        item
        for item in first_api.body["providerStatus"]
        if item["provider"] != "SANITIZED_TRANSIT_FIXTURE"
        and not item["provider"].startswith("FIXTURE::")
    ]
    assert live_statuses and all(item["status"] == "DISABLED" for item in live_statuses)


def test_fixture_availability_does_not_promote_live_provider_capability() -> None:
    registry = foundation_capability_registry()
    assert registry.all()
    assert all(capability.fixture_only for capability in registry.all())
    assert all(not capability.enabled for capability in registry.all())
    assert all(capability.key_verification_state.value == "UNVERIFIED" for capability in registry.all())
    assert all(capability.production_state.value == "UNAPPROVED" for capability in registry.all())

    application, _ = build_integrated_application("R1")
    capabilities = application.capabilities()
    assert capabilities["models"] == []
    assert capabilities["features"]["busEtaModel"] is False
    assert capabilities["features"]["busSeatRisk"] is False
    assert application.version()["models"] == []


def test_lower_budget_removes_over_upper_budget_route_without_relaxation() -> None:
    scenario = SCENARIOS[0]
    constrained = replace(
        scenario,
        constraints=replace(scenario.constraints, taxi_budget_krw=6_000, strict_taxi_budget=False),
    )
    api = invoke_integrated_private_api(constrained, "R1")
    assert api.status_code == 200
    assert api.body["routes"]
    assert all(route["taxiCost"]["upper"] <= 6_000 for route in api.body["routes"])
    assert api.body["recommendations"]["publicTransitOnly"] is not None
