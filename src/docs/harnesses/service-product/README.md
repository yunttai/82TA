# Service Product Harness — Workstream Index

## 미션

React Web App/PWA와 Django Service Backend를 구현하여 사용자가 장소·예산·시각·제약을 입력하고 Routing 결과를 안전하고 이해 가능한 형태로 사용하는 제품 경험을 완성한다.

## 공통 원본

작업 시작 전 다음을 읽고 hash를 검증한다.

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

## 소유 경로

```text
src/apps/web/**
src/services/service-api/**
src/docs/harnesses/service-product/**
```

공동 경로는 계약 변경 절차 없이는 수정하지 않는다.
