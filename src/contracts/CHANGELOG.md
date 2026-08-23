# Contract Changelog

## 1.1.0 — 2026-08-23

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
