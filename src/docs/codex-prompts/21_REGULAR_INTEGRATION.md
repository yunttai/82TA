# 21. 이후 반복 통합

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** 기능 slice를 주기적으로 합칠 때

```text
$integration-coherence-qa

[기능/commit/PR]의 Service와 Routing 변경을 반복 통합해줘.

- 지난 통합 baseline과 이번 diff를 비교한다.
- context/contract/generation parity를 먼저 확인한다.
- 변경된 경계만 집중 검증하되 필수 invariants는 전체 재실행한다.
- producer/consumer, DB, codes, replay, partial, security, performance 영향을 검사한다.
- mock와 real을 비교한다.
- integration STATUS와 양쪽 HANDOFF를 갱신한다.
- merge 가능 여부와 남은 accepted risk를 보고한다.
```
