# Routing & Intelligence Harness — Workstream Index

## 미션

Provider, canonical mapping, Bus Intelligence, time-dependent optimization과 `POST /v1/routes/optimize` 경계를 다룬다. 아래 spec/backlog는 목표·참고 자료이며, 현재 구현에 없는 provider/model을 routine 작업의 선행조건으로 만들지 않는다.

## 작업별 공통 원본

공유 API·데이터 의미가 바뀌거나 integration/release를 수행할 때만 관련 항목을 읽고 live lock을 검증한다.

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
- `EXECUTION_PLAYBOOK.md` — implementation-first 범위 선택, evidence reuse, runtime별 검증

## Workstream 주 경로

```text
src/services/routing-api/**
src/packages/routing-domain/**
src/packages/bus-intelligence-core/**
src/packages/provider-core/**
src/workers/**
src/docs/harnesses/routing-intelligence/**
```

이 목록은 agent의 상시 소유권이 아니다. 실제 write scope는 task가 정한다.

Local implementation은 primary가 직접 수행하는 것이 기본이다. 전체 dependency chain, agent team, workspace handoff, release evidence는 요청된 결과나 실제 diff가 필요로 할 때만 활성화한다.
