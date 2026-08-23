"""Deterministic bounded multi-label search over a canonical transport graph."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from heapq import heappop, heappush
from typing import Iterable

from .evaluation import CandidateEvaluationError, CandidateEvaluator
from .models import (
    CandidateSeed,
    EvaluatedCandidate,
    LegSpec,
    RouteConstraints,
    TRANSIT_MODES,
)
from .patterns import validate_pattern
from .policy import RankingPolicy
from .ports import LegEvaluator


class GraphSearchUncertifiedError(RuntimeError):
    """A hard resource cap prevented a proof over the supplied graph."""


@dataclass(frozen=True, slots=True)
class GraphSearchCaps:
    max_expansions: int = 2_000
    max_labels_per_node: int = 64
    max_complete_paths: int = 256
    max_legs: int = 12

    def __post_init__(self) -> None:
        if min(
            self.max_expansions,
            self.max_labels_per_node,
            self.max_complete_paths,
            self.max_legs,
        ) <= 0:
            raise ValueError("graph search caps must be positive")


@dataclass(frozen=True, slots=True)
class CanonicalRoutingGraph:
    edges: tuple[LegSpec, ...]

    def __post_init__(self) -> None:
        leg_ids = tuple(edge.leg_id for edge in self.edges)
        if len(leg_ids) != len(set(leg_ids)):
            raise ValueError("canonical graph edge leg_id values must be unique")


@dataclass(frozen=True, slots=True)
class GraphPathRejection:
    path_key: str
    reason: str


@dataclass(frozen=True, slots=True)
class GraphSearchResult:
    seeds: tuple[CandidateSeed, ...]
    evaluated_candidates: tuple[EvaluatedCandidate, ...]
    expansion_count: int
    rejected: tuple[GraphPathRejection, ...]

    def __post_init__(self) -> None:
        seed_keys = tuple(seed.candidate_key for seed in self.seeds)
        evaluated_keys = tuple(
            candidate.candidate_key for candidate in self.evaluated_candidates
        )
        if seed_keys != evaluated_keys:
            raise ValueError("graph result seeds and evaluated candidates must align")
        if len(seed_keys) != len(set(seed_keys)):
            raise ValueError("graph result candidate keys must be unique")
        if self.expansion_count < 0:
            raise ValueError("graph expansion count must be non-negative")


@dataclass(frozen=True, slots=True)
class _Label:
    node_ref: str
    visited_nodes: tuple[str, ...]
    legs: tuple[LegSpec, ...]
    seed: CandidateSeed | None
    evaluated: EvaluatedCandidate | None
    path_key: str


def _path_key(legs: Iterable[LegSpec]) -> str:
    material = "|".join(leg.leg_id for leg in legs)
    return f"graph_{sha256(material.encode('utf-8')).hexdigest()[:20]}"


def _core_modes(legs: tuple[LegSpec, ...]) -> tuple[str, ...]:
    return tuple(
        leg.mode
        for leg in legs
        if leg.mode not in {"WALK", "WAIT", "TRANSFER"}
    )


def _pattern_for(legs: tuple[LegSpec, ...], *, final: bool) -> str | None:
    core = _core_modes(legs)
    if not core:
        return None if final else "TRANSIT_ONLY"
    kinds = tuple("TAXI" if mode == "TAXI" else "TRANSIT" for mode in core)
    if any(mode != "TAXI" and mode not in TRANSIT_MODES for mode in core):
        return None
    compressed = tuple(
        kind for index, kind in enumerate(kinds) if index == 0 or kind != kinds[index - 1]
    )
    patterns = {
        ("TRANSIT",): "TRANSIT_ONLY",
        ("TAXI",): "TAXI_ONLY",
        ("TAXI", "TRANSIT"): "TAXI_TRANSIT",
        ("TRANSIT", "TAXI"): "TRANSIT_TAXI",
        ("TAXI", "TRANSIT", "TAXI"): "TAXI_TRANSIT_TAXI",
        ("TRANSIT", "TAXI", "TRANSIT"): "TRANSIT_TAXI_BRIDGE_TRANSIT",
    }
    return patterns.get(compressed)


def _transfer_count(legs: tuple[LegSpec, ...]) -> int:
    return max(0, sum(leg.mode in TRANSIT_MODES for leg in legs) - 1)


def _seed_for(legs: tuple[LegSpec, ...], pattern: str) -> CandidateSeed:
    key = _path_key(legs)
    return CandidateSeed(
        candidate_key=key,
        pattern=pattern,
        legs=legs,
        transfer_count=_transfer_count(legs),
        coarse_p50_seconds=0,
        coarse_taxi_upper_krw=0,
    )


def _label_metrics(label: _Label) -> tuple[object, ...]:
    candidate = label.evaluated
    if candidate is None:
        return (0, 0, 0, 0, 0, 0, 0.0, -1.0)
    return (
        candidate.total_duration.p50_seconds,
        candidate.total_duration.p90_seconds,
        candidate.taxi_cost.upper_krw,
        candidate.walk_seconds,
        candidate.transfer_count,
        candidate.taxi_leg_count,
        candidate.transfer_risk,
        -candidate.reliability_score,
    )


def _pattern_state(label: _Label) -> tuple[str, ...]:
    core = _core_modes(label.legs)
    kinds = tuple("TAXI" if mode == "TAXI" else "TRANSIT" for mode in core)
    return tuple(
        kind
        for index, kind in enumerate(kinds)
        if index == 0 or kind != kinds[index - 1]
    )


def _future_state_dominates(left: _Label, right: _Label) -> bool:
    return (
        _pattern_state(left) == _pattern_state(right)
        and set(left.visited_nodes) <= set(right.visited_nodes)
    )


def _safe_dominates(left: _Label, right: _Label) -> bool:
    """Dominance safe without assuming FIFO time-dependent edge costs.

    Different arrival instants are retained even if one is earlier: a later
    label may enter a downstream time band with a lower traversal cost.
    """

    if not _future_state_dominates(left, right):
        return False
    left_values = _label_metrics(left)
    right_values = _label_metrics(right)
    if left_values[:2] != right_values[:2]:
        return False
    return all(a <= b for a, b in zip(left_values[2:], right_values[2:])) and any(
        a < b for a, b in zip(left_values[2:], right_values[2:])
    )


class TimeDependentGraphSearch:
    def __init__(
        self,
        leg_evaluator: LegEvaluator,
        *,
        caps: GraphSearchCaps | None = None,
        ranking_policy: RankingPolicy | None = None,
    ) -> None:
        self.caps = caps or GraphSearchCaps()
        self.ranking_policy = ranking_policy or RankingPolicy()
        self.evaluator = CandidateEvaluator(leg_evaluator, self.ranking_policy)

    def search(
        self,
        graph: CanonicalRoutingGraph,
        origin_ref: str,
        destination_ref: str,
        departure_at: datetime,
        constraints: RouteConstraints,
    ) -> GraphSearchResult:
        if not origin_ref or not destination_ref or origin_ref == destination_ref:
            raise ValueError("graph search endpoints must be distinct and nonblank")
        if departure_at.tzinfo is None or departure_at.utcoffset() is None:
            raise ValueError("departure_at must be timezone-aware")

        adjacency: dict[str, list[LegSpec]] = {}
        for edge in graph.edges:
            adjacency.setdefault(edge.from_ref, []).append(edge)
        for edges in adjacency.values():
            edges.sort(
                key=lambda edge: (
                    edge.to_ref,
                    edge.mode,
                    edge.topology_ref or "-",
                    edge.leg_id,
                )
            )

        initial = _Label(
            node_ref=origin_ref,
            visited_nodes=(origin_ref,),
            legs=(),
            seed=None,
            evaluated=None,
            path_key="graph_origin",
        )
        frontier: list[tuple[tuple[object, ...], _Label]] = []
        heappush(frontier, (self._queue_key(initial), initial))
        labels_by_node: dict[str, list[_Label]] = {origin_ref: [initial]}
        complete: list[_Label] = []
        rejected: list[GraphPathRejection] = []
        expansion_count = 0

        while frontier:
            _, label = heappop(frontier)
            if label not in labels_by_node.get(label.node_ref, ()):
                continue
            if label.node_ref == destination_ref:
                continue
            if expansion_count >= self.caps.max_expansions:
                raise GraphSearchUncertifiedError("GRAPH_EXPANSION_CAP_UNCERTIFIED")
            outgoing = adjacency.get(label.node_ref, ())
            if len(label.legs) >= self.caps.max_legs:
                if any(edge.to_ref not in label.visited_nodes for edge in outgoing):
                    raise GraphSearchUncertifiedError("GRAPH_LEG_CAP_UNCERTIFIED")
                continue

            expansion_count += 1
            for edge in outgoing:
                next_legs = (*label.legs, edge)
                path_key = _path_key(next_legs)
                if edge.to_ref in label.visited_nodes:
                    rejected.append(GraphPathRejection(path_key, "GRAPH_CYCLE"))
                    continue
                if edge.mode not in constraints.allowed_modes:
                    rejected.append(GraphPathRejection(path_key, "MODE_NOT_ALLOWED"))
                    continue
                pattern = _pattern_for(next_legs, final=edge.to_ref == destination_ref)
                if pattern is None:
                    rejected.append(GraphPathRejection(path_key, "PATTERN_UNSUPPORTED"))
                    continue
                if (
                    pattern == "TRANSIT_TAXI_BRIDGE_TRANSIT"
                    and not constraints.allow_taxi_bridge
                ):
                    rejected.append(
                        GraphPathRejection(path_key, "TAXI_BRIDGE_DISABLED")
                    )
                    continue
                seed = _seed_for(next_legs, pattern)
                if _core_modes(next_legs):
                    try:
                        validate_pattern(seed)
                    except ValueError:
                        rejected.append(
                            GraphPathRejection(path_key, "PATTERN_UNSUPPORTED")
                        )
                        continue
                try:
                    evaluated = self.evaluator.evaluate(seed, departure_at)
                except (CandidateEvaluationError, ValueError) as exc:
                    rejected.append(GraphPathRejection(path_key, str(exc)))
                    continue
                reason = self._constraint_rejection(evaluated, constraints)
                if reason is not None:
                    rejected.append(GraphPathRejection(path_key, reason))
                    continue

                next_label = _Label(
                    node_ref=edge.to_ref,
                    visited_nodes=(*label.visited_nodes, edge.to_ref),
                    legs=next_legs,
                    seed=seed,
                    evaluated=evaluated,
                    path_key=path_key,
                )
                if edge.to_ref == destination_ref:
                    complete.append(next_label)
                    if len(complete) > self.caps.max_complete_paths:
                        raise GraphSearchUncertifiedError(
                            "GRAPH_COMPLETE_PATH_CAP_UNCERTIFIED"
                        )
                    continue
                if not self._insert_label(labels_by_node, next_label):
                    rejected.append(GraphPathRejection(path_key, "LABEL_DOMINATED"))
                    continue
                heappush(frontier, (self._queue_key(next_label), next_label))

        ordered_complete = tuple(
            sorted(
                complete,
                key=lambda label: (
                    _label_metrics(label),
                    label.path_key,
                ),
            )
        )
        final_seeds: list[CandidateSeed] = []
        final_evaluated: list[EvaluatedCandidate] = []
        for label in ordered_complete:
            assert label.seed is not None and label.evaluated is not None
            final_seeds.append(
                replace(
                    label.seed,
                    coarse_p50_seconds=label.evaluated.total_duration.p50_seconds,
                    coarse_taxi_upper_krw=label.evaluated.taxi_cost.upper_krw,
                    coarse_risk=label.evaluated.transfer_risk,
                )
            )
            final_evaluated.append(label.evaluated)
        return GraphSearchResult(
            seeds=tuple(final_seeds),
            evaluated_candidates=tuple(final_evaluated),
            expansion_count=expansion_count,
            rejected=tuple(
                sorted(
                    set(rejected),
                    key=lambda item: (item.path_key, item.reason),
                )
            ),
        )

    def _insert_label(
        self,
        labels_by_node: dict[str, list[_Label]],
        candidate: _Label,
    ) -> bool:
        labels = labels_by_node.setdefault(candidate.node_ref, [])
        candidate_metrics = _label_metrics(candidate)
        for current in tuple(labels):
            current_metrics = _label_metrics(current)
            if current_metrics == candidate_metrics:
                if _future_state_dominates(current, candidate):
                    if _future_state_dominates(candidate, current):
                        if current.path_key <= candidate.path_key:
                            return False
                        labels.remove(current)
                        continue
                    return False
                if _future_state_dominates(candidate, current):
                    labels.remove(current)
                    continue
            if _safe_dominates(current, candidate):
                return False
            if _safe_dominates(candidate, current):
                labels.remove(current)
        labels.append(candidate)
        labels.sort(key=lambda label: (_label_metrics(label), label.path_key))
        if len(labels) > self.caps.max_labels_per_node:
            raise GraphSearchUncertifiedError("GRAPH_LABEL_CAP_UNCERTIFIED")
        return True

    @staticmethod
    def _queue_key(label: _Label) -> tuple[object, ...]:
        return (*_label_metrics(label), label.node_ref, label.path_key)

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
