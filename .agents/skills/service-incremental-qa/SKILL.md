---
name: service-incremental-qa
description: "Service 기능이 완성될 때마다 Public API 응답↔generated TS client↔React hook/UI, Routing response↔Service projection, Service DBML↔Django model/migration, URL↔page, 상태전이를 교차 검증한다. Frontend·Backend 모듈 완료 직후와 Service 릴리스 전에 사용한다."
---

# Service Incremental QA

## 공통 사전 조건

작업을 시작하기 전에 반드시 다음을 수행한다.

1. `python src/scripts/validate_repository.py`를 실행한다.
2. `python src/scripts/verify_contract_lock.py`를 실행한다.
3. `src/contracts/CONTEXT_MANIFEST.json`과 `src/contracts/CONTRACT_LOCK.json`을 읽는다.
4. `src/docs/shared/PROJECT_CONTEXT.md`, `PRD.md`, 관련 canonical 계약을 읽는다.
5. 이전 `_workspace/` 산출물이 있으면 미완료·피드백·차단 사항을 확인한다.

검증 실패 시 구현을 진행하지 않는다. 공통 원본을 임의로 맞춰 쓰지 말고 drift 또는 change request로 처리한다.

## 저장 위치 규칙

- 분석·토론·중간 결과: `_workspace/{workstream}/`
- 검토가 끝난 제품 코드·문서·테스트·인프라: 반드시 `src/` 아래
- 루트에는 `.codex/`, `.agents/`, `_workspace/`, `src/`, `AGENTS.md`, `README.md`, `.gitignore`만 둔다.
- 공통 PRD·OpenAPI·ERD·enum 복사본을 workstream 폴더에 만들지 않는다.


## 검증 우선순위

1. 경계면 정합성
2. 기능 요구사항
3. 보안·개인정보
4. 접근성·responsive
5. 코드 품질

## 필수 교차 비교

- Public serializer 실제 shape ↔ TS client/hook 기대 shape
- Routing fixture ↔ generated Python client ↔ projection
- DBML ↔ model ↔ migration ↔ serializer
- route/page 파일 ↔ href/router path
- status transition ↔ UI branch
- code registry ↔ 문구 renderer
- capability false ↔ disabled/hidden controls

## 실행

- module 완료 시 관련 범위만 빠르게 검증
- vertical slice 완료 시 mock E2E
- staging 합류 시 real Routing E2E
- release 시 `integration-coherence-qa`로 승격

## 출력

PASS/FAIL/UNVERIFIED, production/consumer file pair, evidence, retest를 `src/tests/`에 기록한다.
