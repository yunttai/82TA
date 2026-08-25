---
name: routing-security-performance
description: "Private Django Routing API와 Provider/model runtime의 service authentication, SSRF·secret·schema trust, model artifact integrity, quota·Denial of Wallet, 6.5초 internal deadline, concurrency·cache·load shedding·SLO를 설계·검증한다. Routing 성능·보안·비용 작업 시 사용한다."
---

# Routing Security and Performance

## 범위 선택

Focused security/performance fix는 현재 diff와 직접 관련된 threat, deadline, quota, cache, candidate bound만 구현·검증한다. 전체 threat model, concurrency matrix, environment SLO, release blocker 판정은 사용자가 보안 감사·benchmark·release readiness를 요청했을 때만 수행한다.

반복 작업에서는 관련 source/config가 바뀌지 않은 green evidence를 재사용한다. Routing tests는 Routing runtime에서 실행하고, Service security tests는 Service runtime에서 별도로 실행한다. 하나의 불완전한 환경으로 `src/tests/security`나 `src/tests/performance` 전체를 수집하지 않는다.

## Security

- private ingress + service identity/JWT audience
- Provider URL allowlist, parameter validation, response schema validation
- no user identity
- managed secret storage/rotation/redaction
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

## 실패 의미

- service authentication, SSRF/allowlist, response schema trust, secret handling, artifact integrity는 fail closed다.
- strict budget/feasibility를 인증하는 필수 값이 없으면 해당 후보를 허용하지 않는다.
- optional exactification/enrichment의 timeout·429·deadline은 affected candidate drop 또는 현재 계약의 fallback/`PARTIAL`/no-feasible-route로 처리한다. blanket 5xx/504를 보안 원칙으로 강제하지 않는다.
- provider key·quota·approval 부재는 live production claim을 막지만 offline domain/fixture 검증은 막지 않는다.

## 검증 수준

Routine patch는 관련 timeout/429/schema/deadline counterexample와 provider call/candidate bound만 측정한다. 명시적 load benchmark 또는 release에서는 cold/warm cache, dense hubs, agreed concurrency levels, identical burst, coordinate sweep와 latency/provider call/candidate/cost/partial rate를 함께 기록한다. `10/50/100`은 기본 의무가 아니라 benchmark plan의 한 선택이다.
