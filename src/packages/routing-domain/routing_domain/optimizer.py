"""Pure optimizer composition root."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .candidate_generation import BoundedCandidateGenerator
from .evaluation import CandidateEvaluationError, CandidateEvaluator
from .models import (
    CandidateCounts,
    CandidateSeed,
    EvaluatedCandidate,
    OptimizationResult,
    RejectedCandidate,
    RouteConstraints,
)
from .pareto import pareto_frontier
from .policy import CandidateCaps, EpsilonPolicy, RankingPolicy
from .ports import LegEvaluator
from .ranking import select_recommendations


class RouteOptimizer:
    def __init__(
        self,
        leg_evaluator: LegEvaluator,
        *,
        caps: CandidateCaps | None = None,
        epsilon: EpsilonPolicy | None = None,
        ranking_policy: RankingPolicy | None = None,
    ) -> None:
        self.caps = caps or CandidateCaps()
        self.epsilon = epsilon or EpsilonPolicy()
        self.ranking_policy = ranking_policy or RankingPolicy()
        self.generator = BoundedCandidateGenerator(self.caps)
        self.evaluator = CandidateEvaluator(leg_evaluator, self.ranking_policy)

    def optimize(
        self,
        seeds: Iterable[CandidateSeed],
        departure_at: datetime,
        constraints: RouteConstraints,
        *,
        provider_call_count: int = 0,
    ) -> OptimizationResult:
        batch = self.generator.generate(
            seeds,
            constraints,
            provider_call_count=provider_call_count,
        )
        rejected = [RejectedCandidate(key, reason) for key, reason in batch.rejected]
        evaluated: list[EvaluatedCandidate] = []
        for seed in batch.candidates:
            try:
                candidate = self.evaluator.evaluate(seed, departure_at)
            except (CandidateEvaluationError, ValueError) as exc:
                rejected.append(RejectedCandidate(seed.candidate_key, str(exc)))
                continue
            reason = self._constraint_rejection(candidate, constraints)
            if reason is not None:
                rejected.append(RejectedCandidate(seed.candidate_key, reason))
                continue
            evaluated.append(candidate)

        deduped = self._dedupe(tuple(evaluated))
        frontier = pareto_frontier(deduped, self.epsilon)
        ranked_frontier, recommendations = select_recommendations(
            frontier,
            constraints,
            self.ranking_policy,
        )
        selected_ids = {
            item
            for item in (
                recommendations.fastest,
                recommendations.stable,
                recommendations.efficient,
                recommendations.public_transit_only,
            )
            if item is not None
        }
        selected = tuple(
            item for item in ranked_frontier if item.route_id in selected_ids
        )[: self.caps.user_results]
        return OptimizationResult(
            routes=selected,
            # Only returned route IDs may appear in the API-facing Pareto list.
            pareto_route_ids=tuple(item.route_id for item in selected),
            recommendations=recommendations,
            counts=CandidateCounts(
                supplied=batch.supplied_count,
                generated=len(batch.candidates),
                fully_evaluated=len(evaluated),
                feasible=len(deduped),
                pareto=len(frontier),
            ),
            rejected=tuple(sorted(rejected, key=lambda item: (item.candidate_key, item.reason))),
            ranking_policy_version=self.ranking_policy.version,
        )

    @staticmethod
    def _constraint_rejection(
        candidate: EvaluatedCandidate,
        constraints: RouteConstraints,
    ) -> str | None:
        if candidate.taxi_cost.upper_krw > constraints.taxi_budget_krw:
            return "STRICT_TAXI_BUDGET"
        if candidate.walk_seconds > constraints.max_walk_seconds:
            return "MAX_WALK"
        if candidate.transfer_count > constraints.max_transfers:
            return "MAX_TRANSFERS"
        if candidate.taxi_leg_count > constraints.max_taxi_legs:
            return "MAX_TAXI_LEGS"
        return None

    @staticmethod
    def _dedupe(candidates: tuple[EvaluatedCandidate, ...]) -> tuple[EvaluatedCandidate, ...]:
        by_topology: dict[tuple[tuple[str, str, str, str], ...], EvaluatedCandidate] = {}
        for candidate in candidates:
            current = by_topology.get(candidate.topology_key)
            key = (
                candidate.total_duration.p50_seconds,
                candidate.total_duration.p90_seconds,
                candidate.taxi_cost.upper_krw,
                candidate.route_id,
            )
            if current is None or key < (
                current.total_duration.p50_seconds,
                current.total_duration.p90_seconds,
                current.taxi_cost.upper_krw,
                current.route_id,
            ):
                by_topology[candidate.topology_key] = candidate
        return tuple(sorted(by_topology.values(), key=lambda item: item.route_id))
