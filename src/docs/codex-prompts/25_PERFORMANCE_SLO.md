# 25. 성능·SLO 최적화

**사용 시점:** P95 7초/비용 문제

```text
$routing-security-performance

[시나리오]의 성능·신뢰성을 측정하고 P95 7초 목표를 맞춰줘.

- cold/warm, Provider 지연, cache hit/miss, candidate dense, concurrent, identical burst, matrix unavailable를 분리한다.
- trace로 validation/transit/taxi/GBIS/model/optimizer/serialization을 측정한다.
- Provider calls, candidate count, DB/Redis, CPU/memory, cost/search를 기록한다.
- 정확성/strict budget/partial semantics를 희생하지 않는다.
- optional enrichment/candidate cap/cache/single-flight/deadline/circuit 조정안을 제시한다.
- before/after P50/P95/P99와 regression tests를 보고한다.
```
