# Routing & Intelligence Harness — Workstream Index

## 미션

실시간·과거 교통 데이터를 canonical model로 정규화하고, Bus Intelligence와 time-dependent multimodal optimization을 이용해 `POST /v1/routes/optimize` 계약을 구현한다.

## 공통 원본

- `src/docs/shared/*`
- `src/contracts/openapi/routing-private.v1.yaml`
- `src/contracts/openapi/common/components.v1.yaml`
- `src/contracts/database/routing-db.dbml`
- `src/contracts/codes/reason-warning-error-codes.yaml`

## 문서

- `WORKSTREAM_PRD.md`
- `ALGORITHM_SPEC.md`
- `MODEL_SPEC.md`
- `PROVIDER_SPEC.md`
- `DATA_MIGRATION_SPEC.md`
- `EPIC_BACKLOG.md`
- `DEFINITION_OF_DONE.md`
- `HANDOFF_CONTRACT.md`
- `TEST_MATRIX.md`

- `SOURCE_LAYOUT.md` — private API·순수 package·worker 배치
- `EXECUTION_PLAYBOOK.md` — Phase별 팀 재구성과 handoff 절차

## 소유 경로

```text
src/services/routing-api/**
src/packages/routing-domain/**
src/packages/bus-intelligence-core/**
src/packages/provider-core/**
src/workers/**
src/docs/harnesses/routing-intelligence/**
```
