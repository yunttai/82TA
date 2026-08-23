from __future__ import annotations

import json
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone

import pytest

from provider_core.canonical import Coordinate
from provider_core.capabilities import foundation_capability_registry
from provider_core.context import TrafficLinkContext, WeatherContext
from provider_core.context_queries import (
    GitsTrafficCorridorQuery,
    KmaWeatherQuery,
    MAX_TRAFFIC_CORRIDOR_POINTS,
    MAX_TRAFFIC_LINKS,
)
from provider_core.envelope import ProviderStatus, QualityFlag
from provider_core.named import (
    ENDPOINT_SPECS,
    GitsTrafficAdapter,
    ProviderAdapterSuite,
    ProviderFixtureScenario,
)
from provider_core.resilience import Deadline
from provider_core.telemetry import MemoryTelemetrySink
from provider_core.validation import SchemaValidationError
from routing_api.capabilities import foundation_capability_projection
from routing_api.fanin_integration import FanInDependencies, fixture_fan_in_dependencies
from routing_api.fixture_scenarios import fixture_scenario
from routing_api.production_composition import (
    NamedProductionBusContextPort,
    build_default_production_use_case,
)
from routing_api.application import RoutingUnavailableError


KST = timezone(timedelta(hours=9))
AS_OF = datetime(2026, 8, 24, 8, 50, tzinfo=KST)
BOARDING = Coordinate(127.10, 37.39)
ALIGHTING = Coordinate(127.11, 37.40)


class _NoNetworkTransport:
    def __init__(self) -> None:
        self.calls = 0

    def send(self, request):
        self.calls += 1
        raise AssertionError("disabled optional context attempted network I/O")


def _weather_query(*, as_of: datetime = AS_OF) -> KmaWeatherQuery:
    return KmaWeatherQuery.from_coordinate(BOARDING, as_of)


def _traffic_query(
    *,
    as_of: datetime = AS_OF,
    corridor: tuple[Coordinate, ...] = (BOARDING, ALIGHTING),
    links: tuple[str, ...] = ("sanitized-gits-link-a",),
) -> GitsTrafficCorridorQuery:
    return GitsTrafficCorridorQuery.from_corridor(
        corridor,
        as_of,
        relevant_link_external_ids=links,
        maximum_links=max(1, len(links)),
    )


def test_foundation_kma_gits_are_disabled_with_zero_network_quota_and_cost() -> None:
    transport = _NoNetworkTransport()
    telemetry = MemoryTelemetrySink()
    suite = ProviderAdapterSuite(transport, telemetry=telemetry, clock=lambda: AS_OF)

    weather = suite.kma.context_query(
        _weather_query(), deadline=Deadline.after_ms(100)
    )
    traffic = suite.gits.context_query(
        _traffic_query(), deadline=Deadline.after_ms(100)
    )

    assert weather.status is traffic.status is ProviderStatus.DISABLED
    assert weather.payload is traffic.payload is None
    assert transport.calls == 0
    assert len(telemetry.events) == 2
    assert {(item.provider, item.operation) for item in telemetry.events} == {
        ("KMA", "weather_context"),
        ("GITS", "traffic_context"),
    }
    assert all(item.provider_call_count == 0 for item in telemetry.events)
    assert all(item.quota_units == 0 for item in telemetry.events)
    assert all(item.estimated_cost_microunits is None for item in telemetry.events)
    assert all(item.response_bytes == 0 for item in telemetry.events)

    registry = foundation_capability_registry()
    for provider, operation in (
        ("KMA", "weather_context"),
        ("GITS", "traffic_context"),
    ):
        capability = registry.get(provider, operation)
        assert capability.enabled is False
        assert capability.fixture_only is True


def test_context_queries_have_no_caller_url_header_or_secret_surface_and_gits_url_is_unset(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gits_spec = next(
        spec
        for spec in ENDPOINT_SPECS
        if (spec.provider, spec.operation) == ("GITS", "traffic_context")
    )
    assert gits_spec.url is None

    forbidden = {"url", "uri", "host", "header", "headers", "secret", "token", "key"}
    for query_type in (KmaWeatherQuery, GitsTrafficCorridorQuery):
        names = {item.name.lower() for item in fields(query_type)}
        assert names.isdisjoint(forbidden)

    with pytest.raises(TypeError):
        KmaWeatherQuery.from_coordinate(  # type: ignore[call-arg]
            BOARDING, AS_OF, url="https://attacker.invalid", headers={"X-Key": "secret"}
        )
    with pytest.raises(TypeError):
        GitsTrafficCorridorQuery.from_corridor(  # type: ignore[call-arg]
            (BOARDING, ALIGHTING), AS_OF, secret="must-not-cross"
        )

    transport = _NoNetworkTransport()
    suite = ProviderAdapterSuite(transport)
    secret = "ri362-context-secret-must-not-cross"
    result = suite.gits.context_query(
        _traffic_query(links=("opaque-link",)), deadline=Deadline.after_ms(100)
    )
    rendered = json.dumps(
        {
            "status": result.status.value,
            "telemetry": [repr(item) for item in suite.gits.telemetry.events],
        }
    )
    assert result.status is ProviderStatus.DISABLED
    assert secret not in rendered
    assert secret not in caplog.text
    assert transport.calls == 0


def test_context_schema_nonfinite_oversize_bbox_and_link_allowlist_fail_closed() -> None:
    suite = ProviderAdapterSuite(_NoNetworkTransport())

    for adapter, query in (
        (suite.kma, _weather_query()),
        (suite.gits, _traffic_query()),
    ):
        drift = adapter.fixture_context(query, ProviderFixtureScenario.SCHEMA_DRIFT)
        assert drift.status is ProviderStatus.BAD_RESPONSE
        assert drift.payload is None
        assert QualityFlag.SCHEMA_DRIFT in drift.quality_flags

    disallowed = suite.gits.fixture_context(
        _traffic_query(links=("different-link",)), ProviderFixtureScenario.SUCCESS
    )
    assert disallowed.status is ProviderStatus.BAD_RESPONSE
    assert disallowed.payload is None

    with pytest.raises(ValueError):
        WeatherContext(BOARDING, AS_OF, float("nan"), None)
    with pytest.raises(ValueError):
        TrafficLinkContext("link", 10, float("inf"), AS_OF)
    with pytest.raises(ValueError):
        GitsTrafficCorridorQuery.from_corridor(
            tuple(BOARDING for _ in range(MAX_TRAFFIC_CORRIDOR_POINTS + 1)), AS_OF
        )
    with pytest.raises(ValueError):
        GitsTrafficCorridorQuery.from_bounds(
            Coordinate(128.5, 38.5), Coordinate(126.0, 36.0), AS_OF
        )
    with pytest.raises(ValueError):
        _traffic_query(links=tuple(f"link-{index}" for index in range(MAX_TRAFFIC_LINKS + 1)))

    oversized_body = {
        "data": [
            {
                "linkId": f"link-{index}",
                "speedKph": 1,
                "travelTimeSeconds": 1,
                "createdAt": AS_OF.isoformat(),
            }
            for index in range(MAX_TRAFFIC_LINKS + 1)
        ]
    }
    with pytest.raises(SchemaValidationError, match="response bound"):
        GitsTrafficAdapter(_NoNetworkTransport())._parse(
            "traffic_context", oversized_body, AS_OF
        )


def test_context_fingerprint_includes_exact_as_of_corridor_and_link_identity() -> None:
    same_instant_utc = AS_OF.astimezone(timezone.utc)
    assert _weather_query().fingerprint() == _weather_query(
        as_of=same_instant_utc
    ).fingerprint()
    assert _weather_query().fingerprint() != _weather_query(
        as_of=AS_OF + timedelta(seconds=1)
    ).fingerprint()

    baseline = _traffic_query()
    assert baseline.fingerprint() == _traffic_query(as_of=same_instant_utc).fingerprint()
    assert baseline.fingerprint() != _traffic_query(
        as_of=AS_OF + timedelta(seconds=1)
    ).fingerprint()
    assert baseline.fingerprint() != _traffic_query(
        corridor=(BOARDING, Coordinate(127.12, 37.41))
    ).fingerprint()
    assert baseline.fingerprint() != _traffic_query(links=("another-link",)).fingerprint()


def test_context_operation_subset_is_explicit_immutable_and_bounded() -> None:
    base = fixture_fan_in_dependencies(fixture_scenario("R1"))
    suite = ProviderAdapterSuite(_NoNetworkTransport())
    valid = NamedProductionBusContextPort(
        suite, frozenset({"weather_context", "traffic_context"})
    )
    dependencies = replace(base, context=valid)
    assert isinstance(dependencies.context.enabled_operations, frozenset)
    with pytest.raises(AttributeError):
        dependencies.context.enabled_operations.add("unknown")  # type: ignore[attr-defined]

    for operations in (
        {"weather_context"},
        frozenset({"weather_context", "unknown"}),
        frozenset({"weather_context", "traffic_context", "unknown"}),
    ):
        port = type(
            "Port",
            (),
            {"enabled_operations": operations},
        )()
        with pytest.raises(ValueError, match="bounded subset"):
            FanInDependencies(
                providers=base.providers,
                mapping=base.mapping,
                eta_predictor=base.eta_predictor,
                seat_predictor=base.seat_predictor,
                context=port,
            )


def test_default_production_composition_injects_no_context_and_capabilities_stay_false() -> None:
    projection = foundation_capability_projection()
    assert not any(projection.features.values())
    context_rows = {
        item["provider"]: item
        for item in projection.providers
        if item["provider"] in {"KMA", "GITS"}
    }
    assert set(context_rows) == {"KMA", "GITS"}
    assert all(item["health"] == "DISABLED" for item in context_rows.values())
    assert all(item["keyVerificationState"] == "UNVERIFIED" for item in context_rows.values())
    assert all(item["productionState"] == "UNAPPROVED" for item in context_rows.values())

    transport = _NoNetworkTransport()
    unavailable = build_default_production_use_case(
        type("Clock", (), {"now": staticmethod(lambda: AS_OF)})(),
        provider_suite=ProviderAdapterSuite(transport),
    )
    with pytest.raises(RoutingUnavailableError):
        unavailable.execute(None, None)
    assert transport.calls == 0

