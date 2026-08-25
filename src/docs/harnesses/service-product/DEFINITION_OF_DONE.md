# Service Product — proportionate Definition of Done

모든 항목을 모든 변경에 강제하지 않는다. 현재 diff와 사용자 요청에 적용되는 단계만 사용하고, 해당하지 않는 항목은 생략하거나 이유를 짧게 남긴다.

구현 요청은 실제 Web/Service production path의 변경과 관련 검증으로 완료한다. Audit, plan, workspace ledger, contract proposal, release verdict만으로 완료하지 않는다.

## 1. Routine patch

- [ ] 요청한 동작과 실제 변경이 일치한다.
- [ ] 적용되는 Service/Routing 경계를 위반하지 않는다.
- [ ] 변경 코드의 가장 작은 unit/component/API test, lint 또는 build가 통과한다.
- [ ] secret, 정확한 위치, object ownership 등 변경과 관련된 안전 조건을 지킨다.
- [ ] API 값의 의미를 UI나 Service에서 재계산·왜곡하지 않는다.

문구·스타일·내부 refactor처럼 계약에 영향이 없는 변경에는 contract lock, migration, trace, feature flag, 전체 E2E, contract steward 승인을 요구하지 않는다.

반복 중 targeted test를 사용하고 diff가 안정된 뒤 affected aggregate suite를 한 번 실행한다. 관련 source·fixture·dependency가 그대로면 같은 task의 green evidence를 재사용한다.

## 2. Boundary, data, or security change

해당되는 항목만 추가한다.

- [ ] API 변경: 관련 OpenAPI/example/generated client/producer-consumer test
- [ ] DB 변경: 관련 model/migration/ownership/data lifecycle test
- [ ] auth/privacy 변경: object authorization, CSRF/session/log redaction 등 위험 기반 test
- [ ] 상태 의미 변경: COMPLETE/PARTIAL/error/unknown fixture와 UI projection
- [ ] backward compatibility와 rollback 또는 migration 설명

DBML, event, code registry는 실제 영향이 있을 때만 갱신한다.

## 3. Integration or release

사용자가 cross-workstream integration 또는 release/readiness를 요청했을 때만 이 절을 적용한다.

- [ ] live contract lock parity와 생성 client 정합성
- [ ] 대표 mock/replay/real boundary test
- [ ] 환경별 security, observability, rollback evidence
- [ ] 릴리스에서 주장하는 capability만 provider/model/performance evidence로 검증

`UNVERIFIED` optional capability는 disabled/unsupported/PARTIAL이면 일반 source merge를 막지 않는다.
`GO`/`NO_GO`는 명시적 deployment/release gate에서만 사용한다.
