# 07. 2번 작업 이어서 진행

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** 이전 Routing 세션 다음 작업

```text
$routing-intelligence-orchestrator

이전 Routing & Intelligence 작업을 이어서 진행해줘.

- WORKPLAN/STATUS/HANDOFF/context snapshot/branch diff를 읽는다.
- DONE을 재작성하지 말고 dependency가 해소된 PENDING/BLOCKED/UNVERIFIED를 선택한다.
- capability/data/mapping/model 상태를 확인한다.
- 독립 작업만 named custom subagents에 위임하고 primary thread가 dependency order로 fan-in한다.
- context hash가 다르면 중단하고 drift를 보고한다.
- 미검증 Provider·데이터 부족·coverage 부족을 완료로 표현하지 않는다.
- component/replay/semantic/performance 후 STATUS/HANDOFF를 갱신한다.

선택 task, dependency, evidence, capability/model 변화, gaps, 다음 최우선 task를 보고하라.
```
