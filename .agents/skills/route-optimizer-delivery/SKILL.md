---
name: route-optimizer-delivery
description: "순수 Python routing domain의 graph/candidate search, leg-entry-time cost, strict budget, transfer feasibility, Pareto와 ranking을 현재 production call path에 구현·검증한다. 경로 알고리즘 작업 시 사용한다."
---

# Route Optimizer Delivery

## 구현 우선

1. 적용되는 `AGENTS.md`, 실제 optimizer 진입점과 호출 경로, 인접 테스트를 읽는다.
2. 관계 확인이 필요하면 CodeGraph를 affected symbol 기준으로 한 번 사용하고 바로 구현한다. 현재 task에서 이미 확인한 경로는 관련 코드가 바뀌지 않았다면 재조사하지 않는다.
3. 실패를 재현하는 작은 counterexample/property test를 만든 뒤 production path의 최소 gap을 수정한다.
4. 반복 중 targeted test를 실행하고 diff가 안정된 뒤 관련 Routing aggregate suite를 한 번 실행한다. 공유 경계가 그대로면 full repository, snapshot, ledger, ADR/CCR, release gate를 요구하지 않는다.

외부 Provider key나 production approval은 live adapter 작업에만 필요하다. Canonical fixtures와 offline graph로 수행할 수 있는 순수 domain 구현의 blocker가 아니다.

## Domain independence

`src/packages/routing-domain`은 Django request·ORM·settings·Provider raw JSON을 import하지 않는다. 입력은 canonical typed object와 clock/policy/model result다.

## 알고리즘 지침

현재 구현의 graph search, pattern pipeline, 또는 두 방식의 조합을 유지·확장한다. 문서에 적힌 특정 내부 단계만 맞추려고 동작하는 구현을 교체하지 않는다.

- 각 leg 진입시각으로 뒤 leg의 schedule/cost를 평가한다.
- 모든 taxi leg의 upper cost와 dispatch wait를 누적하고 strict feasibility 전에 인증한다.
- transfer P50/P90 margin, candidate/provider call bound, Pareto/epsilon dominance, 대표 ranking 의미를 보존한다.
- exact taxi/walk/mapping/bus enrichment가 선택적이면 timeout 시 affected candidate를 버리거나 기존 fallback/`PARTIAL`/no-feasible-route 의미를 사용한다. 이를 자동으로 504로 바꾸지 않는다.
- strict cost 또는 필수 feasibility 값이 unknown이면 그 후보를 feasible로 통과시키지 않는다.

## 필수 불변식

- 모든 taxi leg의 `sum(taxiCost.upper) <= budget`
- `P90 >= P50`
- leg time non-decreasing
- 사용자 도착 전 버스 제외
- 일반버스 crowded를 기본 승차 실패 penalty로 사용하지 않음
- frontier에 완전 지배 후보 없음
- candidate/provider call 상한 존재
- 같은 canonical input·clock·policy는 결정적 결과 생성
