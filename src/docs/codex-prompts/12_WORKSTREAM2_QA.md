# 12. 2번 단독 QA

**사용 시점:** Service와 합치기 전 Routing 검증

```text
$routing-incremental-qa

Routing & Intelligence만 통합 전 검증해줘. 먼저 findings만 작성한다.

Adapter schema/failure/cache/quota, mapping precision/direction, label/trip leakage, ETA/Seat/calibration, expected wait, candidate/time progression, transfer, strict budget, Pareto, Private OpenAPI, no identity/cross-DB, replay, P95, security를 검사하라.

finding마다 severity, 파일/심볼, fixture/replay, invariant, owner, retest를 기록하고 PASS/CONDITIONAL/FAIL/UNVERIFIED로 판정하라.
```
