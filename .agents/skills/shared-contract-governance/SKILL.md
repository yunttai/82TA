---
name: shared-contract-governance
description: "Govern shared PRD semantics, OpenAPI, DBML, events, enums, reason/warning/error codes, examples, compatibility, context snapshots, and contract locks. Use before any cross-workstream contract or data-boundary change."
---
# Shared Contract Governance

1. Validate repository and lock.
2. Read both workstream STATUS/HANDOFF files.
3. Create a change request under `_workspace/integration/` before editing canonical files.
4. Identify product semantic, producer, consumer, DB, event, code registry, generated client and migration impact.
5. Prefer backward-compatible optional additions. Breaking changes require ADR, major version and migration/overlap plan.
6. Update the atomic set: PRD/acceptance if needed, OpenAPI, DBML, events, codes, examples, compatibility docs and traceability.
7. Delegate review to `contract-steward`, `architecture-auditor` and `integration-qa` when useful; primary thread consolidates.
8. Regenerate clients under `src/generated/` only.
9. Run producer/consumer contract tests.
10. Only after both workstream approvals run `python src/scripts/update_contract_lock.py --approved-change`.
11. Snapshot service-product, routing-intelligence and integration; compare parity.
12. Update handoffs and changelog.

Never copy canonical DTOs into a workstream. Never update the lock to conceal unreviewed drift.
