# Service Product Harness Execution Playbook

## 시작 범위

1. 현재 Service 구현, 적용되는 `AGENTS.md`, 영향받는 테스트를 먼저 본다.
2. API·공유 의미가 바뀔 때만 manifest/lock과 관련 contract·generated client를 추가로 본다.
3. 관계가 불명확하면 affected symbol/call path를 CodeGraph로 한 번 확인하고 바로 구현한다.
4. 가장 작은 relevant check를 선택한다. snapshot과 `_workspace` 기록은 선택 사항이다.

Continuation에서는 unchanged call-path findings와 green evidence를 재사용한다. 구현 요청을 audit, UX plan, workspace ledger, CCR/ADR 또는 release verdict로 대체하지 않는다.

## 작업 흐름

- Local fix: 직접 수정 → targeted test → diff/impact 보고.
- Vertical slice: UX state·fixture → Backend producer/Frontend consumer → affected data/privacy review → incremental QA.
- Shared boundary: 영향받는 producer/consumer와 contract를 먼저 확정하고 `shared-contract-governance`를 적용.
- Real Routing integration: live lock parity, private generated client, mock/replay/real response parity, public-safe projection.
- Release: 해당 환경의 security/accessibility/operations/rollback evidence를 추가.

Routing 기능이 없거나 미검증이면 canonical stub/replay와 explicit PARTIAL/unsupported로 계속할 수 있다. 새 field가 필요할 때는 관련 API/client/test만 영향 기반으로 바꾸며, 무관한 DBML·event·code registry를 강제하지 않는다.

Focused task는 primary가 직접 수행한다. 사용자가 위임을 요청했거나 진짜 독립 작업이 있을 때만 최대 한 implementer와 한 reviewer를 사용한다. 반복 중 targeted test 후 안정된 diff에 대해 affected aggregate suite를 한 번 실행한다.

## 완료 보고

변경 파일, 동작 결과, 실행한 checks, 실제 계약 영향, security/privacy 영향, known gap, rollback을 작업 규모에 맞게 기록한다. 일반 source 구현에는 `GO`/`NO_GO`를 붙이지 않는다.
