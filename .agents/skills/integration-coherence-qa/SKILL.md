---
name: integration-coherence-qa
description: "Verify the Service↔Routing boundaries actually touched by an integration, contract change, conflict resolution, or release. Scale evidence to source merge versus deployment readiness."
---
# Integration Coherence QA

Start from the current implementation and diff. Optional agents and `_workspace` notes may be used for large independent checks, but are not prerequisites.

Reuse passing evidence when the affected producer, consumer, fixture, generated artifact, and configuration have not changed. Do not rerun live lock, snapshot, E2E, security, or performance checks for an unchanged boundary on every continuation.

## Source-merge checks

For an ordinary merge, verify only affected boundaries:

1. changed producer response ↔ consumer/client/UI usage
2. changed DBML ↔ model/migration ownership
3. changed reason/warning/error/capability semantics
4. applicable invariants such as strict budget, time propagation, null/unknown/unsupported, privacy, and no cross-DB access
5. targeted contract/integration/replay tests and source layout

An optional external provider, model, or environment may remain `UNVERIFIED` when the implementation keeps the capability disabled, unsupported, or explicitly `PARTIAL`. That does not block an unrelated source merge.

## Integration/release checks

For cross-workstream integration or deployment, additionally verify live contract locks, generated clients, representative replay/E2E, security, performance, provider quota/fallback, and environment-specific rollback evidence. Use `compare_context_snapshots.py` to compare verified live locks, not old snapshot files. Run each suite in its owning Service, Routing, or prepared integration runtime.

Use `PASS`, `CONDITIONAL`, `FAIL`, or `UNVERIFIED` only when the user requested integration/readiness judgment. Issue `GO`/`NO_GO` only for an explicit deployment or release gate. Ordinary implementation QA reports the affected assertions and regressions without inventing a release verdict. A `FAIL` blocks the affected boundary; `UNVERIFIED` blocks only a release or capability claim that depends on that evidence.
