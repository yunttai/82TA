"""Bounded best-first search over a finite canonical candidate universe.

The search frontier is ordered by each seed's admissible P50 lower bound.  A
candidate is accepted as an incumbent only after sequential, time-dependent
leg evaluation and all hard constraints have been checked.  Completeness in
this module is deliberately scoped to the finite set supplied by the caller;
it does not imply that a Provider or the physical transport network was
searched exhaustively.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from heapq import heapify, heappop
from typing import Final, Iterable, Literal

from .evaluation import CandidateEvaluationError, CandidateEvaluator
from .models import (
    CandidateSeed,
    EvaluatedCandidate,
    RecommendationSet,
    RejectedCandidate,
    RouteConstraints,
)
from .pareto import pareto_frontier
from .patterns import validate_pattern
from .policy import EpsilonPolicy, RankingPolicy
from .ranking import select_recommendations


SearchObjective = Literal[
    "FASTEST",
    "STABLE",
    "EFFICIENT",
    "PUBLIC_TRANSIT_ONLY",
    "PARETO",
]

_FULL_FRONTIER_OBJECTIVES: Final[frozenset[SearchObjective]] = frozenset(
    {"STABLE", "EFFICIENT", "PARETO"}
)
_DEFAULT_OBJECTIVES: Final[frozenset[SearchObjective]] = frozenset(
    {
        "FASTEST",
        "STABLE",
        "EFFICIENT",
        "PUBLIC_TRANSIT_ONLY",
        "PARETO",
    }
)


class SearchProtocolError(RuntimeError):
    """The caller violated the pop/record incremental-search protocol."""


class SearchNotCertifiedError(RuntimeError):
    """The requested result cannot yet be proved inside the supplied scope."""


@dataclass(frozen=True, slots=True)
class SearchCertificate:
    """Proof state for the finite candidate set supplied to this search."""

    supplied_scope_exhausted: bool
    hard_cap_reached: bool
    lower_bounds_admissible_so_far: bool
    fastest_certified: bool
    public_transit_only_certified: bool
    min_unseen_p50_lower_bound: int | None
    fastest_incumbent_p50_seconds: int | None
    public_incumbent_p50_seconds: int | None
    fastest_reason: str
    public_transit_only_reason: str


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """Exact pool and display frontier are kept intentionally separate."""

    exact_feasible: tuple[EvaluatedCandidate, ...]
    epsilon_frontier: tuple[EvaluatedCandidate, ...]
    ranked_routes: tuple[EvaluatedCandidate, ...]
    recommendations: RecommendationSet
    rejected: tuple[RejectedCandidate, ...]
    certificate: SearchCertificate
    supplied_count: int
    fully_evaluated_count: int


def _fastest_key(candidate: EvaluatedCandidate) -> tuple[object, ...]:
    # Must remain aligned with the canonical exact FASTEST tie policy.
    return (
        candidate.total_duration.p50_seconds,
        -candidate.reliability_score,
        candidate.transfer_risk,
        candidate.walk_seconds,
        candidate.total_duration.p90_seconds,
        candidate.taxi_cost.upper_krw,
        candidate.route_id,
        candidate.candidate_key,
    )


def _frontier_key(seed: CandidateSeed) -> tuple[object, ...]:
    """Admissible lower bound followed only by deterministic identity ties."""

    return (
        seed.coarse_p50_seconds,
        seed.pattern,
        seed.topology_key,
        seed.candidate_key,
    )


class TimeDependentCandidateSearch:
    """Incremental exactification of a bounded, finite candidate seed set."""

    def __init__(
        self,
        seeds: Iterable[CandidateSeed],
        departure_at: datetime,
        constraints: RouteConstraints,
        evaluator: CandidateEvaluator,
        *,
        epsilon: EpsilonPolicy | None = None,
        ranking_policy: RankingPolicy | None = None,
        hard_candidate_cap: int | None = None,
    ) -> None:
        if departure_at.tzinfo is None or departure_at.utcoffset() is None:
            raise ValueError("departure_at must be timezone-aware")
        supplied = tuple(seeds)
        candidate_keys = [seed.candidate_key for seed in supplied]
        if len(candidate_keys) != len(set(candidate_keys)):
            raise ValueError("candidate_key values must be unique in supplied scope")
        if hard_candidate_cap is not None and hard_candidate_cap <= 0:
            raise ValueError("hard_candidate_cap must be positive when supplied")

        self.departure_at = departure_at
        self.constraints = constraints
        self.evaluator = evaluator
        self.epsilon = epsilon or EpsilonPolicy()
        self.ranking_policy = ranking_policy or evaluator.policy
        self.hard_candidate_cap = hard_candidate_cap
        self.supplied_count = len(supplied)

        self._frontier: list[tuple[tuple[object, ...], CandidateSeed]] = [
            (_frontier_key(seed), seed) for seed in supplied
        ]
        heapify(self._frontier)
        self._active: CandidateSeed | None = None
        self._processed_count = 0
        self._fully_evaluated_count = 0
        self._evaluated: list[EvaluatedCandidate] = []
        self._rejected: list[RejectedCandidate] = []
        self._lower_bounds_admissible_so_far = True
        self._hard_cap_reached = False

    @property
    def active_candidate(self) -> CandidateSeed | None:
        return self._active

    @property
    def has_pending_candidates(self) -> bool:
        return self._active is not None or bool(self._frontier)

    @property
    def exact_feasible(self) -> tuple[EvaluatedCandidate, ...]:
        return self._dedupe(tuple(self._evaluated))

    @property
    def rejected(self) -> tuple[RejectedCandidate, ...]:
        return tuple(
            sorted(
                self._rejected,
                key=lambda item: (item.candidate_key, item.reason),
            )
        )

    def pop_next_candidate(self) -> CandidateSeed | None:
        """Pop the next statically feasible seed in admissible-LB order.

        Static rejections are recorded inside the same bounded work accounting.
        The returned seed must be followed by exactly one ``record_*`` call.
        """

        if self._active is not None:
            raise SearchProtocolError("active candidate must be recorded before next pop")

        while self._frontier:
            if (
                self.hard_candidate_cap is not None
                and self._processed_count >= self.hard_candidate_cap
            ):
                self._hard_cap_reached = True
                return None
            _, seed = heappop(self._frontier)
            self._processed_count += 1
            reason = self._static_rejection(seed)
            if reason is not None:
                self._rejected.append(RejectedCandidate(seed.candidate_key, reason))
                continue
            self._active = seed
            return seed
        return None

    def record_evaluated(
        self,
        seed: CandidateSeed,
        candidate: EvaluatedCandidate,
    ) -> bool:
        """Record an exact result; return whether it passed hard constraints."""

        self._require_active(seed)
        if candidate.candidate_key != seed.candidate_key:
            raise SearchProtocolError("evaluated candidate does not match active seed")
        self._fully_evaluated_count += 1
        if candidate.total_duration.p50_seconds < seed.coarse_p50_seconds:
            # Results remain exact when the supplied set is exhausted, but no
            # early proof may rely on a lower bound that has been falsified.
            self._lower_bounds_admissible_so_far = False
        reason = self._constraint_rejection(candidate)
        if reason is None:
            self._evaluated.append(candidate)
            accepted = True
        else:
            self._rejected.append(RejectedCandidate(seed.candidate_key, reason))
            accepted = False
        self._active = None
        return accepted

    def record_rejected(self, seed: CandidateSeed, reason: str) -> None:
        self._require_active(seed)
        if not reason:
            raise ValueError("rejection reason is required")
        self._rejected.append(RejectedCandidate(seed.candidate_key, reason))
        self._active = None

    def evaluate_next(self) -> EvaluatedCandidate | None:
        """Pop and sequentially evaluate one seed, recording any rejection."""

        seed = self.pop_next_candidate()
        if seed is None:
            return None
        try:
            candidate = self.evaluator.evaluate(seed, self.departure_at)
        except (CandidateEvaluationError, ValueError) as exc:
            self.record_rejected(seed, str(exc))
            return None
        return candidate if self.record_evaluated(seed, candidate) else None

    def certificate(self) -> SearchCertificate:
        exact = self.exact_feasible
        fastest = min(exact, key=_fastest_key) if exact else None
        public_pool = tuple(item for item in exact if item.taxi_cost.upper_krw == 0)
        public = min(public_pool, key=_fastest_key) if public_pool else None
        exhausted = (
            self._active is None
            and not self._frontier
            and not self._hard_cap_reached
        )
        min_unseen = self._min_unseen_lower_bound()

        fastest_certified, fastest_reason = self._objective_certificate(
            incumbent=fastest,
            exhausted=exhausted,
            min_unseen=min_unseen,
            objective="FASTEST",
        )
        public_certified, public_reason = self._objective_certificate(
            incumbent=public,
            exhausted=exhausted,
            min_unseen=min_unseen,
            objective="PUBLIC_TRANSIT_ONLY",
        )
        return SearchCertificate(
            supplied_scope_exhausted=exhausted,
            hard_cap_reached=self._hard_cap_reached,
            lower_bounds_admissible_so_far=self._lower_bounds_admissible_so_far,
            fastest_certified=fastest_certified,
            public_transit_only_certified=public_certified,
            min_unseen_p50_lower_bound=min_unseen,
            fastest_incumbent_p50_seconds=(
                fastest.total_duration.p50_seconds if fastest is not None else None
            ),
            public_incumbent_p50_seconds=(
                public.total_duration.p50_seconds if public is not None else None
            ),
            fastest_reason=fastest_reason,
            public_transit_only_reason=public_reason,
        )

    def can_finalize(
        self,
        objectives: Iterable[SearchObjective] = _DEFAULT_OBJECTIVES,
    ) -> bool:
        requested = frozenset(objectives)
        self._validate_objectives(requested)
        certificate = self.certificate()
        if certificate.supplied_scope_exhausted:
            return True
        if requested & _FULL_FRONTIER_OBJECTIVES:
            return False
        if "FASTEST" in requested and not certificate.fastest_certified:
            return False
        if (
            "PUBLIC_TRANSIT_ONLY" in requested
            and not certificate.public_transit_only_certified
        ):
            return False
        return bool(requested)

    def finalize(
        self,
        objectives: Iterable[SearchObjective] = _DEFAULT_OBJECTIVES,
    ) -> SearchOutcome:
        requested = frozenset(objectives)
        if not self.can_finalize(requested):
            certificate = self.certificate()
            raise SearchNotCertifiedError(
                "SEARCH_NOT_CERTIFIED: "
                f"fastest={certificate.fastest_reason}; "
                f"public={certificate.public_transit_only_reason}"
            )

        exact = self.exact_feasible
        frontier = pareto_frontier(exact, self.epsilon)
        if exact:
            ranked, recommendations = select_recommendations(
                frontier,
                self.constraints,
                self.ranking_policy,
                exact_feasible=exact,
            )
        else:
            ranked = ()
            recommendations = RecommendationSet(None, None, None, None)

        # Early objective-specific completion must not imply that unrequested
        # rankings have been certified.
        if not self.certificate().supplied_scope_exhausted:
            recommendations = replace(
                recommendations,
                fastest=(
                    recommendations.fastest if "FASTEST" in requested else None
                ),
                stable=None,
                efficient=None,
                public_transit_only=(
                    recommendations.public_transit_only
                    if "PUBLIC_TRANSIT_ONLY" in requested
                    else None
                ),
            )
        return SearchOutcome(
            exact_feasible=exact,
            epsilon_frontier=frontier,
            ranked_routes=ranked,
            recommendations=recommendations,
            rejected=self.rejected,
            certificate=self.certificate(),
            supplied_count=self.supplied_count,
            fully_evaluated_count=self._fully_evaluated_count,
        )

    def _objective_certificate(
        self,
        *,
        incumbent: EvaluatedCandidate | None,
        exhausted: bool,
        min_unseen: int | None,
        objective: str,
    ) -> tuple[bool, str]:
        if exhausted:
            return True, "SUPPLIED_SCOPE_EXHAUSTED"
        if self._hard_cap_reached:
            return False, "HARD_CANDIDATE_CAP_UNCERTIFIED"
        if incumbent is None:
            return False, f"NO_{objective}_INCUMBENT"
        if not self._lower_bounds_admissible_so_far:
            return False, "LOWER_BOUND_VIOLATION_REQUIRES_EXHAUSTION"
        assert min_unseen is not None
        incumbent_p50 = incumbent.total_duration.p50_seconds
        if min_unseen > incumbent_p50:
            return True, "MIN_UNSEEN_LOWER_BOUND_EXCEEDS_INCUMBENT"
        if min_unseen == incumbent_p50:
            return False, "EQUAL_LOWER_BOUND_REQUIRES_TIE_EVALUATION"
        return False, "UNSEEN_LOWER_BOUND_CAN_BE_FASTER"

    def _min_unseen_lower_bound(self) -> int | None:
        bounds = [int(item[0][0]) for item in self._frontier]
        if self._active is not None:
            bounds.append(self._active.coarse_p50_seconds)
        return min(bounds) if bounds else None

    @staticmethod
    def _validate_objectives(objectives: frozenset[SearchObjective]) -> None:
        unknown = set(objectives) - set(_DEFAULT_OBJECTIVES)
        if unknown:
            raise ValueError(f"unknown search objectives: {sorted(unknown)}")
        if not objectives:
            raise ValueError("at least one search objective is required")

    def _require_active(self, seed: CandidateSeed) -> None:
        if self._active is None:
            raise SearchProtocolError("no active candidate")
        if self._active.candidate_key != seed.candidate_key:
            raise SearchProtocolError("recorded seed does not match active candidate")

    def _static_rejection(self, seed: CandidateSeed) -> str | None:
        try:
            validate_pattern(seed)
        except ValueError:
            return "PATTERN_INVALID"
        modes = {leg.mode for leg in seed.legs if leg.mode not in {"WAIT", "TRANSFER"}}
        if not modes <= self.constraints.allowed_modes:
            return "MODE_NOT_ALLOWED"
        if (
            seed.pattern == "TRANSIT_TAXI_BRIDGE_TRANSIT"
            and not self.constraints.allow_taxi_bridge
        ):
            return "TAXI_BRIDGE_DISABLED"
        if sum(leg.mode == "TAXI" for leg in seed.legs) > self.constraints.max_taxi_legs:
            return "MAX_TAXI_LEGS"
        if seed.transfer_count > self.constraints.max_transfers:
            return "MAX_TRANSFERS"
        return None

    def _constraint_rejection(self, candidate: EvaluatedCandidate) -> str | None:
        if candidate.taxi_cost.upper_krw > self.constraints.taxi_budget_krw:
            return "STRICT_TAXI_BUDGET"
        if candidate.walk_seconds > self.constraints.max_walk_seconds:
            return "MAX_WALK"
        if candidate.transfer_count > self.constraints.max_transfers:
            return "MAX_TRANSFERS"
        if candidate.taxi_leg_count > self.constraints.max_taxi_legs:
            return "MAX_TAXI_LEGS"
        return None

    @staticmethod
    def _dedupe(
        candidates: tuple[EvaluatedCandidate, ...],
    ) -> tuple[EvaluatedCandidate, ...]:
        by_topology: dict[
            tuple[tuple[str, str, str, str], ...], EvaluatedCandidate
        ] = {}
        for candidate in candidates:
            current = by_topology.get(candidate.topology_key)
            if current is None or _fastest_key(candidate) < _fastest_key(current):
                by_topology[candidate.topology_key] = candidate
        return tuple(sorted(by_topology.values(), key=lambda item: item.route_id))
