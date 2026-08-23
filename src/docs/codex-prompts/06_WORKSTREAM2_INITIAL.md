# 06. 2번 Routing & Intelligence 최초 구현

**사용 시점:** 개발자 2가 처음 구현을 시작할 때

```text
$routing-intelligence-orchestrator

Routing & Intelligence 초기 구현을 시작해줘. 2번 범위만 구현한다.

- validation과 routing context snapshot을 실행한다.
- AGENTS, shared PRD, Private OpenAPI, Routing DBML, algorithm/model/provider 문서를 읽는다.
- 기존 BusCrowdRisk 자산과 약 3주 데이터의 실제 통계가 없으면 꾸미지 말고 inventory task로 둔다.
- WORKPLAN에 dependency graph와 latency budget을 기록한다.
- 필요한 custom subagents에 위임한다: routing-technical-lead, provider-integration-engineer, transport-mapping-engineer, route-optimization-engineer, bus-intelligence-engineer, routing-data-ml-engineer, routing-security-performance-engineer, routing-qa-engineer.
- fixture/Adapter→canonical→mapping→Bus Intelligence→optimizer→Private API 순으로 통합한다.
- 미검증 Kakao Transit/Walk/Multi-destination은 capability false/fixture로 둔다.
- ETA와 Seat를 분리하고 미래관측 없음은 NULL/unobserved다.
- candidate, time-dependent legs, transfer, strict taxi upper budget, Pareto, 네 대표 결과를 구현한다.
- R1~R4 replay와 Provider failure fixture를 만든다.
- 6.5초 내부 deadline과 후보 cap/partial을 검증한다.
- tests/replay/performance/security/validation 후 STATUS/HANDOFF를 갱신한다.

Service 소유 경로와 사용자 DB를 수정하지 마라. capability 실제 상태, 알고리즘/모델, tests, performance, contract/data gaps를 보고하라.
```
