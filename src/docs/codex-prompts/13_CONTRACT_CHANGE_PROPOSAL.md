# 13. 공통 계약 변경안만 작성

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** 아직 구현 승인 전

```text
$shared-contract-governance

공통 계약 변경안을 작성하되 아직 제품 코드와 canonical 계약을 수정하지 마라.

변경 요구: [필드/행동/DB/코드]

- 현재 PRD/OpenAPI/DBML/events/codes/examples/consumers/producers를 분석한다.
- 제품 의미와 동기화 이유를 작성한다.
- additive optional 가능성, breaking 여부, version, migration/backfill/deprecation을 분석한다.
- Service/Routing/Frontend/generated client/test 영향표를 만든다.
- proposal을 _workspace/integration에 기록한다.
- 승인 전 lock을 갱신하지 않는다.

최종 출력은 승인/수정/거절을 결정할 수 있는 change set으로 작성하라.
```
