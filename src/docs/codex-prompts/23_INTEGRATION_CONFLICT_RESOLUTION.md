# 23. 통합 충돌 해결

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** 두 작업흐름이 다르게 수정했을 때

```text
$shared-contract-governance
$integration-coherence-qa

다음 통합 충돌을 해결할 계획을 작성하고 승인된 범위만 수정해줘: [충돌].

- product semantic, contract, generated artifact, implementation, DB migration, docs, workspace conflict로 분류한다.
- canonical source와 ownership을 기준으로 승자를 임의 결정하지 말고 근거를 제시한다.
- 양쪽 변경 의도와 tests를 보존한다.
- breaking이면 ADR/version/migration을 적용한다.
- generated 파일은 원본 계약에서 재생성한다.
- resolution 후 snapshots/lock/contracts/E2E를 검증한다.
```
