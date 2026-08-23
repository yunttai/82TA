---
name: integration-coherence-qa
description: "Verify Service and Routing context parity, API producer-consumer compatibility, DB ownership, generated clients, code registry, replay, security, performance and merge readiness. Use before first integration, recurring integration, merge, release, or after conflict."
---
# Integration Coherence QA

Primary thread creates `_workspace/integration/WORKPLAN.md`, delegates independent checks to `integration-qa`, `architecture-auditor`, `contract-steward`, and relevant QA/security/performance agents, waits, then consolidates.

Mandatory gates:

1. repository and contract lock
2. service/routing context snapshots same aggregate SHA-256
3. Public OpenAPI ↔ Service implementation/client/UI
4. Private OpenAPI ↔ Routing producer ↔ Service consumer
5. DBML ↔ ORM/migrations; no cross-DB access
6. reason/warning/error registry across domain/API/UI
7. no user identity in Routing
8. deterministic replay and representative routes
9. PARTIAL/null/unknown/unsupported semantics
10. strict taxi upper-budget and temporal invariants
11. security/privacy
12. P95 7-second goal and Provider quota/fallback
13. source layout

Verdict: PASS, CONDITIONAL, FAIL, UNVERIFIED. No merge while mandatory gate is FAIL or UNVERIFIED unless an explicit accepted-risk record names owner, expiry and mitigation.
