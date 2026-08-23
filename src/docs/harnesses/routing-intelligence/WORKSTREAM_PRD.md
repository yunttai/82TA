# Workstream PRD — Routing & Intelligence

## 1. 목적

외부 대중교통·택시·경기버스·날씨·도로 데이터를 알고리즘 입력으로 통합하고, 사용자 identity 없이 경로 후보·ETA·좌석 위험·실질 대기·예산·환승 위험을 계산한다.

## 2. 입력

Private OptimizeRouteRequest와 deadline, correlation, idempotency.

## 3. 출력

- canonical route candidates
- four recommendation route IDs
- Pareto frontier
- provider status
- model/mapping/ranking versions
- reason/warning/provenance
- computation counts·cache·latency

## 4. 모듈

| 모듈 | 책임 |
|---|---|
| provider_registry | capability·priority·health |
| transit_provider | baseline transit |
| walk_provider | access/transfer/egress walk |
| taxi_provider | exact/matrix/future driving time·fare |
| bus_realtime_provider | GBIS arrival/location/seat |
| weather/traffic | KMA·GITS cached context |
| entity_mapping | Provider route/stop↔canonical GBIS |
| candidate_generation | pattern 조합·upper bound |
| bus_intelligence | ETA·seat·expected wait |
| transfer_evaluation | P50/P90 margin·failure delay |
| cost_model | total P50/P90/fare/risk |
| pareto/ranking | four recommendations |
| explanation | reason·warning |
| model_runtime | approved artifact |
| data_quality | freshness·coverage·drift |

## 5. 금지

- user account/profile persistence
- email/name/phone/social ID request
- Service DB query
- Frontend-specific response copy
- Provider raw field in domain
- request-supplied model artifact path
- missing label negative conversion

## 6. 기능 요구

### RI-FR-001 Provider

- Adapter protocol
- envelope·schema validation
- timeout·bounded retry·breaker·cache
- capability states
- raw storage policy
- deterministic fixtures

### RI-FR-002 Baseline Routing

- current transit baseline
- taxi-only
- access/egress/both-end taxi
- exact walk
- time propagation by leg entry time
- strict budget

### RI-FR-003 Mapping

- route name normalization
- boarding/alighting stop proximity
- sequence·direction·origin/destination
- geometry consistency
- mapping score·version·validity
- HIGH automatic, MEDIUM review/limited, LOW no enrichment

### RI-FR-004 Bus Intelligence

- user arrival 이후 candidates
- official ETA priority
- position/history ETA fallback
- target stop no-seat·low-seat
- boardability proxy disclosure
- multi-vehicle expected/P90 wait
- seat/general bus policy
- freshness·coverage·confidence

### RI-FR-005 Candidate Optimization

- bounded access/egress hubs
- matrix coarse pruning
- exact enrichment top candidates
- upstream stop
- Taxi Bridge
- transfer feasibility
- epsilon Pareto
- FASTEST/STABLE/EFFICIENT/TRANSIT_ONLY

### RI-FR-006 Data & Model Ops

- checkpoint collector
- quality gate
- legacy migration
- trip identity
- feature/label dataset version
- model registry·calibration·shadow·canary·rollback
- replay bundle

## 7. 성능

- Routing hard deadline <=6.5s
- provider calls parallel and bounded
- model batch inference
- candidate caps from algorithm spec
- optional enrichment skipped before deadline
- PARTIAL minimum route

## 8. 정확성

- strict cost upper
- P90>=P50
- time monotonic
- route/direction mapping precision
- data source·freshness
- calibration
- deterministic replay

## 9. 보안

- service JWT
- private ingress
- Provider URL allowlist
- secret manager
- raw response validation
- tokenized plate
- safe artifact format/hash
- cost abuse and quota

## 10. 수용

- Provider raw JSON 없는 domain test
- representative route fixtures
- mapping gold set
- Bus enrichment ranking reversal
- model fallback/rollback
- 6.5s deadline partial
- private response passes OpenAPI
