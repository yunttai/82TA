"""Packaged prediction/feature drift summaries with sample sufficiency."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import mean
from typing import Iterable, Mapping


class DriftError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NumericDrift:
    feature_name: str
    baseline_count: int
    current_count: int
    baseline_mean: float
    current_mean: float
    standardized_mean_shift: float
    severity: str


def numeric_mean_drift(
    feature_name: str, baseline: Iterable[float], current: Iterable[float], *,
    reference_scale: float, warning_threshold: float = 0.25,
    critical_threshold: float = 0.5, minimum_count: int = 20,
) -> NumericDrift:
    baseline_values = tuple(float(value) for value in baseline)
    current_values = tuple(float(value) for value in current)
    if any(not isfinite(value) for value in (*baseline_values, *current_values)):
        raise DriftError("drift inputs must be finite")
    if reference_scale <= 0 or warning_threshold < 0 or critical_threshold < warning_threshold:
        raise DriftError("drift thresholds and reference scale are invalid")
    if not feature_name.strip():
        raise DriftError("drift feature name must not be blank")
    if not baseline_values or not current_values:
        raise DriftError("drift requires baseline and current observations")
    shift = abs(mean(current_values) - mean(baseline_values)) / reference_scale
    if min(len(baseline_values), len(current_values)) < minimum_count:
        severity = "INSUFFICIENT_DATA"
    elif shift >= critical_threshold:
        severity = "CRITICAL"
    elif shift >= warning_threshold:
        severity = "WARNING"
    else:
        severity = "OK"
    return NumericDrift(
        feature_name, len(baseline_values), len(current_values),
        mean(baseline_values), mean(current_values), shift, severity,
    )


@dataclass(frozen=True, slots=True)
class DelayedLabelAudit:
    total_predictions: int
    observed_labels: int
    coverage: float
    status: str


def delayed_label_coverage(
    prediction_ids: Iterable[str], labels_by_prediction: Mapping[str, object | None], *,
    minimum_coverage: float,
) -> DelayedLabelAudit:
    ids = tuple(prediction_ids)
    if len(set(ids)) != len(ids):
        raise DriftError("prediction ids must be unique")
    if not 0 <= minimum_coverage <= 1:
        raise DriftError("minimum label coverage must be in [0, 1]")
    observed = sum(labels_by_prediction.get(item) is not None for item in ids)
    coverage = observed / len(ids) if ids else 0.0
    return DelayedLabelAudit(
        len(ids), observed, coverage,
        "PASS" if ids and coverage >= minimum_coverage else "LOW_COVERAGE",
    )
