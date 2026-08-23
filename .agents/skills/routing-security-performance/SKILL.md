---
name: routing-security-performance
description: "Private Django Routing API와 Provider/model runtime의 service authentication, SSRF·secret·schema trust, model artifact integrity, quota·Denial of Wallet, 6.5초 internal deadline, concurrency·cache·load shedding·SLO를 설계·검증한다. Routing 성능·보안·비용 작업 시 사용한다."
---

# Routing Security and Performance

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


## Security

- private ingress + service identity/JWT audience
- Provider URL allowlist, parameter validation, response schema validation
- no user identity
- secrets manager/rotation/redaction
- artifact allowlist/hash/schema/read-only runtime
- raw payload storage policy
- admin model/cache endpoint authorization and audit

## Performance and cost

- 전체 internal hard deadline <= 6.5초
- provider별 timeout/retry budget
- bounded candidate and exact enrichment
- provider semaphore/single-flight/cache/stale policy
- batch model inference
- quota burn/cost per search
- load shedding order and partial result

## 검증

cold/warm cache, timeout, 429, schema drift, dense hubs, 10/50/100 concurrency, identical burst, coordinate sweep를 측정한다. latency만이 아니라 provider call count, candidate count, cost, partial rate를 함께 기록한다.
