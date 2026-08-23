---
name: service-backend-delivery
description: "Django Service Backend의 Public API, 인증·guest ownership, Kakao Local proxy, request validation, RoutingGateway, 결과 projection, history·favorite·preference를 계약 기반으로 구현·수정한다. Service API·serializer·view·gateway 작업 시 사용한다."
---

# Service Backend Delivery

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


## 경계

Service는 사용자와 Public API를 소유한다. Provider 조율, Kakao↔GBIS 매핑, 모델, 후보·Pareto·ranking을 구현하지 않는다.

## 워크플로우

1. Public OpenAPI operation과 requirement를 선택한다.
2. domain/application/infrastructure/API 경계를 정의한다.
3. generated Routing Python client 뒤에 `RoutingGateway`를 구현한다.
4. correlation ID, deadline, idempotency를 전달한다.
5. Routing response를 재계산하지 않고 public-safe projection만 수행한다.
6. guest/user ownership, session, CSRF, rate limit, cache를 구현한다.
7. exact coordinate·raw provider·plate·artifact URI가 log/response에 새지 않는지 검사한다.
8. serializer contract·DB transaction·integration test를 작성한다.
9. Frontend fixture를 갱신하고 incremental QA를 요청한다.

## 대체 Adapter

- `HttpRoutingGateway`: 실제 private API
- `StubRoutingGateway`: 병렬 개발
- `ReplayRoutingGateway`: 회귀·장애
- `InProcessRoutingGateway`: 미래 통합, contract DTO 유지

## 출력

`src/services/service-api/**`, 관련 Service test만 수정한다.
