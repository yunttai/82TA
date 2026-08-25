---
name: service-incremental-qa
description: "Service 기능이 완성될 때마다 Public API 응답↔generated TS client↔React hook/UI, Routing response↔Service projection, Service DBML↔Django model/migration, URL↔page, 상태전이를 교차 검증한다. Frontend·Backend 모듈 완료 직후와 Service 릴리스 전에 사용한다."
---

# Service Incremental QA

## 작업 범위 확인

1. 적용되는 `AGENTS.md`, 현재 구현, 직접 영향받는 테스트를 읽는다.
2. 공유 API·데이터 의미를 소비하거나 바꿀 때만 manifest, lock, 관련 canonical 계약과 실제 producer·consumer를 읽는다.
3. 작업 전후 가장 작은 관련 검증을 실행한다. 전체 repository/lock 검증은 공유 경계·통합·릴리스 또는 drift 조사에 사용한다.
4. 기존의 무관한 실패는 baseline으로 분리해 보고하고, 현재 작업을 무효화할 때만 중단한다.

제품 산출물은 `src/`에 두고 CI/CD는 `.github/`에 둘 수 있다. `_workspace/`는 선택적·gitignored 메모이며 최신 상태의 근거가 아니다. 공통 PRD·OpenAPI·ERD·enum 복사본은 만들지 않는다.


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
