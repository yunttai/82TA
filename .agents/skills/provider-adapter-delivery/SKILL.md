---
name: provider-adapter-delivery
description: "Kakao Transit/Walk/Mobility, GBIS, KMA, GITS, TMAP/ODsay 등 교통 Provider의 capability probe, adapter, canonical normalization, timeout·retry·circuit breaker·cache, schema drift, sanitized fixture를 구현·검증한다. 외부 교통 API 연동 작업 시 사용한다."
---

# Provider Adapter Delivery

## 작업 범위 확인

1. 적용되는 `AGENTS.md`, 현재 구현, 직접 영향받는 테스트를 읽는다.
2. 공유 API·데이터 의미를 소비하거나 바꿀 때만 manifest, lock, 관련 canonical 계약과 실제 producer·consumer를 읽는다.
3. 작업 전후 가장 작은 관련 검증을 실행한다. 전체 repository/lock 검증은 공유 경계·통합·릴리스 또는 drift 조사에 사용한다.
4. 기존의 무관한 실패는 baseline으로 분리해 보고하고, 현재 작업을 무효화할 때만 중단한다.

제품 산출물은 `src/`에 두고 CI/CD는 `.github/`에 둘 수 있다. `_workspace/`는 선택적·gitignored 메모이며 최신 상태의 근거가 아니다. 공통 PRD·OpenAPI·ERD·enum 복사본은 만들지 않는다.


## 원칙

- 공식 문서 존재, 현재 key 성공, 상용 승인 상태를 분리한다.
- endpoint URL은 allowlist이고 사용자 입력 URL을 받지 않는다.
- raw response는 infrastructure 밖으로 누출하지 않는다.
- observedAt, receivedAt, schemaVersion, freshness, quality flag를 보존한다.
- online 필수와 collector cache 데이터를 구분한다.

## 워크플로우

1. capability matrix와 약관·쿼터를 확인한다.
2. sanitized success/empty/error/timeout/429/schema-drift fixture를 만든다.
3. Protocol interface와 Provider Envelope를 구현한다.
4. raw schema를 검증하고 canonical DTO로 변환한다.
5. timeout/retry/deadline/breaker/semaphore/single-flight/cache를 적용한다.
6. failure를 partial/fallback/fatal로 분류한다.
7. contract·fixture·resilience·cost telemetry test를 작성한다.
8. Routing QA에 raw↔canonical 비교를 요청한다.

## 출력

- adapter/core: `src/packages/provider-core/**`
- Routing glue: `src/services/routing-api/**`
- collector: `src/workers/transport-collector/**`
- fixtures/tests: `src/tests/**`
