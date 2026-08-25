# Contract Changelog

## Context 1.4.1 — 2026-08-25

- Accepted GCE as the only supported cloud compute deployment platform and
  removed the alternate-cloud Terraform, runbooks and CI/CD templates.
- Made the implemented single-GCE-VM Docker Compose workflow the honest current
  baseline without relabeling its development flags, SQLite or internal HTTP as
  production-ready.
- Replaced cloud model/data artifact identities with canonical `gs://` URIs while
  preserving bucket allowlists, path canonicalization, safe formats and SHA-256
  verification.
- Added GCE Terraform for the VM/network/static IP/firewall/runtime identity and a
  private versioned GCS artifact bucket. Exact Google managed-service topology is
  intentionally not frozen by the harness.
- Contract version remains `1.4.0`; OpenAPI, DBML, events, code registry, generated
  clients, ranking and public/private API wire semantics are unchanged.

## 1.4.0 — 2026-08-24

- Added optional `RouteLeg.waitDuration` and `RouteLeg.travelDuration` to preserve
  the optimizer's separate bus/rail boarding wait, Taxi dispatch wait and movement
  time through Routing, Service and Web.
- Kept `duration` and `totalDuration` authoritative and unchanged. Existing 1.x
  consumers can ignore the additive fields; absence remains distinct from known zero.
- Added optional nullable `PlaceRef.address` so the Service place proxy preserves
  Kakao Local's road address, with parcel address as fallback. Existing consumers
  may ignore the field and new consumers hide the address row when it is absent.
- No DBML, migration, event, code-registry, ranking, budget or route-ID change.

## Routing policy provenance activation — 2026-08-24

- Accepted the implemented minimum-arrival correction only for the finite canonical
  graph constructed from the admitted Provider payload. Within that bounded graph,
  `FASTEST` is the deterministic exact P50 anchor and `PUBLIC_TRANSIT_ONLY` is the
  deterministic exact zero-Taxi-upper-cost anchor; epsilon dominance remains a
  display/frontier compression policy. This is not a network-global optimality
  claim.
- Assigned immutable executable-policy identifiers `rank-0.2.0` and
  `strategy-2.0.0`. The latter identifies the combined finite-payload admission,
  strategy generation, exactification, and graph-search policy. Historical
  `rank-0.1.1` and `strategy-1.0.0` results remain historical and must not be
  relabeled or replayed under the new identifiers.
- Kept every uncertified candidate, exactification, and graph-search hard-cap path
  fail-closed through the existing capacity/error boundary. No completeness field,
  status, warning/error code, OpenAPI schema, DBML, event, or generated-client change
  is approved by this entry.
- Deferred the `transferCount`/`maxTransfers` meaning (CCR-008 Finding A) and additive
  search-completeness wire proposal (Finding C). Contract/context versions remain
  `1.3.0`; this is an opaque policy-provenance and deterministic-result update.

## 1.3.0 — 2026-08-24

- Extended email registration with a required profile nickname, an explicit current
  consent-document version, mandatory `SERVICE_PRIVACY` acceptance, and four
  independently selected optional consent purposes.
- Added optional `SessionContext.nickname`, the Service profile nickname target
  column, and the registered `SERVICE_PRIVACY` consent type. Existing consumers may
  ignore the additive session field.
- Kept the unchanged Private Routing OpenAPI and generated Python client at
  repository metadata `1.1.0`, the optimize wire family at `1.0`, and executable
  ranking provenance at `rank-0.1.1`.

## 1.2.0 — 2026-08-24

- Added backward-compatible email registration and login operations using the
  existing Service-owned account and authenticated-session tables.
- Added optional `SessionContext.email` plus registered generic-login and
  duplicate-account Problem codes; Routing contracts, events, and DB ownership are
  unchanged.

## 1.1.0 — 2026-08-23

- Corrected the first Service↔Routing integration baseline: Public route search now
  documents the existing safe `422` and `504` Problems, all four canonical route
  examples are one deterministic sanitized R1 translator→producer→projection
  chain, Routing `/v1/version` reports repository metadata `1.1.0`, and ranking
  provenance is consistently `rank-0.1.1`. The obsolete illustrative
  `NO_SEAT_DATA_FOR_ROUTE` message was removed; the producer example now uses the
  already registered `BUS_DATA_UNAVAILABLE` warning with provider message codes
  left `null`. The optimize wire family remains `1.0`; no ranking behavior, DB
  schema, event, or code-registry member changed.
- Added backward-compatible guest/session inspection and revocation, consent, saved-place/favorite detail mutation, and asynchronous data export/deletion Public operations.
- Added preference ETag/`If-Match` overlap semantics, history ownership metadata, and documented Public 403/502 responses.
- Defined deterministic Service→Routing mapping for DEPART_AT, allowed modes, seat-risk preference, baseline, support, and history opt-in; ARRIVE_BY remains explicit `ARRIVE_BY_UNSUPPORTED` until supported by Routing.
- Expanded Service DB for authenticated session revocation, soft-delete timestamps, history retention, and data-rights jobs.
- Added optional Private seat-risk preference and Bus Intelligence coverage fields without moving any Routing calculation into Service.
- Domain events are unchanged; all additions are compatible-minor or expand-only.
- Corrected `SavedPlace` and `FavoriteJourney` output schemas to flattened Draft 2020-12-valid objects; wire fields and required-field semantics are unchanged.
- Aligned place-suggestion query validation with the established Service requirement by enforcing a two-character minimum.
- Documented canonical `RATE_LIMITED` Problem responses (`429`) for place suggestion and reverse geocoding.

## Context 1.0.1 — Codex harness migration

- Replaced active Claude-only controls with Codex-native `AGENTS.md`, `.agents/skills`, `.codex/agents`, project config, and durable work-plan coordination.
- Product contract version remains 1.0.0; business OpenAPI, DBML, PRD and algorithms are unchanged.

## 1.0.0 — 2026-08-23

- Public Service API와 Private Routing API 분리
- Coordinate, MoneyRange, TimeEstimate, Provenance, RouteLeg, RouteCandidate 공통 schema
- Service DB와 Routing DB의 소유권 분리
- reason·warning·error code registry
- 두 하네스의 단일 context manifest와 contract hash lock 도입
