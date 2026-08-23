---
name: routing-intelligence-orchestrator
description: "Run the Routing & Intelligence workstream. Use for transport providers, canonical mapping, Bus Intelligence, ETA and seat models, candidate generation, time-dependent costs, strict budget, transfer risk, Pareto ranking, private Django Routing API, collectors, MLOps, fixes, continuation, and partial reruns."
---

# Routing & Intelligence Orchestrator

## Global gates

```bash
python src/scripts/validate_repository.py
python src/scripts/verify_contract_lock.py
```

Read the applicable `AGENTS.md` chain, `src/contracts/CONTEXT_MANIFEST.json`, `src/contracts/CONTRACT_LOCK.json`, shared PRD, relevant contract, workstream documents, and latest `_workspace` state. Final product artifacts belong under `src/`; durable coordination belongs in `_workspace/`.

If shared semantics or contracts must change, stop and use `$shared-contract-governance`.

## Owned paths

- `src/services/routing-api/**`
- `src/packages/routing-domain/**`
- `src/packages/provider-core/**`
- `src/packages/bus-intelligence-core/**`
- `src/workers/**`
- `src/docs/harnesses/routing-intelligence/**`

Never access Service DB or implement account/history/favorites.

## Primary-thread workflow

The primary thread owns orchestration and final consolidation.

1. Run `python src/scripts/snapshot_context.py routing-intelligence`.
2. Create/update `_workspace/routing-intelligence/WORKPLAN.md`.
3. Build dependency graph and latency budget.
4. Delegate independent provider, mapping, model/data, optimizer, security/performance and QA tasks.
5. Keep canonical interfaces fixed during parallel work.
6. Wait for all results and fan-in in dependency order.
7. Run replay/contract/semantic checks incrementally.
8. Write `STATUS.md` and `HANDOFF.md`.

## Recommended custom subagents

- `routing-technical-lead`
- `provider-integration-engineer`
- `transport-mapping-engineer`
- `route-optimization-engineer`
- `bus-intelligence-engineer`
- `routing-data-ml-engineer`
- `routing-security-performance-engineer`
- `routing-qa-engineer`
- `contract-steward`: shared contract impact and compatibility
- `architecture-auditor`: bounded-context and integration architecture review
- `integration-qa`: cross-workstream verification

Do not spawn every role for a narrow task. Keep concurrency within `.codex/config.toml`.

## Dependency order

```text
capability/fixture
→ adapter/canonical object
→ catalog/mapping
→ ETA/seat/boardability/expected wait
→ candidate/time propagation
→ transfer/cost/budget/Pareto/ranking
→ private API
→ replay/performance/security
```

## Phases

### Phase 0 — Audit

- repository/lock/context snapshot
- capability states: DOCUMENTED / KEY_VERIFIED / PRODUCTION_APPROVED
- data/model/mapping status
- private API contract/deadline

### Phase 1 — Plan

Each task includes paths, canonical input/output, fixture, dependency, latency allocation and fallback.

### Phase 2 — Provider and mapping

Use `$provider-adapter-delivery` and `$transport-mapping-delivery`:

- envelope/schema/timeout/quota/cache
- canonical route/stop/direction
- mapping evidence/confidence/review
- malformed/stale/429/timeout fixtures

Run QA before downstream use.

### Phase 3 — Bus Intelligence and optimizer

Use `$bus-intelligence-delivery`, `$routing-data-mlops`, `$route-optimizer-delivery`:

- trip identity and observed labels
- ETA P50/P90/source arbitration
- target-stop seat risk/calibration
- boardability proxy and multi-vehicle expected/P90 wait
- bounded candidate patterns
- sequential time-dependent evaluation
- transfer feasibility
- strict taxi upper-budget
- Pareto and representative selection

Bus Intelligence is incomplete unless it changes bus-leg expected time and ranking in validated cases.

### Phase 4 — API, performance, security

- `POST /v1/routes/optimize`
- capability/health/version/admin restriction
- deadline/cancellation
- provider/model/mapping/ranking provenance
- 6.5-second internal budget
- partial/fallback
- private service auth
- deterministic replay/load/fault tests

### Phase 5 — Service integration

Proceed only after context parity. Compare real output with canonical fixture and generated client; ensure no user identity or cross-database access.

### Phase 6 — Completion

Run component, contract, replay, performance and repository checks. Report capability and data/model gaps honestly.

## Failure rules

- Unverified provider: fixture + capability false; never claim production readiness.
- Optional enrichment timeout: cancel and return PARTIAL when valid.
- LOW mapping: no Bus Intelligence.
- Missing model: approved fallback with warning; no fabricated probability.
- Missing future label: unobserved/NULL, not negative.
- Latency over budget: reduce optional candidates/enrichment, not correctness invariants.
- Shared contract drift: stop and invoke governance.
