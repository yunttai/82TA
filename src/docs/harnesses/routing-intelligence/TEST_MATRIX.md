# Routing & Intelligence Test Matrix

| 영역 | 생성물 | 대조 대상 |
|---|---|---|
| Adapter | canonical output | Provider fixture/schema |
| Mapping | route/stop/direction/score | gold set |
| Domain | candidates/cost/rank | invariants/expected replay |
| Bus ETA | distribution | future observations |
| Seat Risk | calibrated probability | target stop labels |
| Wait | expected/P90 | candidate vehicle outcomes/proxy |
| API | Optimize response | private OpenAPI/Service client |
| DB | migration/model | DBML/ownership |
| Security | request/log/artifact | threat controls |

## Core Cases

- current transit complete
- matrix unsupported single fallback
- GBIS seat missing
- official ETA absent model fallback
- stale bus data
- mapping LOW
- general bus crowded
- upstream candidate wins/loses
- Taxi Bridge wins/loses
- strict budget edge
- transfer margin negative/low
- deadline optional enrichment cut
- provider 429/circuit open
- Redis unavailable
- model artifact rollback

## Properties

- lower budget never introduces more expensive feasible candidate
- no dominated route in Pareto
- p90>=p50
- chronological legs
- no pre-arrival vehicle
- no user identity persisted
