# Service Product Definition of Done

기능은 다음을 모두 만족해야 완료다.

## Contract

- [ ] 공통 context/contract lock 검증
- [ ] Public OpenAPI와 generated client 일치
- [ ] Routing client는 private OpenAPI에서 생성
- [ ] new field/code는 registry·examples·compatibility 반영

## Code

- [ ] `src/apps/web` 또는 `src/services/service-api` 아래
- [ ] TypeScript strict·Python type/lint 기준
- [ ] secret·exact location·plate log 없음
- [ ] service boundary 위반 없음

## Test

- [ ] unit
- [ ] API consumer contract
- [ ] response↔hook type 교차 검증
- [ ] state transition·route link 검증
- [ ] auth/ownership/privacy
- [ ] COMPLETE/PARTIAL/error fixture
- [ ] accessibility·responsive 기본

## Operations

- [ ] structured log·metric·trace
- [ ] feature flag·rollback
- [ ] migration expand/contract
- [ ] support/runbook 영향 반영

## Acceptance

- [ ] PRD 요구 ID와 evidence
- [ ] user-facing text가 probability·fare·ETA를 과장하지 않음
- [ ] Routing 계산값을 Service에서 재계산하지 않음
- [ ] QA와 contract steward 승인
