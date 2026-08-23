"""Optional LightGBM adapter; importing this module never implies readiness."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from math import isfinite
from typing import Iterable, Mapping

from ..data_quality.dataset_foundation import NullableTarget
from ..feature_encoding import encode_feature_mapping
from .model_foundation import ModelFoundationError


class LightGbmUnavailable(ModelFoundationError):
    pass


@dataclass(frozen=True, slots=True)
class LightGbmCapability:
    installed: bool
    training_enabled: bool
    production_ready: bool
    reason: str


def select_observed_seat_ordinal_training_rows(
    *,
    rows: Iterable[Mapping[str, object]],
    targets: Iterable[NullableTarget[int]],
) -> tuple[tuple[Mapping[str, object], ...], tuple[int, ...]]:
    """Exclude unobserved future Seat targets without coercing them to class zero."""

    row_values = tuple(rows)
    target_values = tuple(targets)
    if len(row_values) != len(target_values):
        raise ModelFoundationError("Seat training rows and nullable targets must align")
    selected_rows: list[Mapping[str, object]] = []
    selected_labels: list[int] = []
    for row, target in zip(row_values, target_values, strict=True):
        if type(target) is not NullableTarget:
            raise ModelFoundationError("Seat training target must use NullableTarget")
        if not target.has_target:
            continue
        label = target.value
        if isinstance(label, bool) or not isinstance(label, int) or label not in range(4):
            raise ModelFoundationError("Seat ordinal training target must be class 0..3")
        selected_rows.append(row)
        selected_labels.append(label)
    return tuple(selected_rows), tuple(selected_labels)


def capability(*, training_enabled: bool = False) -> LightGbmCapability:
    installed = find_spec("lightgbm") is not None
    reason = (
        "EXPLICIT_TRAINING_DISABLED" if installed and not training_enabled
        else "DEPENDENCY_UNAVAILABLE" if not installed
        else "OFFLINE_TRAINING_ALLOWED_NOT_PRODUCTION_APPROVED"
    )
    return LightGbmCapability(installed, training_enabled and installed, False, reason)


def train_to_native_text(
    *, rows: Iterable[Mapping[str, object]], labels: Iterable[float],
    family: str | None = None, feature_schema_version: str | None = None,
    feature_names: tuple[str, ...], output_path: Path,
    parameters: Mapping[str, object], training_enabled: bool = False,
    lightgbm_module: object | None = None,
) -> None:
    """Train only with explicit data and opt-in, saving LightGBM native text.

    Registration, validation and activation are intentionally separate operations.
    """

    if not training_enabled:
        raise LightGbmUnavailable("EXPLICIT_TRAINING_DISABLED")
    if lightgbm_module is None:
        state = capability(training_enabled=True)
        if not state.training_enabled:
            raise LightGbmUnavailable(state.reason)
        import lightgbm as lightgbm_module  # type: ignore[import-not-found,no-redef]
    if family not in {"ETA", "SEAT_RISK"} or not feature_schema_version:
        raise ModelFoundationError(
            "training requires an exact model family and feature schema version"
        )
    row_values = tuple(rows)
    label_values = tuple(labels)
    if not row_values or len(row_values) != len(label_values):
        raise ModelFoundationError("training requires equal non-empty rows and labels")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(float(value))
        for value in label_values
    ):
        raise ModelFoundationError("training labels must be finite numeric values")
    objective = parameters.get("objective")
    if family == "ETA":
        if objective != "regression" or any(float(value) < 0 for value in label_values):
            raise ModelFoundationError(
                "ETA native training requires non-negative duration labels and regression objective"
            )
    elif (
        objective != "multiclass"
        or parameters.get("num_class") != 4
        or any(
            isinstance(value, bool)
            or int(value) != float(value)
            or int(value) not in {0, 1, 2, 3}
            for value in label_values
        )
    ):
        raise ModelFoundationError(
            "Seat Risk native training requires ordinal classes 0..3 and multiclass num_class=4"
        )
    if output_path.suffix.lower() != ".txt" or output_path.exists():
        raise ModelFoundationError("training output must be a new .txt artifact path")
    matrix = [
        list(
            encode_feature_mapping(
                family=family,
                feature_schema_version=feature_schema_version,
                feature_names=feature_names,
                values=row,
            )
        )
        for row in row_values
    ]
    dataset_factory = getattr(lightgbm_module, "Dataset", None)
    train = getattr(lightgbm_module, "train", None)
    if not callable(dataset_factory) or not callable(train):
        raise LightGbmUnavailable("LIGHTGBM_MODULE_INTERFACE_INVALID")
    dataset = dataset_factory(
        matrix, label=list(label_values), feature_name=list(feature_names)
    )
    booster = train(dict(parameters), dataset)
    if not callable(getattr(booster, "save_model", None)):
        raise LightGbmUnavailable("LIGHTGBM_BOOSTER_INTERFACE_INVALID")
    booster.save_model(str(output_path))


__all__ = [
    "LightGbmCapability",
    "LightGbmUnavailable",
    "capability",
    "select_observed_seat_ordinal_training_rows",
    "train_to_native_text",
]
