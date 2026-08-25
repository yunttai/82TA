# Routing & Intelligence — proportionate Definition of Done

현재 변경이 닿는 계층에만 완료 조건을 적용한다. Provider, mapping, model, replay, performance evidence를 모든 Routing 수정에 일괄 요구하지 않는다.

구현·수정 요청의 완료물은 실제 production path의 코드와 관련 검증이다. Audit, plan, ADR/CCR, workspace ledger, snapshot, release verdict만으로 구현 요청을 완료하지 않는다.

## 1. Routine patch

- [ ] 요청한 동작과 현재 구현이 일치한다.
- [ ] 순수 domain과 Django/provider/DB 경계를 보존한다.
- [ ] 변경 코드의 가장 작은 unit/property/API test 또는 static check가 통과한다.
- [ ] 관련되는 strict budget, 시간 전파, P90, null/unknown/unsupported 불변식을 지킨다.
- [ ] capability가 검증되지 않았으면 disabled/unsupported/PARTIAL로 남긴다.
- [ ] optional exactification/enrichment 실패는 기존 candidate-drop/fallback/PARTIAL/no-feasible 의미를 보존하며 자동 504가 아니다.

문서·내부 refactor·고립된 bug fix에는 mapping gold set, model card, canary, load test, Service E2E를 자동으로 요구하지 않는다.

반복 중에는 targeted test를 사용하고 diff가 안정된 뒤 affected aggregate suite를 한 번 실행한다. 관련 source·fixture·dependency가 그대로면 같은 task의 green evidence를 재사용한다. Routing과 Service test는 각 소유 runtime에서 실행하며 하나의 불완전한 환경에 두 tree를 함께 수집하지 않는다.

## 2. Affected subsystem evidence

- [ ] Provider 변경: 관련 normal/empty/error/timeout/429/drift fixture와 resilience
- [ ] Mapping 변경: 영향받는 gold/review case와 confidence gate
- [ ] Optimizer 변경: 관련 property/replay와 budget/time/Pareto invariant
- [ ] Data/model 변경: label 의미, leakage-safe split, metric/calibration, artifact integrity, rollback
- [ ] Private API 변경: relevant OpenAPI/generated Service consumer/partial/deadline/auth test
- [ ] Worker/DB 변경: relevant schema/migration/checkpoint/data-quality test

적용되지 않는 subsystem evidence는 필요하지 않다.

## 3. Integration or release

이 절은 사용자가 cross-workstream integration 또는 release/readiness를 요청했을 때만 적용한다.

- [ ] live contract lock parity와 producer-consumer compatibility
- [ ] 대표 replay/E2E 및 환경별 security/performance/resilience
- [ ] 출시 대상으로 선언한 provider/model의 production approval, quota, coverage, rollback
- [ ] known gap과 disabled capability가 사용자 응답에 정직하게 반영됨

`UNVERIFIED` evidence는 그 evidence에 의존하는 release/capability claim만 막는다.
`GO`/`NO_GO`는 명시적 deployment/release gate에서만 사용한다.
