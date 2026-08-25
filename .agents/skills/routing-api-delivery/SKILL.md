---
name: routing-api-delivery
description: "Django private Routing API의 /v1/routes/optimize, capabilities, health, version, 관리자 model/cache endpoint를 application use case와 순수 routing domain에 연결하고 service authentication·deadline·idempotency·partial response를 구현한다. Routing API endpoint·serializer·application orchestration 작업 시 사용한다."
---

# Routing API Delivery

## 작업 범위 확인

1. 적용되는 `AGENTS.md`, 현재 endpoint/use case, 직접 영향받는 테스트를 읽는다.
2. request/response 또는 의미가 바뀔 때만 private OpenAPI, common components, examples와 Service consumer를 함께 읽는다.
3. 가장 작은 관련 검증을 우선한다. 전체 repository/lock 검증과 context parity는 공유 경계·통합·릴리스에 사용한다.
4. `_workspace` snapshot은 선택적 진단이며 최신성의 근거가 아니다.

## 경계

Django API는 인증·schema validation·deadline·idempotency·use-case invocation·serialization을 담당한다. 후보 생성·Pareto·Bus Intelligence 계산은 `src/packages/`의 순수 domain/application port에서 수행한다. Provider raw JSON을 endpoint에서 직접 해석하지 않는다.

## 워크플로우

1. OpenAPI operation과 error/partial semantics를 고정한다.
2. service-to-service JWT 또는 workload identity를 검증한다.
3. `X-Correlation-Id`, `X-Request-Deadline`, `Idempotency-Key`를 처리한다.
4. request DTO를 application command로 변환한다.
5. provider/model/domain port를 주입한 `OptimizeRouteUseCase`를 호출한다.
6. deadline이 부족하면 optional enrichment를 취소하고 안전한 PARTIAL을 만든다.
7. domain result를 contract response로 직렬화하되 의미·단위를 바꾸지 않는다.
8. capabilities, live/ready, version에 provider·model·ranking 상태를 연결한다.
9. 관리자 endpoint는 private auth·audit·allowlist를 적용한다.
10. contract·integration·deadline·security test를 작성한다.

## 필수 금지

- user ID·email·saved place label 수신
- Service DB 조회
- request로 model artifact path 선택
- 내부 stack trace·provider secret·raw payload 응답
- 200 COMPLETE로 provider/model 실패 숨김
- Django ORM object를 domain package에 전달

## 저장 위치

- `src/services/routing-api/**`
- 관련 contract/replay/security tests는 `src/tests/**`
- 공통 계약 변경은 `shared-contract-governance`로 전환한다.
