"""Production-shaped model runtime adapters behind the stable prediction ports.

The adapters validate serving readiness and feature-schema parity before calling a
model. They never deserialize artifacts and never receive future target outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Protocol

from .domain import (
    MODEL_READINESS_VALUES,
    EtaPrediction,
    SeatRiskPrediction,
    require_probability,
)
from .ports import EtaPredictor, EtaPredictorInput, SeatRiskPredictor, SeatRiskPredictorInput


@dataclass(frozen=True, slots=True)
class RuntimeModelSpec:
    purpose: str
    version: str
    readiness: str
    feature_schema_version: str
    calibrated: bool = False
    allow_fixture_only: bool = False

    def __post_init__(self) -> None:
        for name in ("purpose", "version", "readiness", "feature_schema_version"):
            if not getattr(self, name):
                raise ValueError(f"{name} must be non-empty")
        if self.readiness not in MODEL_READINESS_VALUES:
            raise ValueError("unsupported runtime model readiness")
        if not isinstance(self.calibrated, bool) or not isinstance(self.allow_fixture_only, bool):
            raise ValueError("runtime model flags must be boolean")

    def can_serve(self, serving_feature_schema_version: str) -> bool:
        schema_matches = self.feature_schema_version == serving_feature_schema_version
        readiness_allows = self.readiness == "ACTIVE" or (
            self.readiness == "FIXTURE_ONLY" and self.allow_fixture_only
        )
        return schema_matches and readiness_allows


class GuardedEtaPredictor:
    """Readiness/schema/freshness gate for one ETA source."""

    def __init__(
        self,
        predictor: EtaPredictor,
        spec: RuntimeModelSpec,
        *,
        serving_feature_schema_version: str,
        required_source: str,
        max_input_age_seconds: int | None,
    ) -> None:
        if spec.purpose != "BUS_ETA":
            raise ValueError("ETA runtime spec purpose must be BUS_ETA")
        if required_source not in {"POSITION_MODEL", "HISTORICAL"}:
            raise ValueError("guarded ETA source must be model or historical")
        if max_input_age_seconds is not None and max_input_age_seconds <= 0:
            raise ValueError("max_input_age_seconds must be positive")
        self._predictor = predictor
        self._spec = spec
        self._serving_schema = serving_feature_schema_version
        self._required_source = required_source
        self._max_input_age_seconds = max_input_age_seconds

    def predict(self, value: EtaPredictorInput) -> EtaPrediction | None:
        if not self._spec.can_serve(self._serving_schema):
            return None
        if self._input_is_stale(value):
            return None
        prediction = self._predictor.predict(value)
        if prediction is None:
            return None
        if prediction.source != self._required_source:
            return None
        if prediction.model_version != self._spec.version:
            return None
        return replace(prediction, model_readiness=self._spec.readiness)

    def _input_is_stale(self, value: EtaPredictorInput) -> bool:
        if self._max_input_age_seconds is None or value.prediction_at is None:
            return False
        age = (value.prediction_at - value.observed_at).total_seconds()
        return age > self._max_input_age_seconds


class EtaFallbackChain:
    """Position model → historical proxy → unknown (`None`)."""

    def __init__(self, position_model: EtaPredictor, historical: EtaPredictor) -> None:
        self._position_model = position_model
        self._historical = historical

    def predict(self, value: EtaPredictorInput) -> EtaPrediction | None:
        position = self._position_model.predict(value)
        if position is not None:
            if position.source != "POSITION_MODEL":
                raise ValueError("position ETA predictor returned the wrong source")
            if "FEATURE_OUT_OF_DISTRIBUTION" not in position.warnings:
                return position
        historical = self._historical.predict(value)
        if historical is not None and historical.source != "HISTORICAL":
            raise ValueError("historical ETA predictor returned the wrong source")
        if position is not None and historical is not None:
            historical = replace(
                historical,
                warnings=tuple(
                    sorted(set(historical.warnings) | {"FEATURE_OUT_OF_DISTRIBUTION"})
                ),
            )
        return historical


@dataclass(frozen=True, slots=True)
class RawSeatRiskScore:
    no_seat_score: float
    low_seat2_score: float
    low_seat5_score: float | None
    confidence: float
    out_of_distribution: bool = False

    def __post_init__(self) -> None:
        require_probability(self.no_seat_score, "raw no-seat score")
        require_probability(self.low_seat2_score, "raw low-seat-2 score")
        if self.low_seat5_score is not None:
            require_probability(self.low_seat5_score, "raw low-seat-5 score")
        require_probability(self.confidence, "raw Seat Risk confidence")
        if not isinstance(self.out_of_distribution, bool):
            raise ValueError("out_of_distribution must be boolean")


class SeatRiskScorer(Protocol):
    def score(self, value: SeatRiskPredictorInput) -> RawSeatRiskScore | None: ...


class ProbabilityCalibrator(Protocol):
    def calibrate(self, value: float) -> float: ...


@dataclass(frozen=True, slots=True)
class IdentityProbabilityCalibrator:
    """Explicit test/baseline calibrator; production metadata must still opt in."""

    def calibrate(self, value: float) -> float:
        require_probability(value, "calibration input")
        return value


class CalibratedSeatRiskPredictor:
    """Calibrated Seat Risk port with readiness/schema/OOD fallback."""

    def __init__(
        self,
        scorer: SeatRiskScorer,
        spec: RuntimeModelSpec,
        *,
        serving_feature_schema_version: str,
        no_seat_calibrator: ProbabilityCalibrator,
        low_seat2_calibrator: ProbabilityCalibrator,
        low_seat5_calibrator: ProbabilityCalibrator | None,
        fallback: SeatRiskPredictor | None = None,
        origin: str = "MODEL_PREDICTED",
    ) -> None:
        if spec.purpose != "SEAT_RISK":
            raise ValueError("Seat runtime spec purpose must be SEAT_RISK")
        if origin not in {"MODEL_PREDICTED", "HISTORICAL_PROXY"}:
            raise ValueError("unsupported Seat Risk runtime origin")
        self._scorer = scorer
        self._spec = spec
        self._serving_schema = serving_feature_schema_version
        self._no_seat_calibrator = no_seat_calibrator
        self._low_seat2_calibrator = low_seat2_calibrator
        self._low_seat5_calibrator = low_seat5_calibrator
        self._fallback = fallback
        self._origin = origin

    def predict(self, value: SeatRiskPredictorInput) -> SeatRiskPrediction | None:
        if not self._spec.calibrated or not self._spec.can_serve(self._serving_schema):
            return self._fallback_prediction(value)
        raw = self._scorer.score(value)
        if raw is None:
            return self._fallback_prediction(value)
        if raw.out_of_distribution:
            return self._fallback_prediction(value, warning="FEATURE_OUT_OF_DISTRIBUTION")
        try:
            no_seat = self._calibrated(self._no_seat_calibrator, raw.no_seat_score)
            low_seat2 = max(
                no_seat,
                self._calibrated(self._low_seat2_calibrator, raw.low_seat2_score),
            )
            low_seat5 = None
            if raw.low_seat5_score is not None:
                if self._low_seat5_calibrator is None:
                    return self._fallback_prediction(value)
                low_seat5 = max(
                    low_seat2,
                    self._calibrated(self._low_seat5_calibrator, raw.low_seat5_score),
                )
        except (TypeError, ValueError, OverflowError):
            return self._fallback_prediction(value)

        return SeatRiskPrediction(
            no_seat_probability=no_seat,
            low_seat2_probability=low_seat2,
            low_seat5_probability=low_seat5,
            model_version=self._spec.version,
            confidence=raw.confidence,
            origin=self._origin,
            model_readiness=self._spec.readiness,
        )

    @staticmethod
    def _calibrated(calibrator: ProbabilityCalibrator, value: float) -> float:
        calibrated = calibrator.calibrate(value)
        if not isinstance(calibrated, (float, int)) or not isfinite(calibrated):
            raise ValueError("calibrator returned a non-finite value")
        require_probability(float(calibrated), "calibrated probability")
        return float(calibrated)

    def _fallback_prediction(
        self, value: SeatRiskPredictorInput, *, warning: str | None = None
    ) -> SeatRiskPrediction | None:
        if self._fallback is None:
            return None
        prediction = self._fallback.predict(value)
        if prediction is None or warning is None:
            return prediction
        return replace(prediction, warnings=tuple(sorted(set(prediction.warnings) | {warning})))
