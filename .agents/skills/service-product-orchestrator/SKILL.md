---
name: service-product-orchestrator
description: "Run the Service Product workstream for React Web/PWA and Django Service Backend. Use for new features, fixes, continuation, partial reruns, UX, public API, accounts, places, history, favorites, RoutingGateway, and user-facing integration. Do not use for provider orchestration or routing algorithms."
---

# Service Product Orchestrator

## Default mode: focused implementation

Treat a feature, bug fix, or continuation as implementation work. Read applicable `AGENTS.md`, the affected Web/Service production path, nearby tests, and directly consumed contracts; then edit promptly. If relationships are unclear and `.codegraph/` exists, use one bounded affected-symbol query and reuse it until that source changes.

An audit, UX plan, contract proposal, workspace ledger, or release verdict is not a substitute for requested code. On continuation, reuse unchanged source findings, contract evidence, and green tests; do not rerun snapshots, ledgers, full suites, or planning phases just because the task resumed.

## Scope routing

- Local UI or Service API fix: modify the affected component/view/serializer/gateway and run targeted tests.
- Vertical slice: connect only the necessary Web consumer and Service producer, adding data/privacy review if that slice touches them.
- Shared API meaning: use `$shared-contract-governance` for the affected producer/consumer and generated client only.
- Real Routing integration: verify the changed private-client/projection boundary and live lock parity.
- Deployment/release: add environment security, accessibility, operations, and rollback evidence only when explicitly requested.

Default to the smallest named slice. Coordination state for rate limiting or idempotency does not imply Kakao Local or Routing Provider response caching. Treat adjacent caching, retention, provider-terms, and cloud-rollout questions as separate TBDs unless the request changes those paths. Validate only the environment the task names; local or PR-CI work does not require a deployed-GCE proof, and removed AWS infrastructure is never a fallback requirement.

Editing or activating a repository-local PR check is ordinary implementation when working CI is requested. Ask for added authority only if the change also touches secrets or permissions, deploys or mutates an external environment, creates material cost, or performs a destructive action. A shared file path requires an actual diff/writer-overlap check, not general team approval.

Do not edit Routing algorithms/providers for a Service task. The browser never calls Routing directly, and Service does not recalculate Routing-owned duration, fare, ETA, risk, or ranking.

## Delegation and evidence

Use the primary thread for a focused task. Delegate only when the user requested it or work is genuinely independent; use at most one implementation specialist and one independent reviewer with non-overlapping write scopes. Do not automatically start lead, UX, Frontend, Backend, Data, Security, QA, Contract, Architecture, and Integration roles.

Run Web/Service checks in their owning runtime and cross-workstream checks in a prepared integration runtime. Use targeted tests while iterating and one affected aggregate suite after the diff stabilizes. `_workspace`, snapshot, and handoff records are optional coordination aids.

## Failure rules

- Routing unavailable: use current canonical Stub/Replay and explicit unsupported/`PARTIAL`; live integration remains `UNVERIFIED`.
- Shared contract drift affecting this task: stop that boundary and diagnose; report unrelated baseline drift separately.
- Public/private mismatch: report exact producer/consumer paths; do not hide it with `any`, casts, duplicate DTOs, or frontend recomputation.
- Do not issue `GO`/`NO_GO` for an ordinary source implementation.
