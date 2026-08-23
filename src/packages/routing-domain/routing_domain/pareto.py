"""Exact and epsilon dominance for evaluated route candidates."""

from __future__ import annotations

from .models import EvaluatedCandidate
from .policy import EpsilonPolicy


def _metrics(candidate: EvaluatedCandidate) -> tuple[float, float, float, float, float]:
    return (
        candidate.total_duration.p50_seconds,
        candidate.total_duration.p90_seconds,
        candidate.taxi_cost.upper_krw,
        candidate.walk_seconds,
        candidate.transfer_risk,
    )


def exactly_dominates(left: EvaluatedCandidate, right: EvaluatedCandidate) -> bool:
    left_values = _metrics(left)
    right_values = _metrics(right)
    return all(a <= b for a, b in zip(left_values, right_values)) and any(
        a < b for a, b in zip(left_values, right_values)
    )


def epsilon_dominates(
    left: EvaluatedCandidate,
    right: EvaluatedCandidate,
    epsilon: EpsilonPolicy,
) -> bool:
    left_values = _metrics(left)
    right_values = _metrics(right)
    tolerances = (
        epsilon.p50_seconds,
        epsilon.p90_seconds,
        epsilon.taxi_upper_krw,
        epsilon.walk_seconds,
        epsilon.transfer_risk,
    )
    no_worse = all(a <= b + tolerance for a, b, tolerance in zip(left_values, right_values, tolerances))
    meaningfully_better = any(
        a < b - tolerance
        for a, b, tolerance in zip(left_values, right_values, tolerances)
    )
    return no_worse and meaningfully_better


def pareto_frontier(
    candidates: tuple[EvaluatedCandidate, ...],
    epsilon: EpsilonPolicy,
) -> tuple[EvaluatedCandidate, ...]:
    """Return a cycle-safe epsilon frontier over the exact Pareto set.

    Epsilon dominance is not transitive and can contain directed cycles.  The
    versioned internal policy collapses strongly connected components, keeps
    only source components in the condensation DAG, and selects one
    lexicographic representative from each.  Starting from the exact frontier
    preserves the no-exact-dominance invariant; every finite nonempty graph has
    at least one source component, so epsilon pruning cannot erase all routes.
    """

    ordered = tuple(sorted(candidates, key=lambda item: (item.route_id, item.candidate_key)))
    exact_frontier = tuple(
        candidate
        for candidate in ordered
        if not any(
            other is not candidate and exactly_dominates(other, candidate)
            for other in ordered
        )
    )
    if len(exact_frontier) < 2:
        return exact_frontier

    graph = tuple(
        tuple(
            right_index
            for right_index, right in enumerate(exact_frontier)
            if left_index != right_index and epsilon_dominates(left, right, epsilon)
        )
        for left_index, left in enumerate(exact_frontier)
    )
    components = _strongly_connected_components(graph)
    component_by_node = {
        node: component_index
        for component_index, component in enumerate(components)
        for node in component
    }
    incoming = [False] * len(components)
    for source, targets in enumerate(graph):
        source_component = component_by_node[source]
        for target in targets:
            target_component = component_by_node[target]
            if source_component != target_component:
                incoming[target_component] = True

    frontier = tuple(
        min(
            (exact_frontier[index] for index in component),
            key=_representative_key,
        )
        for component_index, component in enumerate(components)
        if not incoming[component_index]
    )
    return tuple(
        sorted(
            frontier,
            key=lambda item: (
                item.total_duration.p50_seconds,
                item.total_duration.p90_seconds,
                item.taxi_cost.upper_krw,
                item.route_id,
            ),
        )
    )


def _representative_key(candidate: EvaluatedCandidate) -> tuple[object, ...]:
    return (*_metrics(candidate), candidate.route_id, candidate.candidate_key)


def _strongly_connected_components(graph: tuple[tuple[int, ...], ...]) -> tuple[tuple[int, ...], ...]:
    """Deterministic Tarjan SCC decomposition for the bounded epsilon graph."""

    next_index = 0
    indices = [-1] * len(graph)
    lowlinks = [0] * len(graph)
    stack: list[int] = []
    on_stack = [False] * len(graph)
    components: list[tuple[int, ...]] = []

    def visit(node: int) -> None:
        nonlocal next_index
        indices[node] = next_index
        lowlinks[node] = next_index
        next_index += 1
        stack.append(node)
        on_stack[node] = True

        for target in graph[node]:
            if indices[target] == -1:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif on_stack[target]:
                lowlinks[node] = min(lowlinks[node], indices[target])

        if lowlinks[node] != indices[node]:
            return
        component: list[int] = []
        while True:
            member = stack.pop()
            on_stack[member] = False
            component.append(member)
            if member == node:
                break
        components.append(tuple(sorted(component)))

    for node in range(len(graph)):
        if indices[node] == -1:
            visit(node)
    return tuple(sorted(components, key=lambda component: component[0]))
