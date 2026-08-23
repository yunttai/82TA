"""Fail-closed native LightGBM loaders for verified worker artifact bundles.

This module is inert on import.  LightGBM is imported only by ``load`` after the
composition factory has verified every bundle digest and lifecycle identity.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
from math import ceil, isfinite
from pathlib import Path
from typing import Any, Mapping

from bus_intelligence_core import EtaNativePrediction, SeatRiskNativePrediction

from .feature_encoding import (
    FEATURE_ENCODING_VERSION,
    FeatureEncodingError,
    encode_feature_values,
    feature_schema_document,
)
from .model_serving import ModelServingConfigurationError
from .model_jobs.evaluation import (
    EvaluationError,
    IsotonicCalibrator,
    PlattCalibrator,
)


_MAX_JSON_BYTES = 1_048_576
_MAX_ISOTONIC_KNOTS = 1_024


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ModelServingConfigurationError("native runtime JSON cannot be a symlink")
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or resolved.stat().st_size > _MAX_JSON_BYTES:
            raise ModelServingConfigurationError(
                "native runtime JSON is invalid or exceeds its byte limit"
            )

        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON key: {key}")
                result[key] = value
            return result

        value = json.loads(
            resolved.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=_reject_constant,
        )
    except ModelServingConfigurationError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ModelServingConfigurationError(
            "native runtime metadata must be strict UTF-8 JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ModelServingConfigurationError("native runtime metadata must be an object")
    return value


def _number(value: object, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelServingConfigurationError(f"{name} must be numeric")
    result = float(value)
    if not isfinite(result) or (minimum is not None and result < minimum):
        raise ModelServingConfigurationError(f"{name} is outside its valid range")
    return result


def _probability(value: object, name: str) -> float:
    result = _number(value, name, minimum=0)
    if result > 1:
        raise ModelServingConfigurationError(f"{name} must be in [0, 1]")
    return result


def _verify_schema(
    *, path: Path, family: str, version: str, names: tuple[str, ...]
) -> None:
    value = _load_json(path)
    if value != feature_schema_document(family=family):
        raise ModelServingConfigurationError(
            "feature schema document does not match the versioned encoder"
        )
    if (
        value["fullFeatureSchemaVersion"] != version
        or tuple(value["orderedFeatureNames"]) != names
        or value["encodingVersion"] != FEATURE_ENCODING_VERSION
    ):
        raise ModelServingConfigurationError("feature encoding metadata drift")


def _load_booster(
    *,
    artifact_path: Path,
    artifact_format: str,
    feature_names: tuple[str, ...],
    family: str,
    lightgbm_module: object | None,
) -> object:
    if artifact_format != "LIGHTGBM_TEXT" or artifact_path.suffix.lower() != ".txt":
        raise ModelServingConfigurationError(
            "native LightGBM loader supports only verified text artifacts"
        )
    if artifact_path.is_symlink():
        raise ModelServingConfigurationError("native model artifact cannot be a symlink")
    try:
        model_path = artifact_path.resolve(strict=True)
    except OSError as exc:
        raise ModelServingConfigurationError("native model artifact is unavailable") from exc
    module = lightgbm_module
    if module is None:
        try:
            module = importlib.import_module("lightgbm")
        except (ImportError, ModuleNotFoundError) as exc:
            raise ModelServingConfigurationError(
                "optional LightGBM runtime dependency is unavailable"
            ) from exc
    booster_factory = getattr(module, "Booster", None)
    if not callable(booster_factory):
        raise ModelServingConfigurationError("LightGBM Booster interface is unavailable")
    try:
        booster = booster_factory(model_file=str(model_path))
        internal_names = tuple(booster.feature_name())
    except Exception as exc:
        raise ModelServingConfigurationError("LightGBM native model loading failed") from exc
    if internal_names != feature_names or not callable(getattr(booster, "predict", None)):
        raise ModelServingConfigurationError(
            "LightGBM internal feature names do not match the attested schema"
        )
    parameters = getattr(booster, "params", None)
    if not isinstance(parameters, Mapping):
        raise ModelServingConfigurationError(
            "LightGBM objective metadata is unavailable"
        )
    if family == "ETA":
        if parameters.get("objective") != "regression":
            raise ModelServingConfigurationError(
                "ETA LightGBM artifact must be scalar regression"
            )
    else:
        try:
            num_class = int(parameters.get("num_class"))
        except (TypeError, ValueError) as exc:
            raise ModelServingConfigurationError(
                "Seat Risk LightGBM num_class metadata is invalid"
            ) from exc
        if parameters.get("objective") != "multiclass" or num_class != 4:
            raise ModelServingConfigurationError(
                "Seat Risk LightGBM artifact must be four-class ordinal multiclass"
            )
    return booster


def _raw_outputs(booster: object, encoded: tuple[float, ...]) -> tuple[float, ...]:
    try:
        raw: object = booster.predict([list(encoded)])
        tolist = getattr(raw, "tolist", None)
        if callable(tolist):
            raw = tolist()
        if not isinstance(raw, (list, tuple)) or len(raw) != 1:
            raise ValueError("prediction must contain exactly one row")
        row: object = raw[0]
        if isinstance(row, (list, tuple)):
            values = tuple(row)
        else:
            values = (row,)
        numeric = tuple(_number(value, "native model output") for value in values)
    except ModelServingConfigurationError:
        raise
    except Exception as exc:
        raise ModelServingConfigurationError(
            "LightGBM output shape or value is invalid"
        ) from exc
    return numeric


@dataclass(frozen=True, slots=True)
class _EtaCalibration:
    method: str
    confidence: float
    p90_offset_seconds: float | None


def _eta_calibration(path: Path, method: str) -> _EtaCalibration:
    value = _load_json(path)
    common = {"schemaVersion", "family", "method", "confidence"}
    expected = common | {"p90OffsetSeconds"}
    if set(value) != expected:
        raise ModelServingConfigurationError("ETA calibration JSON keys do not match schema")
    if (
        value["schemaVersion"] != "eta-calibration-v1"
        or value["family"] != "ETA"
        or value["method"] != method
        or method != "CONFORMAL"
    ):
        raise ModelServingConfigurationError("ETA calibration identity mismatch")
    offset = _number(value["p90OffsetSeconds"], "p90OffsetSeconds", minimum=0)
    return _EtaCalibration(method, _probability(value["confidence"], "confidence"), offset)


@dataclass(frozen=True, slots=True)
class _SeatCalibration:
    method: str
    confidence: float
    parameters: tuple[PlattCalibrator | IsotonicCalibrator, ...]


def _seat_calibration(path: Path, method: str) -> _SeatCalibration:
    value = _load_json(path)
    if set(value) != {"schemaVersion", "family", "method", "confidence", "parameters"}:
        raise ModelServingConfigurationError("Seat calibration JSON keys do not match schema")
    if (
        value["schemaVersion"] != "seat-risk-calibration-v1"
        or value["family"] != "SEAT_RISK"
        or value["method"] != method
        or method not in {"PLATT", "ISOTONIC"}
    ):
        raise ModelServingConfigurationError("Seat calibration identity mismatch")
    raw_parameters = value["parameters"]
    if not isinstance(raw_parameters, list) or len(raw_parameters) != 3:
        raise ModelServingConfigurationError(
            "Seat calibration requires exactly three target calibrators"
        )
    parameters: list[PlattCalibrator | IsotonicCalibrator] = []
    try:
        for item in raw_parameters:
            if not isinstance(item, Mapping):
                raise ModelServingConfigurationError("Seat calibrator must be an object")
            if method == "PLATT":
                if set(item) != {"slope", "intercept"}:
                    raise ModelServingConfigurationError("Platt calibrator keys do not match schema")
                parameters.append(
                    PlattCalibrator(
                        _number(item["slope"], "Platt slope"),
                        _number(item["intercept"], "Platt intercept"),
                    )
                )
            else:
                if set(item) != {"x", "y"}:
                    raise ModelServingConfigurationError("isotonic calibrator keys do not match schema")
                x_values = item["x"]
                y_values = item["y"]
                if (
                    not isinstance(x_values, list)
                    or not isinstance(y_values, list)
                    or len(x_values) != len(y_values)
                    or len(x_values) < 2
                    or len(x_values) > _MAX_ISOTONIC_KNOTS
                ):
                    raise ModelServingConfigurationError("isotonic knots are invalid")
                parameters.append(
                    IsotonicCalibrator(
                        tuple(_number(v, "isotonic x") for v in x_values),
                        tuple(_probability(v, "isotonic y") for v in y_values),
                    )
                )
    except EvaluationError as exc:
        raise ModelServingConfigurationError("Seat calibration parameters are invalid") from exc
    return _SeatCalibration(
        method,
        _probability(value["confidence"], "confidence"),
        tuple(parameters),
    )


@dataclass(frozen=True, slots=True)
class _EtaSession:
    booster: object
    calibration: _EtaCalibration
    feature_schema_version: str
    feature_names: tuple[str, ...]

    def predict(self, values: tuple[object, ...]) -> EtaNativePrediction | None:
        try:
            encoded = encode_feature_values(
                family="ETA",
                feature_schema_version=self.feature_schema_version,
                feature_names=self.feature_names,
                values=values,
            )
            raw = _raw_outputs(self.booster, encoded)
            if len(raw) != 1 or self.calibration.p90_offset_seconds is None:
                return None
            p50 = ceil(_number(raw[0], "ETA p50", minimum=0))
            p90 = ceil(raw[0] + self.calibration.p90_offset_seconds)
            if p90 < p50:
                return None
            return EtaNativePrediction(p50, p90, self.calibration.confidence)
        except (FeatureEncodingError, ModelServingConfigurationError, ValueError, OverflowError):
            return None


@dataclass(frozen=True, slots=True)
class _SeatSession:
    booster: object
    calibration: _SeatCalibration
    feature_schema_version: str
    feature_names: tuple[str, ...]

    def predict(self, values: tuple[object, ...]) -> SeatRiskNativePrediction | None:
        try:
            encoded = encode_feature_values(
                family="SEAT_RISK",
                feature_schema_version=self.feature_schema_version,
                feature_names=self.feature_names,
                values=values,
            )
            raw = _raw_outputs(self.booster, encoded)
            if len(raw) != 4:
                return None
            class_probabilities = tuple(
                _probability(value, "Seat ordinal class probability") for value in raw
            )
            if abs(sum(class_probabilities) - 1.0) > 1e-6:
                return None
            cumulative = (
                class_probabilities[0],
                class_probabilities[0] + class_probabilities[1],
                class_probabilities[0]
                + class_probabilities[1]
                + class_probabilities[2],
            )
            probabilities = tuple(
                parameter.transform(value)
                for value, parameter in zip(
                    cumulative, self.calibration.parameters, strict=True
                )
            )
            if not probabilities[0] <= probabilities[1] <= probabilities[2]:
                return None
            return SeatRiskNativePrediction(
                probabilities[0],
                probabilities[1],
                probabilities[2],
                self.calibration.confidence,
            )
        except (FeatureEncodingError, ModelServingConfigurationError, ValueError, OverflowError):
            return None


@dataclass(frozen=True, slots=True)
class LightGbmEtaRuntimeLoader:
    """Concrete ETA loader; dependency injection is test-only and explicit."""

    lightgbm_module: object | None = None

    def load(
        self,
        *,
        artifact_path: Path,
        artifact_format: str,
        calibration_path: Path,
        calibration_method: str,
        feature_schema_path: Path,
        feature_schema_version: str,
        feature_names: tuple[str, ...],
    ) -> _EtaSession:
        _verify_schema(
            path=feature_schema_path,
            family="ETA",
            version=feature_schema_version,
            names=feature_names,
        )
        calibration = _eta_calibration(calibration_path, calibration_method)
        booster = _load_booster(
            artifact_path=artifact_path,
            artifact_format=artifact_format,
            feature_names=feature_names,
            family="ETA",
            lightgbm_module=self.lightgbm_module,
        )
        return _EtaSession(booster, calibration, feature_schema_version, feature_names)


@dataclass(frozen=True, slots=True)
class LightGbmSeatRiskRuntimeLoader:
    """Concrete Seat Risk loader with exact three-target calibration."""

    lightgbm_module: object | None = None

    def load(
        self,
        *,
        artifact_path: Path,
        artifact_format: str,
        calibration_path: Path,
        calibration_method: str,
        feature_schema_path: Path,
        feature_schema_version: str,
        feature_names: tuple[str, ...],
    ) -> _SeatSession:
        _verify_schema(
            path=feature_schema_path,
            family="SEAT_RISK",
            version=feature_schema_version,
            names=feature_names,
        )
        calibration = _seat_calibration(calibration_path, calibration_method)
        booster = _load_booster(
            artifact_path=artifact_path,
            artifact_format=artifact_format,
            feature_names=feature_names,
            family="SEAT_RISK",
            lightgbm_module=self.lightgbm_module,
        )
        return _SeatSession(booster, calibration, feature_schema_version, feature_names)


__all__ = ["LightGbmEtaRuntimeLoader", "LightGbmSeatRiskRuntimeLoader"]
