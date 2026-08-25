# Routing Workstream Map

| 요청 | 관련 전문성 | 필요한 경우에만 추가 검증 |
|---|---|---|
| API adapter | Provider | touched resilience/schema/security |
| Kakao↔GBIS | Mapping | affected fixture/gold/confidence case |
| graph/candidates/Pareto | Optimization | affected property/replay; Provider/Bus only if consumed path changed |
| ETA/seat/wait | Bus + Data/ML | affected mapping/model fallback |
| legacy migration | Data/ML | affected schema/checkpoint/data quality |
| deadline/cost/auth | Security/Performance | focused counterexample; release load only when requested |
| private contract meaning | Contract Steward | affected producer/consumer and Integration QA |
| user UI/account | Service Harness | consumer contract |

The table routes expertise; it does not require agent delegation or a full dependency-chain run.
