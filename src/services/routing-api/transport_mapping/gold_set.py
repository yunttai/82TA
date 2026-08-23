"""Deterministic gold-set evaluation for the HIGH precision release gate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import CanonicalRouteCandidate, MappingGrade, MappingResult, ProviderMappingInput
from .scoring import DEFAULT_MAPPING_VERSION, map_candidate


@dataclass(frozen=True, slots=True)
class GoldSetCase:
    case_id: str
    source: ProviderMappingInput
    candidate: CanonicalRouteCandidate
    expected_match: bool
    review: "GoldReviewProvenance | None" = None

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must be non-blank")


@dataclass(frozen=True, slots=True)
class GoldReviewProvenance:
    reviewer_role: str
    reviewed_at: datetime
    source_kind: str = "SANITIZED_REVIEWED_FIXTURE"

    def __post_init__(self) -> None:
        if not self.reviewer_role.strip():
            raise ValueError("reviewer_role must be non-blank")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        if not self.source_kind.strip():
            raise ValueError("source_kind must be non-blank")


@dataclass(frozen=True, slots=True)
class ConfusionMatrix:
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int


@dataclass(frozen=True, slots=True)
class ProviderGoldMetrics:
    provider: str
    total: int
    confusion: ConfusionMatrix
    precision: float | None
    coverage: float | None


@dataclass(frozen=True, slots=True)
class GoldSetMetrics:
    total: int
    expected_matches: int
    high_predictions: int
    high_true_positives: int
    high_false_positives: int
    high_precision: float | None
    high_coverage: float | None
    gate_accuracy: float
    passes_recommended_precision_gate: bool
    confusion: ConfusionMatrix
    reviewed_cases: int
    provider_slices: tuple[ProviderGoldMetrics, ...]


@dataclass(frozen=True, slots=True)
class GoldSetEvaluation:
    results: tuple[tuple[str, MappingResult], ...]
    metrics: GoldSetMetrics


def _confusion(
    cases: tuple[GoldSetCase, ...],
    outputs: tuple[tuple[str, MappingResult], ...],
) -> ConfusionMatrix:
    expected = {case.case_id: case.expected_match for case in cases}
    predicted = {
        case_id: result.grade is MappingGrade.HIGH
        for case_id, result in outputs
    }
    return ConfusionMatrix(
        true_positive=sum(expected[key] and predicted[key] for key in expected),
        false_positive=sum(not expected[key] and predicted[key] for key in expected),
        true_negative=sum(not expected[key] and not predicted[key] for key in expected),
        false_negative=sum(expected[key] and not predicted[key] for key in expected),
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _provider_slices(
    cases: tuple[GoldSetCase, ...],
    outputs: tuple[tuple[str, MappingResult], ...],
) -> tuple[ProviderGoldMetrics, ...]:
    by_id = dict(outputs)
    providers = sorted({case.source.provider for case in cases})
    slices: list[ProviderGoldMetrics] = []
    for provider in providers:
        provider_cases = tuple(case for case in cases if case.source.provider == provider)
        provider_outputs = tuple((case.case_id, by_id[case.case_id]) for case in provider_cases)
        confusion = _confusion(provider_cases, provider_outputs)
        slices.append(
            ProviderGoldMetrics(
                provider=provider,
                total=len(provider_cases),
                confusion=confusion,
                precision=_ratio(
                    confusion.true_positive,
                    confusion.true_positive + confusion.false_positive,
                ),
                coverage=_ratio(
                    confusion.true_positive,
                    confusion.true_positive + confusion.false_negative,
                ),
            )
        )
    return tuple(slices)


def evaluate_gold_set(
    cases: tuple[GoldSetCase, ...],
    *,
    evaluated_at: datetime,
    mapping_version: str = DEFAULT_MAPPING_VERSION,
    recommended_precision: float = 0.995,
) -> GoldSetEvaluation:
    if not 0 <= recommended_precision <= 1:
        raise ValueError("recommended_precision must be between 0 and 1")
    case_ids = tuple(case.case_id for case in cases)
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("gold-set case_id values must be unique")
    outputs = tuple(
        (
            case.case_id,
            map_candidate(
                case.source,
                case.candidate,
                evaluated_at=evaluated_at,
                mapping_version=mapping_version,
            ),
        )
        for case in cases
    )
    expected = {case.case_id: case.expected_match for case in cases}
    confusion = _confusion(cases, outputs)
    high = [(case_id, result) for case_id, result in outputs if result.grade is MappingGrade.HIGH]
    true_positive = confusion.true_positive
    false_positive = confusion.false_positive
    expected_matches = true_positive + confusion.false_negative
    precision = _ratio(true_positive, true_positive + false_positive)
    coverage = _ratio(true_positive, expected_matches)
    correct_gate = sum(
        1
        for case_id, result in outputs
        if result.allows_bus_intelligence == expected[case_id]
    )
    gate_accuracy = round(correct_gate / len(cases), 6) if cases else 1.0
    metrics = GoldSetMetrics(
        total=len(cases),
        expected_matches=expected_matches,
        high_predictions=len(high),
        high_true_positives=true_positive,
        high_false_positives=false_positive,
        high_precision=precision,
        high_coverage=coverage,
        gate_accuracy=gate_accuracy,
        passes_recommended_precision_gate=(
            precision is not None and precision >= recommended_precision
        ),
        confusion=confusion,
        reviewed_cases=sum(case.review is not None for case in cases),
        provider_slices=_provider_slices(cases, outputs),
    )
    return GoldSetEvaluation(results=outputs, metrics=metrics)
