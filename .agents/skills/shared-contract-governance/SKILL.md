---
name: shared-contract-governance
description: "Govern cross-workstream API/data semantics, compatibility, canonical artifacts, generated clients, and contract locks. Use when a shared boundary or meaning actually changes, not for unrelated local edits."
---
# Shared Contract Governance

An internal algorithm, search completeness, cache, provider-call accounting, or implementation metadata change is not automatically a contract change. If the published shape, units, status/error semantics, and producer-consumer meaning stay the same, implement and test it locally without a speculative CCR, ADR, field, or lock update.

1. Inspect the current producer, consumer, relevant canonical files, generated clients, and contract lock.
2. State the requested semantic change and identify its real API, persistence, event, code-registry, documentation, privacy, and migration impact. Mark unaffected surfaces explicitly; do not edit them.
3. Prefer backward-compatible optional additions. Breaking changes require an explicit decision, compatibility window, migration, and rollback plan.
4. Use a CCR or ADR for breaking meaning, ownership boundaries, production cloud/provider strategy, security/privacy policy, or other hard-to-reverse decisions. Routine additive changes need only the affected changelog/compatibility record.
5. Update the smallest coherent set:
   - API change: relevant OpenAPI/examples/generated clients/producer-consumer tests.
   - Persistence change: relevant DBML/model/migration/data tests.
   - Event or code change: relevant schema/registry and consumers.
   - Acceptance text only when product meaning changes.
6. Run affected producer/consumer checks and compatibility review.
7. Update `CONTRACT_LOCK.json` only after the task authorizes the intentional canonical diff. Never update it to conceal drift.
8. Compare live verified locks for integration. Snapshots and `_workspace` change requests are optional evidence, not prerequisites.

Never copy canonical DTOs, ERDs, or enums into a workstream.
