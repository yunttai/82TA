---
name: routing-intelligence-orchestrator
description: "Run the Routing & Intelligence workstream. Use for transport providers, canonical mapping, Bus Intelligence, ETA and seat models, candidate generation, time-dependent costs, strict budget, transfer risk, Pareto ranking, private Django Routing API, collectors, MLOps, fixes, continuation, and partial reruns."
---

# Routing & Intelligence Orchestrator

## Default mode: focused implementation

Treat an implementation, bug fix, or continuation request as implementation work. An audit, plan, ADR/CCR proposal, workspace update, or release verdict is not an alternative deliverable.

1. Read applicable `AGENTS.md`, the current production call path, nearby tests, and directly consumed contracts.
2. If relationships are unclear and `.codegraph/` exists, make one bounded query for the affected symbol/call path. Reuse that result until the relevant source changes.
3. Identify the smallest real implementation gap, edit it, and add a focused regression or property test.
4. Run targeted checks while iterating and one affected Routing aggregate suite after the diff stabilizes.
5. Report the implementation and its evidence. Do not issue `GO`/`NO_GO` unless the user requested integration or release readiness.

On a continuation, reuse unchanged code findings, verified contract hashes, and green test results. Do not repeat repository audits, snapshots, `WORKPLAN`/`STATUS`/`HANDOFF` updates, or unchanged suites merely because the task resumed.

## Scope routing

- Local provider, mapping, Bus Intelligence, optimizer, worker, or private API change: work only in the affected component and its tests.
- Shared API or semantic change: add `$shared-contract-governance` for the affected producer/consumer surface only.
- Cross-workstream integration: add `$integration-coherence-qa` for the changed boundary only.
- Deployment/release readiness: add security, performance, capability, rollback, and environment evidence only when explicitly requested.

Do not invoke architecture, contract, integration, security, or release roles merely because they exist. Delegate only when the user requested delegation or the task contains genuinely independent work; keep a focused task to at most one implementation specialist and one independent reviewer with non-overlapping write scopes.

## Dependency guidance, not a mandatory pipeline

Provider → canonical mapping → optional Bus Intelligence → candidate/time/cost/ranking → private API is a dependency map. Run only the segment touched by the task. An unavailable provider key, live approval, model, or mapping corpus does not block pure-domain or fixture-backed offline algorithm work; keep the unavailable live capability disabled or unverified.

Use the runtime that owns each check. Routing package/private API tests run in the Routing environment. Service consumer tests run in the Service environment. Do not collect both trees with one incomplete environment.

## Failure semantics

- Fail closed for service authentication, untrusted schemas/artifacts, and values required to certify strict budget or feasibility.
- Optional exactification/enrichment timeout drops the affected candidate or uses the current fallback/`PARTIAL`/no-feasible-route semantics; it is not automatically a hard 504.
- LOW mapping disables Bus Intelligence; missing models use the approved explicit fallback; missing future labels stay NULL/unobserved.
- Preserve bounded candidate/provider calls, time propagation, provenance, and deterministic behavior.
- Stop only the shared boundary affected by real contract drift; report unrelated baseline drift separately.
