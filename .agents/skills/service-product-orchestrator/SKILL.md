---
name: service-product-orchestrator
description: "Run the Service Product workstream for React Web/PWA and Django Service Backend. Use for new features, fixes, continuation, partial reruns, UX, public API, accounts, places, history, favorites, RoutingGateway, and user-facing integration. Do not use for provider orchestration or routing algorithms."
---

# Service Product Orchestrator

## Global gates

Before implementation:

```bash
python src/scripts/validate_repository.py
python src/scripts/verify_contract_lock.py
```

Read the applicable `AGENTS.md` chain, `src/contracts/CONTEXT_MANIFEST.json`, `src/contracts/CONTRACT_LOCK.json`, shared PRD, relevant contract, workstream documents, and latest `_workspace` state. Final product artifacts belong under `src/`; durable coordination belongs in `_workspace/`.

If shared semantics or contracts must change, stop the conflicting implementation and use `$shared-contract-governance`.

## Owned paths

- `src/apps/web/**`
- `src/services/service-api/**`
- `src/docs/harnesses/service-product/**`
- shared test paths only when explicitly required

Do not edit Routing-owned paths. The browser never calls Routing directly. Service consumes only the versioned Routing contract.

## Primary-thread workflow

The primary Codex thread is the supervisor. It must:

1. Run `python src/scripts/snapshot_context.py service-product`.
2. Create/update `_workspace/service-product/WORKPLAN.md`.
3. Classify initial, continuation, focused rerun, bug fix, or integration.
4. Map each task to requirement, owned paths, contract input, acceptance, test, dependency.
5. Delegate independent tasks to named project custom subagents.
6. Wait for all subagents, inspect results, resolve conflicts, and consolidate the final diff.
7. Run incremental QA after each boundary.
8. Write `_workspace/service-product/STATUS.md` and `HANDOFF.md`.

## Recommended custom subagents

- `service-product-lead`
- `service-ux-engineer`
- `service-frontend-engineer`
- `service-backend-engineer`
- `service-data-engineer`
- `service-security-engineer`
- `service-qa-engineer`
- `contract-steward`: approved shared-change analysis only
- `architecture-auditor`: bounded-context and integration architecture review
- `integration-qa`: cross-workstream verification

Ask Codex explicitly to delegate independent pieces. Keep at most seven workstream subagents active. Use `/agent` interactively to inspect threads.

## WORKPLAN format

```markdown
| ID | Agent | Paths | Contract | Acceptance | Test | Depends on | Status | Handoff |
```

Status: `PENDING`, `IN_PROGRESS`, `BLOCKED`, `DONE`, `FAILED`, `UNVERIFIED`.

## Phases

### Phase 0 — Context and contract

- validate repository and lock
- snapshot context
- read Public/Private OpenAPI examples
- detect hidden shared semantic changes
- select Stub/Replay/Real RoutingGateway

### Phase 1 — UX and public API plan

Delegate UX/state and Django/API planning in parallel. Consolidate one vertical slice before editing.

Required states: IDLE, VALIDATING, SEARCHING, COMPLETE, PARTIAL, NO_FEASIBLE_ROUTE, PROVIDER_UNAVAILABLE, EXPIRED, Bus Intelligence supported/unknown/stale/low-confidence.

### Phase 2 — Contract-first mock

Use canonical fixtures. Frontend and Backend consume the same examples. Do not invent fields because Routing is incomplete.

### Phase 3 — Parallel implementation

Frontend and Backend may proceed after shape fixation. Delegate Data/Security only when independent.

### Phase 4 — Incremental QA

Compare:

- OpenAPI ↔ Django serializer/view
- Django projection ↔ generated TypeScript client
- TypeScript model ↔ UI field access
- route ownership/auth
- exact-location log redaction
- COMPLETE/PARTIAL/error/unknown behavior

Return a failed boundary to its owner. Do not hide mismatch with `any`, casts, duplicate DTOs, or frontend recomputation.

### Phase 5 — Real Routing integration

Only after context parity:

- generated client version
- service JWT/deadline/idempotency/correlation
- mock vs real response parity
- partial/error behavior
- public-safe projection
- R1–R4 smoke/E2E

### Phase 6 — Completion

Run relevant tests and repository validation. Report changed files, tests, contract impact, privacy/security, known gaps, rollback.

## Focused reruns

Delegate only required roles and touch related files. Preserve unrelated work and `_workspace` decisions.

## Failure rules

- Routing unavailable: continue with canonical Stub/Replay; real integration is `UNVERIFIED`.
- Shared contract drift: stop.
- Public/private shape mismatch: report exact producer/consumer paths; do not cast around it.
- Subagent failure: retry once with narrower scope, then mark `BLOCKED` and reassign or continue in primary thread.
