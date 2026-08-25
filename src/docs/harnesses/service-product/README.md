# Service Product Harness — Workstream Index

## 미션

React Web App/PWA와 Django Service Backend의 제품 경험을 다룬다. 이 디렉터리의 backlog와 spec은 계획·참고 자료이며, 현재 구현에 없는 항목을 routine 작업에서 자동으로 강제하지 않는다.

## 공통 원본

공유 API·데이터 의미를 바꾸는 작업에서만 아래 관련 원본과 hash를 확인한다. local UI/API patch는 현재 source와 직접 소비하는 계약만 읽는다.

- `src/docs/shared/PROJECT_CONTEXT.md`
- `src/docs/shared/PRD.md`
- `src/contracts/openapi/service-public.v1.yaml`
- `src/contracts/openapi/routing-private.v1.yaml`
- `src/contracts/database/service-db.dbml`
- `src/contracts/database/routing-db.dbml`
- `src/contracts/codes/reason-warning-error-codes.yaml`

이 디렉터리는 공통 계약의 복사본을 만들지 않는다.

## 문서

- `WORKSTREAM_PRD.md` — 1번 작업흐름 범위와 요구사항
- `EPIC_BACKLOG.md` — 구현 가능한 Epic·Task·Acceptance
- `DEFINITION_OF_DONE.md` — 완료 조건
- `HANDOFF_CONTRACT.md` — Routing과의 경계·합류 규칙
- `TEST_MATRIX.md` — Frontend·Service·경계 QA
- `UX_INFORMATION_ARCHITECTURE.md` — 화면·상태·정보 구조

- `SOURCE_LAYOUT.md` — 실제 React·Django 코드의 `src/` 하위 배치
- `EXECUTION_PLAYBOOK.md` — 기능 단위 하네스 실행 절차

## Workstream 주 경로

```text
src/apps/web/**
src/services/service-api/**
src/docs/harnesses/service-product/**
```

이 목록은 agent의 상시 소유권이 아니다. 실제 write scope는 task가 정하며, 공동 경로는 실제 영향받는 producer·consumer와 compatibility를 확인한다.

Local implementation은 primary가 직접 수행하는 것이 기본이다. Full team, workspace handoff, snapshot, release evidence는 요청된 결과나 실제 diff가 필요로 할 때만 활성화한다.
