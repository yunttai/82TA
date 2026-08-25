---
name: service-backend-delivery
description: "Django Service Backend의 Public API, 인증·guest ownership, Kakao Local proxy, request validation, RoutingGateway, 결과 projection, history·favorite·preference를 계약 기반으로 구현·수정한다. Service API·serializer·view·gateway 작업 시 사용한다."
---

# Service Backend Delivery

## 작업 범위 확인

1. 적용되는 `AGENTS.md`, 현재 구현, 직접 영향받는 테스트를 읽는다.
2. 공유 API·데이터 의미를 소비하거나 바꿀 때만 manifest, lock, 관련 canonical 계약과 실제 producer·consumer를 읽는다.
3. 작업 전후 가장 작은 관련 검증을 실행한다. 전체 repository/lock 검증은 공유 경계·통합·릴리스 또는 drift 조사에 사용한다.
4. 기존의 무관한 실패는 baseline으로 분리해 보고하고, 현재 작업을 무효화할 때만 중단한다.

요청이 rate limit·idempotency의 process 간 coordination이면 그 소비자, backend wiring, 직접 테스트까지만 기본 범위로 삼는다. Kakao Local 또는 Routing Provider 응답 캐싱, TTL·약관·위치 key 정책, 배포 환경 확대는 명시적으로 요청되거나 실제 diff가 그 경계를 바꿀 때만 포함한다. 인접 기능의 미결정은 현재 slice의 차단 사유가 아니다.

공유 infra나 CI 파일도 실제로 겹치는 writer/diff가 있을 때만 조율한다. 경로가 shared라는 이유만으로 승인 대기하지 않는다. 사용자가 working PR CI를 요청했다면 repository-local 검증 활성화는 구현 범위이며, secret·permission·배포·외부 상태 변경이 동반될 때만 별도 권한을 확인한다.

제품 산출물은 `src/`에 두고 CI/CD는 `.github/`에 둘 수 있다. `_workspace/`는 선택적·gitignored 메모이며 최신 상태의 근거가 아니다. 공통 PRD·OpenAPI·ERD·enum 복사본은 만들지 않는다.


## 경계

Service는 사용자와 Public API를 소유한다. Provider 조율, Kakao↔GBIS 매핑, 모델, 후보·Pareto·ranking을 구현하지 않는다.

## 워크플로우

아래 항목은 변경에 해당하는 단계만 선택한다. 모든 Service Backend 작업의 일괄 완료 목록이 아니다.

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
