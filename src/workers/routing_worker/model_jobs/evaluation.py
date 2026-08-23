"""Packaged deterministic ETA/Seat evaluation and calibration utilities."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from math import exp, isfinite, log
from statistics import mean, median
from typing import Callable, Generic, Iterable, Protocol, TypeVar


class EvaluationError(ValueError):
    pass


def _probability(value: float) -> float:
    if not isfinite(value) or not 0 <= value <= 1:
        raise EvaluationError("probability must be finite and in [0, 1]")
    return value


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        raise EvaluationError("quantile requires observations")
    if not 0 <= probability <= 1:
        raise EvaluationError("quantile probability must be in [0, 1]")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(probability * len(ordered) + 0.999999) - 1))
    return ordered[index]


@dataclass(frozen=True, slots=True)
class EtaPrediction:
    actual_seconds: float
    predicted_seconds: float
    lower_seconds: float | None = None
    upper_seconds: float | None = None

    def __post_init__(self) -> None:
        values = (self.actual_seconds, self.predicted_seconds)
        if any(not isfinite(value) or value < 0 for value in values):
            raise EvaluationError("ETA actual and prediction must be finite and non-negative")
        if (self.lower_seconds is None) != (self.upper_seconds is None):
            raise EvaluationError("ETA interval requires both bounds")
        if self.lower_seconds is not None:
            if not 0 <= self.lower_seconds <= self.upper_seconds:  # type: ignore[operator]
                raise EvaluationError("ETA interval bounds are invalid")


@dataclass(frozen=True, slots=True)
class EtaMetrics:
    count: int
    mae_seconds: float
    median_absolute_error_seconds: float
    p90_absolute_error_seconds: float
    interval_coverage: float | None
    mean_interval_width_seconds: float | None


def evaluate_eta(rows: Iterable[EtaPrediction]) -> EtaMetrics:
    values = tuple(rows)
    if not values:
        raise EvaluationError("ETA evaluation requires rows")
    errors = [abs(item.predicted_seconds - item.actual_seconds) for item in values]
    intervals = [item for item in values if item.lower_seconds is not None]
    coverage: float | None = None
    width: float | None = None
    if intervals:
        coverage = mean(
            float(item.lower_seconds <= item.actual_seconds <= item.upper_seconds)  # type: ignore[operator]
            for item in intervals
        )
        width = mean(item.upper_seconds - item.lower_seconds for item in intervals)  # type: ignore[operator]
    return EtaMetrics(
        len(values), mean(errors), median(errors), _quantile(errors, 0.9), coverage, width
    )


def conformal_absolute_radius(
    actual: Iterable[float], predicted: Iterable[float], *, coverage: float = 0.9
) -> float:
    actual_values = tuple(actual)
    predicted_values = tuple(predicted)
    if len(actual_values) != len(predicted_values) or not actual_values:
        raise EvaluationError("conformal inputs must have equal non-zero length")
    if not 0 < coverage < 1:
        raise EvaluationError("conformal coverage must be between zero and one")
    residuals = [abs(left - right) for left, right in zip(actual_values, predicted_values, strict=True)]
    finite_sample_level = min(1.0, ((len(residuals) + 1) * coverage) / len(residuals))
    return _quantile(residuals, finite_sample_level)


def conformal_interval(prediction: float, radius: float) -> tuple[float, float]:
    if prediction < 0 or radius < 0 or not isfinite(prediction + radius):
        raise EvaluationError("conformal interval inputs must be finite and non-negative")
    return max(0.0, prediction - radius), prediction + radius


def quantile_interval(lower: float, median_value: float, upper: float) -> tuple[float, float, float]:
    """Validate lower/median/upper quantile output without silently sorting it."""

    if any(not isfinite(value) or value < 0 for value in (lower, median_value, upper)):
        raise EvaluationError("quantile ETA outputs must be finite and non-negative")
    if not lower <= median_value <= upper:
        raise EvaluationError("quantile ETA outputs must be monotonic")
    return lower, median_value, upper


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    lower: float
    upper: float
    count: int
    mean_probability: float
    positive_rate: float


@dataclass(frozen=True, slots=True)
class SeatMetrics:
    count: int
    positives: int
    pr_auc: float
    brier_score: float
    ece: float
    precision_at_threshold: float
    recall_at_threshold: float
    reliability: tuple[ReliabilityBin, ...]


def _average_precision(labels: tuple[bool, ...], probabilities: tuple[float, ...]) -> float:
    positives = sum(labels)
    if positives == 0:
        return 0.0
    ranked = sorted(zip(probabilities, labels, strict=True), key=lambda item: (-item[0], not item[1]))
    true_positives = 0
    precision_sum = 0.0
    for rank, (_, label) in enumerate(ranked, start=1):
        if label:
            true_positives += 1
            precision_sum += true_positives / rank
    return precision_sum / positives


def evaluate_seat(
    labels: Iterable[bool], probabilities: Iterable[float], *, bins: int = 10,
    decision_threshold: float = 0.5,
) -> SeatMetrics:
    labels_tuple = tuple(labels)
    probabilities_tuple = tuple(_probability(value) for value in probabilities)
    if len(labels_tuple) != len(probabilities_tuple) or not labels_tuple:
        raise EvaluationError("Seat evaluation inputs must have equal non-zero length")
    if bins <= 0:
        raise EvaluationError("reliability bins must be positive")
    _probability(decision_threshold)
    reliability: list[ReliabilityBin] = []
    weighted_gap = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        def in_bin(probability: float) -> bool:
            return lower <= probability <= upper if index == bins - 1 else lower <= probability < upper
        members = [
            (label, probability)
            for label, probability in zip(labels_tuple, probabilities_tuple, strict=True)
            if in_bin(probability)
        ]
        if not members:
            continue
        average_probability = mean(item[1] for item in members)
        positive_rate = mean(float(item[0]) for item in members)
        reliability.append(
            ReliabilityBin(lower, upper, len(members), average_probability, positive_rate)
        )
        weighted_gap += len(members) / len(labels_tuple) * abs(average_probability - positive_rate)
    predicted_positive = tuple(value >= decision_threshold for value in probabilities_tuple)
    tp = sum(predicted and label for predicted, label in zip(predicted_positive, labels_tuple, strict=True))
    fp = sum(predicted and not label for predicted, label in zip(predicted_positive, labels_tuple, strict=True))
    fn = sum(not predicted and label for predicted, label in zip(predicted_positive, labels_tuple, strict=True))
    return SeatMetrics(
        count=len(labels_tuple),
        positives=sum(labels_tuple),
        pr_auc=_average_precision(labels_tuple, probabilities_tuple),
        brier_score=mean((probability - float(label)) ** 2 for label, probability in zip(labels_tuple, probabilities_tuple, strict=True)),
        ece=weighted_gap,
        precision_at_threshold=tp / (tp + fp) if tp + fp else 0.0,
        recall_at_threshold=tp / (tp + fn) if tp + fn else 0.0,
        reliability=tuple(reliability),
    )


class ProbabilityCalibrator(Protocol):
    name: str

    def transform(self, probability: float) -> float: ...


@dataclass(frozen=True, slots=True)
class PlattCalibrator:
    slope: float
    intercept: float
    epsilon: float = 1e-12
    name: str = "PLATT"

    def __post_init__(self) -> None:
        if (
            not isfinite(self.slope)
            or not isfinite(self.intercept)
            or not isfinite(self.epsilon)
            or not 0 < self.epsilon < 0.5
        ):
            raise EvaluationError("Platt parameters must be finite with epsilon in (0, 0.5)")

    def transform(self, probability: float) -> float:
        value = min(1 - self.epsilon, max(self.epsilon, _probability(probability)))
        logit = log(value / (1 - value))
        return 1 / (1 + exp(-(self.slope * logit + self.intercept)))


@dataclass(frozen=True, slots=True)
class IsotonicCalibrator:
    thresholds: tuple[float, ...]
    calibrated: tuple[float, ...]
    name: str = "ISOTONIC"

    def __post_init__(self) -> None:
        if (
            len(self.thresholds) != len(self.calibrated)
            or not self.thresholds
            or len(self.thresholds) > 1_024
        ):
            raise EvaluationError("isotonic knots must have equal non-zero length")
        if any(
            right <= left
            for left, right in zip(self.thresholds, self.thresholds[1:])
        ):
            raise EvaluationError("isotonic thresholds must be strictly increasing")
        if tuple(sorted(self.calibrated)) != self.calibrated:
            raise EvaluationError("isotonic outputs must be non-decreasing")
        for value in (*self.thresholds, *self.calibrated):
            _probability(value)

    def transform(self, probability: float) -> float:
        value = _probability(probability)
        index = min(bisect_left(self.thresholds, value), len(self.calibrated) - 1)
        return self.calibrated[index]


T = TypeVar("T")
M = TypeVar("M")


@dataclass(frozen=True, slots=True)
class SliceMetric(Generic[M]):
    slice_key: str
    count: int
    metrics: M


def evaluate_slices(
    rows: Iterable[T], *, key: Callable[[T], str], evaluator: Callable[[tuple[T, ...]], M],
    minimum_count: int = 1,
) -> tuple[SliceMetric[M], ...]:
    if minimum_count <= 0:
        raise EvaluationError("minimum slice count must be positive")
    grouped: dict[str, list[T]] = {}
    for row in rows:
        grouped.setdefault(key(row), []).append(row)
    return tuple(
        SliceMetric(name, len(values), evaluator(tuple(values)))
        for name, values in sorted(grouped.items())
        if len(values) >= minimum_count
    )
