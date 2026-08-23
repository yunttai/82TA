"""Pure optimizer composition root."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Iterable

from .candidate_generation import BoundedCandidateGenerator, OptimalityUncertifiedError
from .evaluation import CandidateEvaluator
from .graph_search import (
    CanonicalRoutingGraph,
    GraphSearchCaps,
    GraphSearchResult,
    TimeDependentGraphSearch,
)
from .models import (
    CandidateCounts,
    CandidateSeed,
    EvaluatedCandidate,
    OptimizationResult,
    RejectedCandidate,
    RouteConstraints,
)
from .policy import CandidateCaps, EpsilonPolicy, RankingPolicy
from .ports import LegEvaluator
from .patterns import validate_pattern
from .search import SearchOutcome, TimeDependentCandidateSearch


@dataclass(frozen=True, slots=True)
class GraphOptimizationOutcome:
    """Graph discovery evidence paired with its canonical ranked result."""

    graph_search: GraphSearchResult
    optimization: OptimizationResult


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
            # Exact domain evaluation performs no Provider work. Resource-heavy
            # category/pre-Pareto caps belong to strategy exactification; applying
            # them again here can discard the true exact argmin. The overall
            # coarse-combination bound remains enforced.
            exact_evaluation=True,
        )
        search = TimeDependentCandidateSearch(
            batch.candidates,
            departure_at,
            constraints,
            self.evaluator,
            epsilon=self.epsilon,
            ranking_policy=self.ranking_policy,
            hard_candidate_cap=self.caps.coarse_combinations,
        )
        while search.has_pending_candidates:
            search.evaluate_next()
            if search.certificate().hard_cap_reached:
                raise OptimalityUncertifiedError("EXACT_CANDIDATE_CAP_UNCERTIFIED")
        outcome = search.finalize()

        return self._build_result(
            outcome,
            supplied_count=batch.supplied_count,
            generated_count=len(batch.candidates),
            initial_rejected=(
                RejectedCandidate(key, reason) for key, reason in batch.rejected
            ),
        )

    def optimize_graph(
        self,
        graph: CanonicalRoutingGraph,
        origin_ref: str,
        destination_ref: str,
        departure_at: datetime,
        constraints: RouteConstraints,
        *,
        graph_caps: GraphSearchCaps | None = None,
        pattern_hints: Iterable[CandidateSeed] = (),
        provider_call_count: int = 0,
    ) -> GraphOptimizationOutcome:
        """Discover and rank the exact paths in one supplied canonical graph.

        This entrypoint certifies only the supplied graph.  It neither claims that
        a Provider exhausted the physical network nor turns a finite itinerary
        payload into a network-global graph.  Graph discovery performs the exact
        sequential leg evaluation once; its evaluated candidates are then recorded
        into the same candidate-search/ranking pipeline used by ``optimize``.
        """

        if not 0 <= provider_call_count <= self.caps.provider_calls:
            raise ValueError("provider call cap exceeded")
        requested_caps = graph_caps or GraphSearchCaps()
        effective_caps = replace(
            requested_caps,
            max_complete_paths=min(
                requested_caps.max_complete_paths,
                self.caps.coarse_combinations,
            ),
        )
        graph_search = TimeDependentGraphSearch(
            self.evaluator.leg_evaluator,
            caps=effective_caps,
            ranking_policy=self.ranking_policy,
        ).search(
            graph,
            origin_ref,
            destination_ref,
            departure_at,
            constraints,
        )
        graph_search = self._apply_graph_pattern_hints(graph_search, pattern_hints)
        batch = self.generator.generate(
            graph_search.seeds,
            constraints,
            provider_call_count=provider_call_count,
            exact_evaluation=True,
        )
        evaluated_by_key = {
            candidate.candidate_key: candidate
            for candidate in graph_search.evaluated_candidates
        }
        search = TimeDependentCandidateSearch(
            batch.candidates,
            departure_at,
            constraints,
            self.evaluator,
            epsilon=self.epsilon,
            ranking_policy=self.ranking_policy,
            hard_candidate_cap=self.caps.coarse_combinations,
        )
        while search.has_pending_candidates:
            seed = search.pop_next_candidate()
            if seed is None:
                if search.certificate().hard_cap_reached:
                    raise OptimalityUncertifiedError(
                        "EXACT_CANDIDATE_CAP_UNCERTIFIED"
                    )
                continue
            candidate = evaluated_by_key.get(seed.candidate_key)
            if candidate is None:
                raise RuntimeError("graph result lost an evaluated candidate")
            search.record_evaluated(seed, candidate)
        outcome = search.finalize()
        optimization = self._build_result(
            outcome,
            supplied_count=batch.supplied_count,
            generated_count=len(batch.candidates),
            initial_rejected=(
                RejectedCandidate(key, reason) for key, reason in batch.rejected
            ),
        )
        return GraphOptimizationOutcome(graph_search, optimization)

    @staticmethod
    def _apply_graph_pattern_hints(
        graph_search: GraphSearchResult,
        pattern_hints: Iterable[CandidateSeed],
    ) -> GraphSearchResult:
        patterns: dict[tuple[str, ...], str] = {}
        for hint in pattern_hints:
            path = tuple(leg.leg_id for leg in hint.legs)
            current = patterns.setdefault(path, hint.pattern)
            if current != hint.pattern:
                raise ValueError("conflicting graph pattern hints for the same path")

        if not patterns:
            return graph_search
        seeds: list[CandidateSeed] = []
        evaluated: list[EvaluatedCandidate] = []
        for seed, candidate in zip(
            graph_search.seeds,
            graph_search.evaluated_candidates,
            strict=True,
        ):
            pattern = patterns.get(tuple(leg.leg_id for leg in seed.legs))
            if pattern is None or pattern == seed.pattern:
                seeds.append(seed)
                evaluated.append(candidate)
                continue
            restored_seed = replace(seed, pattern=pattern)
            validate_pattern(restored_seed)
            seeds.append(restored_seed)
            evaluated.append(replace(candidate, pattern=pattern))
        return GraphSearchResult(
            seeds=tuple(seeds),
            evaluated_candidates=tuple(evaluated),
            expansion_count=graph_search.expansion_count,
            rejected=graph_search.rejected,
        )

    def _build_result(
        self,
        outcome: SearchOutcome,
        *,
        supplied_count: int,
        generated_count: int,
        initial_rejected: Iterable[RejectedCandidate] = (),
    ) -> OptimizationResult:

        rejected = [
            *initial_rejected,
            *outcome.rejected,
        ]
        deduped = outcome.exact_feasible
        frontier = outcome.epsilon_frontier
        ranked_frontier = outcome.ranked_routes
        recommendations = outcome.recommendations
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
            # Epsilon Pareto membership and exact recommendation anchors are
            # distinct. Only returned epsilon-frontier IDs appear in this list.
            pareto_route_ids=tuple(
                item.route_id
                for item in selected
                if item.route_id in {route.route_id for route in frontier}
            ),
            recommendations=recommendations,
            counts=CandidateCounts(
                supplied=supplied_count,
                generated=generated_count,
                fully_evaluated=outcome.fully_evaluated_count,
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
                -candidate.reliability_score,
                candidate.transfer_risk,
                candidate.walk_seconds,
                candidate.total_duration.p90_seconds,
                candidate.taxi_cost.upper_krw,
                candidate.route_id,
                candidate.candidate_key,
            )
            if current is None or key < (
                current.total_duration.p50_seconds,
                -current.reliability_score,
                current.transfer_risk,
                current.walk_seconds,
                current.total_duration.p90_seconds,
                current.taxi_cost.upper_krw,
                current.route_id,
                current.candidate_key,
            ):
                by_topology[candidate.topology_key] = candidate
        return tuple(sorted(by_topology.values(), key=lambda item: item.route_id))
