from datetime import datetime, timedelta, timezone
import unittest

from bus_intelligence_core import (
    ETA_CONTEXT_FEATURE_NAMES,
    ETA_CONTEXT_SERVING_SCHEMA_VERSION,
    SEAT_RISK_CONTEXT_FEATURE_NAMES,
    SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION,
    TRAFFIC_CONTEXT_FUTURE_EXCLUDED,
    TRAFFIC_CONTEXT_MISSING,
    TRAFFIC_CONTEXT_SCHEMA_MISMATCH,
    TRAFFIC_CONTEXT_SCHEMA_VERSION,
    WEATHER_CONTEXT_FUTURE_EXCLUDED,
    WEATHER_CONTEXT_MISSING,
    WEATHER_CONTEXT_SCHEMA_VERSION,
    WEATHER_CONTEXT_STALE,
    EtaFeatureContext,
    FeatureContextPolicy,
    SeatRiskFeatureContext,
    TrafficFeatureContext,
    WeatherFeatureContext,
    build_eta_context_features,
    build_seat_risk_context_features,
)
from dataset_foundation import DatasetInvariantError
from feature_builder import (
    ETA_FEATURE_NAMES,
    ETA_SCHEMA_VERSION,
    SEAT_FEATURE_NAMES,
    SEAT_SCHEMA_VERSION,
    NormalizedFeatureObservation,
    build_eta_features,
    build_seat_features,
    make_dataset_snapshot,
)


UTC = timezone.utc
QUERY_AT = datetime(2026, 8, 23, 1, 2, tzinfo=UTC)


class FeatureBuilderTest(unittest.TestCase):
    def observation(self):
        observed = QUERY_AT - timedelta(seconds=10)
        return NormalizedFeatureObservation(
            trip_id="trip", route_id="route", direction="UP",
            observed_at=observed, valid_at=QUERY_AT,
            ingested_at=observed + timedelta(seconds=3),
            current_station_sequence=2, target_station_sequence=5,
            recent_segment_seconds_1=20, current_remaining_seats=0,
            capacity_confidence=0.8,
            quality_flags=("SOURCE_CLOCK_UNCERTAIN", "SOURCE_CLOCK_UNCERTAIN"),
        )

    def test_same_builder_is_deterministic_for_train_and_serve(self):
        observation = self.observation()
        train = build_eta_features(observation)
        serve = build_eta_features(observation)
        self.assertEqual(train, serve)
        self.assertEqual(train.schema_version, ETA_SCHEMA_VERSION)
        self.assertEqual(train.as_mapping["remaining_stops"], 3)
        self.assertIn("historical_segment_seconds", train.missing_flags)
        self.assertIn("SOURCE_CLOCK_UNCERTAIN", train.missing_flags)

    def test_eta_and_seat_schemas_are_separate_and_zero_is_observed(self):
        observation = self.observation()
        eta = build_eta_features(observation)
        seat = build_seat_features(observation)
        self.assertNotEqual(eta.schema_version, seat.schema_version)
        self.assertEqual(seat.schema_version, SEAT_SCHEMA_VERSION)
        self.assertEqual(seat.as_mapping["current_remaining_seats"], 0)
        self.assertNotIn("current_remaining_seats", seat.missing_flags)

    def test_train_builder_consumes_exact_serving_projection_and_metadata_order(self):
        self.assertEqual(len(ETA_CONTEXT_FEATURE_NAMES), 8)
        self.assertEqual(len(SEAT_RISK_CONTEXT_FEATURE_NAMES), 8)
        weather = WeatherFeatureContext(
            QUERY_AT - timedelta(seconds=30),
            WEATHER_CONTEXT_SCHEMA_VERSION,
            temperature_c=21.5,
            precipitation_mm=0.0,
        )
        traffic = TrafficFeatureContext(
            QUERY_AT - timedelta(seconds=12),
            TRAFFIC_CONTEXT_SCHEMA_VERSION,
            speed_kph=42.0,
            travel_time_seconds=180.0,
            incident_present=False,
        )
        eta_context = EtaFeatureContext(weather=weather, traffic=traffic)
        seat_context = SeatRiskFeatureContext(weather=weather, traffic=traffic)
        base = self.observation()
        observation = NormalizedFeatureObservation(
            **{
                name: getattr(base, name)
                for name in base.__dataclass_fields__
                if name not in {"eta_feature_context", "seat_risk_feature_context"}
            },
            eta_feature_context=eta_context,
            seat_risk_feature_context=seat_context,
        )

        eta_train = build_eta_features(observation)
        eta_serve = build_eta_context_features(eta_context, QUERY_AT)
        seat_train = build_seat_features(observation)
        seat_serve = build_seat_risk_context_features(seat_context, QUERY_AT)

        self.assertEqual(eta_train.schema_version, ETA_SCHEMA_VERSION)
        self.assertIn(ETA_CONTEXT_SERVING_SCHEMA_VERSION, eta_train.schema_version)
        self.assertEqual(eta_train.feature_names, ETA_FEATURE_NAMES)
        self.assertEqual(
            eta_train.feature_names[-(len(ETA_CONTEXT_FEATURE_NAMES) + 1):-1],
            ETA_CONTEXT_FEATURE_NAMES,
        )
        self.assertEqual(
            tuple(eta_train.as_mapping[name] for name in ETA_CONTEXT_FEATURE_NAMES),
            eta_serve.values,
        )
        self.assertIn(SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION, seat_train.schema_version)
        self.assertEqual(seat_train.feature_names, SEAT_FEATURE_NAMES)
        self.assertEqual(
            tuple(
                seat_train.as_mapping[name]
                for name in SEAT_RISK_CONTEXT_FEATURE_NAMES
            ),
            seat_serve.values,
        )

    def test_observed_zero_and_false_survive_context_projection(self):
        context = EtaFeatureContext(
            weather=WeatherFeatureContext(
                QUERY_AT,
                WEATHER_CONTEXT_SCHEMA_VERSION,
                temperature_c=0.0,
                precipitation_mm=0.0,
            ),
            traffic=TrafficFeatureContext(
                QUERY_AT,
                TRAFFIC_CONTEXT_SCHEMA_VERSION,
                speed_kph=0.0,
                travel_time_seconds=0.0,
                incident_present=False,
            ),
        )
        base = self.observation()
        values = {name: getattr(base, name) for name in base.__dataclass_fields__}
        values["eta_feature_context"] = context
        vector = build_eta_features(NormalizedFeatureObservation(**values))
        self.assertEqual(vector.as_mapping["weather_temperature_c"], 0.0)
        self.assertEqual(vector.as_mapping["traffic_speed_kph"], 0.0)
        self.assertIs(vector.as_mapping["traffic_incident_present"], False)
        self.assertNotIn("weather_temperature_c", vector.missing_flags)
        self.assertNotIn("traffic_incident_present", vector.missing_flags)

    def test_future_stale_schema_mismatch_and_missing_context_remain_null_with_flags(self):
        base = self.observation()
        future = EtaFeatureContext(
            weather=WeatherFeatureContext(
                QUERY_AT + timedelta(seconds=1),
                WEATHER_CONTEXT_SCHEMA_VERSION,
                temperature_c=12.0,
            ),
            traffic=TrafficFeatureContext(
                QUERY_AT + timedelta(seconds=1),
                TRAFFIC_CONTEXT_SCHEMA_VERSION,
                speed_kph=30.0,
            ),
        )
        values = {name: getattr(base, name) for name in base.__dataclass_fields__}
        values["eta_feature_context"] = future
        future_vector = build_eta_features(NormalizedFeatureObservation(**values))
        self.assertIsNone(future_vector.as_mapping["weather_temperature_c"])
        self.assertIsNone(future_vector.as_mapping["traffic_speed_kph"])
        self.assertIn(WEATHER_CONTEXT_FUTURE_EXCLUDED, future_vector.missing_flags)
        self.assertIn(TRAFFIC_CONTEXT_FUTURE_EXCLUDED, future_vector.missing_flags)

        rejected = EtaFeatureContext(
            weather=WeatherFeatureContext(
                QUERY_AT - timedelta(seconds=10),
                WEATHER_CONTEXT_SCHEMA_VERSION,
                temperature_c=12.0,
            ),
            traffic=TrafficFeatureContext(
                QUERY_AT,
                "unsupported-traffic-schema",
                speed_kph=30.0,
            ),
        )
        values["eta_feature_context"] = rejected
        rejected_vector = build_eta_features(
            NormalizedFeatureObservation(**values),
            context_policy=FeatureContextPolicy(
                weather_max_age_seconds=5,
                traffic_max_age_seconds=300,
            ),
        )
        self.assertIsNone(rejected_vector.as_mapping["weather_temperature_c"])
        self.assertIsNone(rejected_vector.as_mapping["traffic_speed_kph"])
        self.assertIn(WEATHER_CONTEXT_STALE, rejected_vector.missing_flags)
        self.assertIn(TRAFFIC_CONTEXT_SCHEMA_MISMATCH, rejected_vector.missing_flags)

        missing_vector = build_eta_features(base)
        self.assertIn(WEATHER_CONTEXT_MISSING, missing_vector.missing_flags)
        self.assertIn(TRAFFIC_CONTEXT_MISSING, missing_vector.missing_flags)

    def test_eta_and_seat_context_and_policy_are_isolated(self):
        weather_at = QUERY_AT - timedelta(seconds=10)
        eta_context = EtaFeatureContext(
            weather=WeatherFeatureContext(
                weather_at, WEATHER_CONTEXT_SCHEMA_VERSION, temperature_c=11.0
            ),
            traffic=None,
        )
        seat_context = SeatRiskFeatureContext(
            weather=WeatherFeatureContext(
                weather_at, WEATHER_CONTEXT_SCHEMA_VERSION, temperature_c=22.0
            ),
            traffic=None,
        )
        base = self.observation()
        values = {name: getattr(base, name) for name in base.__dataclass_fields__}
        values.update(
            eta_feature_context=eta_context,
            seat_risk_feature_context=seat_context,
        )
        observation = NormalizedFeatureObservation(**values)
        eta = build_eta_features(
            observation,
            context_policy=FeatureContextPolicy(
                weather_max_age_seconds=5,
                traffic_max_age_seconds=300,
            ),
        )
        seat = build_seat_features(observation)
        self.assertIsNone(eta.as_mapping["weather_temperature_c"])
        self.assertIn(WEATHER_CONTEXT_STALE, eta.missing_flags)
        self.assertEqual(seat.as_mapping["weather_temperature_c"], 22.0)
        self.assertNotIn(WEATHER_CONTEXT_STALE, seat.missing_flags)
        self.assertEqual(eta.family, "ETA")
        self.assertEqual(seat.family, "SEAT_RISK")

    def test_query_clock_and_typed_family_context_fail_closed(self):
        base = self.observation()
        common = {name: getattr(base, name) for name in base.__dataclass_fields__}
        common["query_at"] = datetime(2026, 8, 23, 1, 2)
        with self.assertRaisesRegex(DatasetInvariantError, "query_at"):
            NormalizedFeatureObservation(**common)

        common["query_at"] = base.observed_at - timedelta(seconds=1)
        with self.assertRaisesRegex(DatasetInvariantError, "available as-of"):
            NormalizedFeatureObservation(**common)

        common["query_at"] = QUERY_AT
        common["eta_feature_context"] = SeatRiskFeatureContext(
            missing_flags=(WEATHER_CONTEXT_MISSING, TRAFFIC_CONTEXT_MISSING)
        )
        with self.assertRaisesRegex(DatasetInvariantError, "ETA context"):
            NormalizedFeatureObservation(**common)

    def test_dataset_snapshot_hash_is_order_and_content_sensitive(self):
        at = datetime(2026, 8, 23, tzinfo=UTC)
        first = make_dataset_snapshot(
            dataset_version="d1", feature_schema_version=ETA_SCHEMA_VERSION,
            target_schema_version="eta-target-v1", rows=({"x": 1}, {"x": 2}), created_at=at,
        )
        same = make_dataset_snapshot(
            dataset_version="d1", feature_schema_version=ETA_SCHEMA_VERSION,
            target_schema_version="eta-target-v1", rows=({"x": 1}, {"x": 2}), created_at=at,
        )
        changed = make_dataset_snapshot(
            dataset_version="d1", feature_schema_version=ETA_SCHEMA_VERSION,
            target_schema_version="eta-target-v1", rows=({"x": 2}, {"x": 1}), created_at=at,
        )
        self.assertEqual(first.content_sha256, same.content_sha256)
        self.assertNotEqual(first.content_sha256, changed.content_sha256)


if __name__ == "__main__":
    unittest.main()
