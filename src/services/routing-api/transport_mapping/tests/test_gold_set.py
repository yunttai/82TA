from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from transport_mapping.gold_set import GoldSetCase, evaluate_gold_set
from transport_mapping.models import CanonicalRouteCandidate, ProviderMappingInput
from transport_mapping.reviewed_gold import representative_reviewed_gold_cases


def test_gold_set_precision_gate_blocks_opposite_direction_and_branch(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    cases = (
        GoldSetCase("positive", provider_input, exact_candidate, True),
        GoldSetCase(
            "opposite-direction",
            provider_input,
            replace(exact_candidate, route_id="opposite", direction="하행"),
            False,
        ),
        GoldSetCase(
            "other-branch",
            provider_input,
            replace(exact_candidate, route_id="branch-b", branch_id="B"),
            False,
        ),
    )

    evaluation = evaluate_gold_set(cases, evaluated_at=evaluated_at)

    assert evaluation.metrics.high_true_positives == 1
    assert evaluation.metrics.high_false_positives == 0
    assert evaluation.metrics.high_precision == 1.0
    assert evaluation.metrics.high_coverage == 1.0
    assert evaluation.metrics.gate_accuracy == 1.0
    assert evaluation.metrics.passes_recommended_precision_gate is True


def test_empty_gold_set_does_not_claim_precision(evaluated_at: datetime) -> None:
    evaluation = evaluate_gold_set((), evaluated_at=evaluated_at)
    assert evaluation.metrics.high_precision is None
    assert evaluation.metrics.passes_recommended_precision_gate is False


def test_representative_reviewed_gold_reports_full_confusion_and_provider_slices(
    evaluated_at: datetime,
) -> None:
    cases = representative_reviewed_gold_cases()

    evaluation = evaluate_gold_set(cases, evaluated_at=evaluated_at)

    assert evaluation.metrics.total == 8
    assert evaluation.metrics.reviewed_cases == 8
    assert evaluation.metrics.confusion.true_positive == 3
    assert evaluation.metrics.confusion.false_positive == 0
    assert evaluation.metrics.confusion.true_negative == 5
    assert evaluation.metrics.confusion.false_negative == 0
    assert evaluation.metrics.high_precision == 1.0
    assert evaluation.metrics.high_coverage == 1.0
    assert evaluation.metrics.gate_accuracy == 1.0
    assert evaluation.metrics.passes_recommended_precision_gate is True
    assert {item.provider for item in evaluation.metrics.provider_slices} == {
        "KAKAO_TRANSIT",
        "TMAP_TRANSIT",
        "ODSAY_TRANSIT",
    }


def test_duplicate_gold_case_ids_are_rejected(
    provider_input: ProviderMappingInput,
    exact_candidate: CanonicalRouteCandidate,
    evaluated_at: datetime,
) -> None:
    duplicate = GoldSetCase("duplicate", provider_input, exact_candidate, True)
    with pytest.raises(ValueError, match="unique"):
        evaluate_gold_set((duplicate, duplicate), evaluated_at=evaluated_at)
