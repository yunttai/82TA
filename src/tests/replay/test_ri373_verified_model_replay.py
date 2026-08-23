from __future__ import annotations

import json
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from bus_intelligence_core import (
    TRAFFIC_CONTEXT_SCHEMA_VERSION,
    WEATHER_CONTEXT_SCHEMA_VERSION,
    EtaCompleteFeatureVector,
    EtaFeatureContext,
    EtaNativePrediction,
    EtaPredictorInput,
    SeatRiskCompleteFeatureVector,
    SeatRiskFeatureContext,
    SeatRiskNativePrediction,
    SeatRiskPredictorInput,
    TrafficFeatureContext,
    VerifiedEtaPredictor,
    VerifiedEtaPredictorAttestation,
    VerifiedPredictorConfigurationError,
    VerifiedSeatRiskPredictor,
    VerifiedSeatRiskPredictorAttestation,
    WeatherFeatureContext,
)
from routing_api.application import RequestContext
from routing_api.fanin_integration import (
    BusObservationQuery,
    CanonicalFanInOptimizeRouteUseCase,
    fixture_fan_in_dependencies,
)
from routing_api.fixture_scenarios import fixture_scenario
from routing_api.production_composition import _verified_model_projection
from routing_api.tests.test_api import FakeClock
from routing_api.tests.test_bus_context_integration import (
    _RecordingContextPort,
    _fixture_leg_and_envelope,
)
from routing_api.tests.test_fixture_integration import _verified_model_pair
from routing_worker.data_quality.dataset_foundation import (
    TargetStopObservation,
    build_target_stop_labels,
)
from routing_worker.feature_builder import (
    NormalizedFeatureObservation,
    build_eta_features,
    build_seat_features,
)
from routing_worker.feature_encoding import (
    encode_feature_mapping,
    encode_feature_values,
    feature_schema_document,
)
from routing_worker.feature_schema import (
    ETA_FEATURE_NAMES,
    ETA_SCHEMA_VERSION,
    SEAT_FEATURE_NAMES,
    SEAT_SCHEMA_VERSION,
)
from routing_worker.native_lightgbm import LightGbmSeatRiskRuntimeLoader
from routing_worker.serving_features import (
    DurableEtaCompleteVectorBuilder,
    DurableSeatRiskCompleteVectorBuilder,
    EtaServingFeatureRecord,
    SeatRiskServingFeatureRecord,
)
from transport_mapping import (
    CanonicalRouteCandidate,
    DisabledGitsRoadLinkIdentityRepository,
    GitsRoadLinkIdentity,
    GitsRoadLinkIdentityRecord,
    InMemoryGitsRoadLinkIdentityRepository,
    MappingGrade,
    PersistedMappingResolution,
    ReviewDisposition,
    StopSignal,
    ValidityWindow,
    enrich_selected_gits_road_link_target,
)
from transport_mapping.models import Coordinate

from test_ri362_bus_context_replay import _execute_context_api


UTC = timezone.utc
AS_OF = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
OBSERVED_AT = AS_OF - timedelta(seconds=10)


def _contexts() -> tuple[EtaFeatureContext, SeatRiskFeatureContext]:
    weather = WeatherFeatureContext(
        OBSERVED_AT,
        WEATHER_CONTEXT_SCHEMA_VERSION,
        temperature_c=0.0,
        precipitation_mm=0.0,
    )
    traffic = TrafficFeatureContext(
        OBSERVED_AT,
        TRAFFIC_CONTEXT_SCHEMA_VERSION,
        speed_kph=0.0,
        travel_time_seconds=0,
        incident_present=False,
    )
    return EtaFeatureContext(weather, traffic), SeatRiskFeatureContext(weather, traffic)


def _observation(**changes: object) -> NormalizedFeatureObservation:
    value = NormalizedFeatureObservation(
        trip_id="ri-373-trip",
        route_id="route-1",
        direction="UP",
        observed_at=OBSERVED_AT,
        ingested_at=OBSERVED_AT + timedelta(seconds=2),
        valid_at=OBSERVED_AT,
        current_station_sequence=4,
        target_station_sequence=8,
        recent_segment_seconds_1=61.0,
        recent_segment_seconds_3=180.0,
        recent_segment_seconds_5=300.0,
        historical_segment_seconds=64.0,
        headway_seconds=420.0,
        current_remaining_seats=0,
        current_crowded_code=0,
        capacity_confidence=0.0,
        recent_seat_delta=0.0,
        query_at=AS_OF,
    )
    return replace(value, **changes)


class _EtaSource:
    def __init__(self, observation: NormalizedFeatureObservation) -> None:
        self.observation = observation

    def load(self, value: EtaPredictorInput) -> EtaServingFeatureRecord:
        return EtaServingFeatureRecord(value.vehicle_ref, value.boarding_stop_id, self.observation)


class _SeatSource:
    def __init__(self, observation: NormalizedFeatureObservation) -> None:
        self.observation = observation

    def load(self, value: SeatRiskPredictorInput) -> SeatRiskServingFeatureRecord:
        return SeatRiskServingFeatureRecord(
            value.vehicle_ref,
            value.boarding_stop_id,
            value.target_stop_id,
            self.observation,
        )


def _eta_input(context: EtaFeatureContext | None = None) -> EtaPredictorInput:
    return EtaPredictorInput(
        "vehicle-token",
        "route-1",
        "UP",
        "stop-4",
        OBSERVED_AT,
        0,
        AS_OF,
        context,
    )


def _seat_input(context: SeatRiskFeatureContext | None = None) -> SeatRiskPredictorInput:
    return SeatRiskPredictorInput(
        "vehicle-token",
        "route-1",
        "UP",
        "stop-4",
        "stop-8",
        OBSERVED_AT,
        AS_OF,
        0,
        context,
    )


def _eta_attestation() -> VerifiedEtaPredictorAttestation:
    return VerifiedEtaPredictorAttestation(
        family="ETA",
        model_version="eta-ri373-v1",
        full_feature_schema_version=ETA_SCHEMA_VERSION,
        ordered_feature_names=ETA_FEATURE_NAMES,
        artifact_sha256="a" * 64,
        verified_artifact_sha256="a" * 64,
        artifact_format="LIGHTGBM_TEXT",
        deployment_id="eta-deployment-ri373",
        deployment_environment="staging",
        deployment_state="ACTIVE",
        readiness="ACTIVE",
        calibrated=True,
        calibration_method="CONFORMAL",
        calibration_sha256="b" * 64,
        verified_calibration_sha256="b" * 64,
    )


def _seat_attestation() -> VerifiedSeatRiskPredictorAttestation:
    return VerifiedSeatRiskPredictorAttestation(
        family="SEAT_RISK",
        model_version="seat-ri373-v1",
        full_feature_schema_version=SEAT_SCHEMA_VERSION,
        ordered_feature_names=SEAT_FEATURE_NAMES,
        artifact_sha256="c" * 64,
        verified_artifact_sha256="c" * 64,
        artifact_format="LIGHTGBM_TEXT",
        deployment_id="seat-deployment-ri373",
        deployment_environment="staging",
        deployment_state="ACTIVE",
        readiness="ACTIVE",
        calibrated=True,
        calibration_method="PLATT",
        calibration_sha256="d" * 64,
        verified_calibration_sha256="d" * 64,
    )


class _EtaRuntime:
    family = "ETA"
    model_version = "eta-ri373-v1"
    artifact_sha256 = "a" * 64
    artifact_format = "LIGHTGBM_TEXT"
    calibration_sha256 = "b" * 64

    def predict(self, value: EtaCompleteFeatureVector) -> EtaNativePrediction:
        assert value.feature_names == ETA_FEATURE_NAMES
        return EtaNativePrediction(121, 180, 0.8)


class _SeatRuntime:
    family = "SEAT_RISK"
    model_version = "seat-ri373-v1"
    artifact_sha256 = "c" * 64
    artifact_format = "LIGHTGBM_TEXT"
    calibration_sha256 = "d" * 64

    def __init__(self, session) -> None:
        self.session = session

    def predict(self, value: SeatRiskCompleteFeatureVector) -> SeatRiskNativePrediction | None:
        assert value.feature_names == SEAT_FEATURE_NAMES
        return self.session.predict(value.values)


class _FakeBooster:
    def __init__(self, module: "_FakeLightGbm") -> None:
        self.module = module
        self.params = {"objective": "multiclass", "num_class": 4}

    def feature_name(self) -> list[str]:
        return list(self.module.names)

    def predict(self, matrix: list[list[float]]) -> list[object]:
        self.module.matrices.append(matrix)
        return [[0.05, 0.20, 0.45, 0.30]]


class _FakeLightGbm:
    def __init__(self) -> None:
        self.names = SEAT_FEATURE_NAMES
        self.matrices: list[list[list[float]]] = []

    def Booster(self, *, model_file: str) -> _FakeBooster:  # noqa: N802
        assert model_file.endswith("model.txt")
        return _FakeBooster(self)


def _seat_session(root: Path):
    model = root / "model.txt"
    schema = root / "feature-schema.json"
    calibration = root / "calibration.json"
    model.write_text("safe fixture\n", encoding="utf-8")
    schema.write_text(
        json.dumps(feature_schema_document(family="SEAT_RISK"), separators=(",", ":")),
        encoding="utf-8",
    )
    calibration.write_text(
        json.dumps(
            {
                "schemaVersion": "seat-risk-calibration-v1",
                "family": "SEAT_RISK",
                "method": "PLATT",
                "confidence": 0.75,
                "parameters": [
                    {"slope": 1.0, "intercept": 0.0},
                    {"slope": 1.0, "intercept": 0.0},
                    {"slope": 1.0, "intercept": 0.0},
                ],
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return LightGbmSeatRiskRuntimeLoader(_FakeLightGbm()).load(
        artifact_path=model,
        artifact_format="LIGHTGBM_TEXT",
        calibration_path=calibration,
        calibration_method="PLATT",
        feature_schema_path=schema,
        feature_schema_version=SEAT_SCHEMA_VERSION,
        feature_names=SEAT_FEATURE_NAMES,
    )


def test_same_observation_is_exact_22_field_train_serve_and_encoding_parity() -> None:
    eta_context, seat_context = _contexts()
    base = _observation()
    eta_train = build_eta_features(replace(base, eta_feature_context=eta_context))
    eta_serve = DurableEtaCompleteVectorBuilder(_EtaSource(base)).build(
        _eta_input(eta_context)
    )
    seat_train = build_seat_features(
        replace(base, seat_risk_feature_context=seat_context)
    )
    seat_serve = DurableSeatRiskCompleteVectorBuilder(_SeatSource(base)).build(
        _seat_input(seat_context)
    )

    assert eta_serve is not None and seat_serve is not None
    assert len(eta_serve.feature_names) == len(seat_serve.feature_names) == 22
    assert (eta_train.schema_version, eta_train.feature_names, eta_train.values, eta_train.missing_flags) == (
        eta_serve.schema_version,
        eta_serve.feature_names,
        eta_serve.values,
        eta_serve.missing_flags,
    )
    assert (seat_train.schema_version, seat_train.feature_names, seat_train.values, seat_train.missing_flags) == (
        seat_serve.schema_version,
        seat_serve.feature_names,
        seat_serve.values,
        seat_serve.missing_flags,
    )
    for family, train, serve in (
        ("ETA", eta_train, eta_serve),
        ("SEAT_RISK", seat_train, seat_serve),
    ):
        assert encode_feature_mapping(
            family=family,
            feature_schema_version=train.schema_version,
            feature_names=train.feature_names,
            values=train.as_mapping,
        ) == encode_feature_values(
            family=family,
            feature_schema_version=serve.schema_version,
            feature_names=serve.feature_names,
            values=serve.values,
        )
    eta_values = dict(zip(eta_serve.feature_names, eta_serve.values, strict=True))
    seat_values = dict(zip(seat_serve.feature_names, seat_serve.values, strict=True))
    assert eta_values["traffic_incident_present"] is False
    assert seat_values["current_remaining_seats"] == 0
    assert seat_values["capacity_confidence"] == 0.0


def test_eta_duration_timestamp_and_seat_ordinal_calibration_stay_separate(
    tmp_path: Path,
) -> None:
    eta_context, seat_context = _contexts()
    base = _observation()
    eta = VerifiedEtaPredictor(
        DurableEtaCompleteVectorBuilder(_EtaSource(base)),
        _EtaRuntime(),
        _eta_attestation(),
        expected_feature_schema_version=ETA_SCHEMA_VERSION,
        expected_feature_names=ETA_FEATURE_NAMES,
        required_environment="staging",
    )
    seat = VerifiedSeatRiskPredictor(
        DurableSeatRiskCompleteVectorBuilder(_SeatSource(base)),
        _SeatRuntime(_seat_session(tmp_path)),
        _seat_attestation(),
        expected_feature_schema_version=SEAT_SCHEMA_VERSION,
        expected_feature_names=SEAT_FEATURE_NAMES,
        required_environment="staging",
    )

    eta_prediction = eta.predict(_eta_input(eta_context))
    seat_prediction = seat.predict(_seat_input(seat_context))
    assert eta_prediction is not None and seat_prediction is not None
    assert eta_prediction.p50_arrival_at == AS_OF + timedelta(seconds=121)
    assert eta_prediction.p90_arrival_at == AS_OF + timedelta(seconds=180)
    assert eta_prediction.p50_arrival_at.utcoffset() is not None
    assert eta_prediction.source == "POSITION_MODEL"
    assert (
        seat_prediction.no_seat_probability,
        seat_prediction.low_seat2_probability,
        seat_prediction.low_seat5_probability,
    ) == pytest.approx((0.05, 0.25, 0.70))
    assert seat_prediction.origin == "MODEL_PREDICTED"
    assert eta.attestation.calibration_method == "CONFORMAL"
    assert seat.attestation.calibration_method == "PLATT"

    missing = build_target_stop_labels(
        trip_id="ri-373-trip",
        target_stop_id="stop-8",
        feature_observed_at=AS_OF,
        observations=(
            # Equal-time and wrong-trip future observations are not target evidence.
            TargetStopObservation("ri-373-trip", "stop-8", AS_OF, 0),
            TargetStopObservation(
                "different-trip", "stop-8", AS_OF + timedelta(seconds=30), 0
            ),
        ),
    )
    missing_seat = build_target_stop_labels(
        trip_id="ri-373-trip",
        target_stop_id="stop-8",
        feature_observed_at=AS_OF,
        observations=(
            TargetStopObservation(
                "ri-373-trip", "stop-8", AS_OF + timedelta(seconds=30), None
            ),
        ),
    )
    observed_zero = build_target_stop_labels(
        trip_id="ri-373-trip",
        target_stop_id="stop-8",
        feature_observed_at=AS_OF,
        observations=(
            TargetStopObservation(
                "ri-373-trip", "stop-8", AS_OF + timedelta(seconds=30), 0
            ),
        ),
    )
    assert not missing.eta_seconds.has_target and missing.eta_seconds.value is None
    assert not missing.seat_ordinal_class.has_target
    assert missing_seat.eta_seconds.value == 30
    assert not missing_seat.seat_ordinal_class.has_target
    assert observed_zero.seat_ordinal_class.has_target
    assert observed_zero.seat_ordinal_class.value == 0
    assert observed_zero.no_seat.value is True


@pytest.mark.parametrize("failure", ("family", "schema", "hash", "calibration", "state"))
def test_verified_eta_family_schema_hash_calibration_and_state_fail_closed(
    failure: str,
) -> None:
    builder = DurableEtaCompleteVectorBuilder(_EtaSource(_observation()))
    attestation = _eta_attestation()
    expected_schema = ETA_SCHEMA_VERSION
    with pytest.raises(VerifiedPredictorConfigurationError):
        if failure == "family":
            attestation = replace(attestation, family="SEAT_RISK")
        elif failure == "schema":
            expected_schema = "eta-feature-drift"
        elif failure == "hash":
            attestation = replace(attestation, verified_artifact_sha256="0" * 64)
        elif failure == "calibration":
            attestation = replace(attestation, calibration_method="ISOTONIC")
        else:
            attestation = replace(attestation, deployment_state="SHADOW")
        VerifiedEtaPredictor(
            builder,
            _EtaRuntime(),
            attestation,
            expected_feature_schema_version=expected_schema,
            expected_feature_names=ETA_FEATURE_NAMES,
            required_environment="staging",
        )


def _mapping_target() -> tuple[CanonicalRouteCandidate, PersistedMappingResolution]:
    route_id = str(uuid4())
    validity = ValidityWindow(AS_OF - timedelta(days=1), AS_OF + timedelta(days=1))
    target = CanonicalRouteCandidate(
        route_id=route_id,
        route_name="5000A",
        route_type="SEATED",
        boarding=StopSignal("Board", Coordinate(127.1, 37.3), "stop-a", 1),
        alighting=StopSignal("Target", Coordinate(127.2, 37.4), "stop-b", 5),
        direction="UP",
        branch_id=None,
        origin_terminal=None,
        destination_terminal=None,
        validity=validity,
        geometry=(Coordinate(127.1, 37.3), Coordinate(127.2, 37.4)),
    )
    resolution = PersistedMappingResolution(
        entity_mapping_id=str(uuid4()),
        provider_fingerprint="a" * 64,
        candidate_fingerprint="b" * 64,
        route_id=route_id,
        mapping_version="mapping-ri373-v1",
        validity=validity,
        accepted_at=AS_OF - timedelta(seconds=1),
    )
    return target, resolution


class _RejectingIdentityRepository:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def find_for_targets(self, targets, *, as_of):
        del targets, as_of
        raise self.error


@pytest.mark.parametrize("mode", ("valid", "disabled", "stale", "ambiguous", "outage"))
def test_gits_identity_is_exact_current_accepted_high_or_absent(mode: str) -> None:
    target, resolution = _mapping_target()
    current = GitsRoadLinkIdentity(
        ("GITS-LINK-001", "GITS-LINK-002"),
        "gits-map-ri373-v1",
        target.validity,
    )
    if mode == "valid":
        repository = InMemoryGitsRoadLinkIdentityRepository(
            (GitsRoadLinkIdentityRecord(target.route_id, "UP", current),)
        )
    elif mode == "disabled":
        repository = DisabledGitsRoadLinkIdentityRepository()
    elif mode == "stale":
        stale = GitsRoadLinkIdentity(
            ("GITS-LINK-001",),
            "gits-map-ri373-v1",
            ValidityWindow(AS_OF - timedelta(days=2), AS_OF - timedelta(days=1)),
        )
        repository = InMemoryGitsRoadLinkIdentityRepository(
            (GitsRoadLinkIdentityRecord(target.route_id, "UP", stale),)
        )
    elif mode == "ambiguous":
        repository = _RejectingIdentityRepository(ValueError("ambiguous identity"))
    else:
        repository = _RejectingIdentityRepository(TimeoutError("identity outage"))

    enriched = enrich_selected_gits_road_link_target(
        target, resolution, repository, as_of=AS_OF
    )
    query = CanonicalFanInOptimizeRouteUseCase._traffic_context_query(
        enriched, SimpleNamespace(geometry=()), AS_OF
    )
    assert resolution.grade is MappingGrade.HIGH
    assert resolution.review_disposition is ReviewDisposition.AUTO_ACCEPT
    if mode == "valid":
        assert enriched.gits_road_link_identity == current
        assert query is not None
        assert query.relevant_link_external_ids == current.link_external_ids
    else:
        assert enriched.gits_road_link_identity is None
        assert enriched.traffic_link_external_ids == ()
        assert query is None


def test_accepted_gits_provider_outage_is_missing_not_fabricated_or_500() -> None:
    clock = FakeClock(wall=AS_OF)
    dependencies = fixture_fan_in_dependencies(fixture_scenario("R1"))
    leg, envelope = _fixture_leg_and_envelope(dependencies)
    target, resolution = _mapping_target()
    identity = GitsRoadLinkIdentity(
        ("GITS-LINK-001", "GITS-LINK-002"), "gits-map-ri373-v1", target.validity
    )
    target = enrich_selected_gits_road_link_target(
        target,
        resolution,
        InMemoryGitsRoadLinkIdentityRepository(
            (GitsRoadLinkIdentityRecord(target.route_id, "UP", identity),)
        ),
        as_of=AS_OF,
    )

    class OutagePort(_RecordingContextPort):
        def traffic(self, query, *, deadline):
            del deadline
            self.traffic_queries.append(query)
            raise TimeoutError("optional GITS outage")

    port = OutagePort(envelope)
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "ri-373-gits-outage", clock, dependencies=replace(dependencies, context=port)
    )
    context = RequestContext(
        "ri-373-correlation",
        "ri-373-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    group = use_case._fetch_bus_optional_group(
        context,
        dependencies.providers,
        port,
        BusObservationQuery(target.route_id, "stop-a", AS_OF),
        target,
        leg,
        "SEATED",
    )
    assert group.started_units == 4
    assert group.arrivals is not None and group.locations is not None
    assert group.weather is not None and group.traffic is None
    assert group.context_complete is False
    assert len(port.traffic_queries) == 1
    assert port.traffic_queries[0].relevant_link_external_ids == identity.link_external_ids
    assert group.eta_feature_context is not None
    assert group.eta_feature_context.traffic is None
    assert group.seat_risk_feature_context is not None
    assert group.seat_risk_feature_context.traffic is None


def test_model_endpoint_projection_and_optimize_provenance_have_distinct_single_sources() -> None:
    eta, seat = _verified_model_pair("staging")
    projection = _verified_model_projection(eta, seat, "staging")
    assert projection is not None
    assert tuple(dict(value) for value in projection) == (
        {"purpose": "BUS_ETA", "version": "eta-production-1", "state": "ACTIVE"},
        {"purpose": "SEAT_RISK", "version": "seat-production-1", "state": "ACTIVE"},
    )

    response, _, _, _, _, _, persisted = _execute_context_api(context_mode="fresh")
    deployed_versions = {value["version"] for value in projection}
    actual_versions = {value["version"] for value in response["modelVersions"]}
    assert actual_versions
    assert actual_versions.isdisjoint(deployed_versions)
    for route in response["routes"]:
        for leg in route["legs"]:
            if leg["mode"] != "BUS" or leg["busIntelligence"] is None:
                continue
            leg_models = {
                value["provider"].rsplit("/", 1)[-1]
                for value in leg["provenance"]
                if value["origin"]
                in {"POSITION_MODEL", "MODEL_PREDICTED", "HISTORICAL_PROXY"}
            }
            assert leg_models <= actual_versions
    persisted_versions = {
        version
        for leg in persisted.bus_enrichments
        for version in (leg.eta_model_version, leg.seat_model_version)
        if version is not None
    }
    assert persisted_versions <= actual_versions
