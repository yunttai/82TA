# Contract Changelog

## Context 1.0.1 — Codex harness migration

- Replaced active Claude-only controls with Codex-native `AGENTS.md`, `.agents/skills`, `.codex/agents`, project config, and durable work-plan coordination.
- Product contract version remains 1.0.0; business OpenAPI, DBML, PRD and algorithms are unchanged.

## 1.0.0 — 2026-08-23

- Public Service API와 Private Routing API 분리
- Coordinate, MoneyRange, TimeEstimate, Provenance, RouteLeg, RouteCandidate 공통 schema
- Service DB와 Routing DB의 소유권 분리
- reason·warning·error code registry
- 두 하네스의 단일 context manifest와 contract hash lock 도입
