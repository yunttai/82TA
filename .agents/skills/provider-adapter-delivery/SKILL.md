---
name: provider-adapter-delivery
description: "Kakao Transit/Walk/Mobility, GBIS, KMA, GITS, TMAP/ODsay 등 교통 Provider의 capability probe, adapter, canonical normalization, timeout·retry·circuit breaker·cache, schema drift, sanitized fixture를 구현·검증한다. 외부 교통 API 연동 작업 시 사용한다."
---

# Provider Adapter Delivery

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
