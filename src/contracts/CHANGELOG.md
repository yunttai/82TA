# Contract Changelog

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
