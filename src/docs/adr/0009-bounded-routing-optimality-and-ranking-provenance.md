# ADR-0009: 제한된 Routing 최적성 및 실행 정책 provenance

- 상태: Accepted (bounded implementation scope)
- 날짜: 2026-08-24
- 결정자: Product owner, Contract Steward
- 구현 활성화 승인 필요: Service Product owner, Routing & Intelligence owner,
  architecture auditor, integration QA, Routing QA, Service QA,
  routing security/performance
- 관련 요구사항: FR-ROUTE-009, FR-OPT-003, FR-OPT-006, FR-OPT-007,
  FR-OPS-006, BR-009, NFR-PERF-001
- 관련 계약: `src/contracts/versions/platform-versions.json`,
  `src/contracts/openapi/routing-private.v1.yaml`,
  `_workspace/integration/CCR-008-minimum-arrival-semantics.md`

## Context

`FASTEST`는 strict-budget-feasible 후보 중 P50 도착시간이 가장 짧은 경로이고,
`PUBLIC_TRANSIT_ONLY`는 Taxi upper cost 합계가 0인 비교 기준이다. 이전
`rank-0.1.1` 구현은 epsilon Pareto 대표 집합이 이 두 exact anchor를 제거할 수
있었다. 현재 구현은 Provider가 반환한 유한 itinerary payload를 canonical graph로
구성하고, time-dependent leg-entry 비용, transfer feasibility, strict Taxi upper
budget, canonical deduplication을 적용한 뒤 두 anchor를 exact feasible pool에서
선택한다.

서로 다른 세 범위를 혼동하면 안 된다.

1. **Network-global universe**: 실제 교통망과 모든 Provider에 존재할 수 있는 모든
   경로다. 현재 시스템은 이 집합을 소진하거나 최적성을 증명하지 않는다.
2. **Finite admitted payload graph**: versioned Provider fallback/admission과
   strategy/exactification 정책이 한 요청에서 받아들인 immutable payload로 만든
   유한 canonical graph다.
3. **Exact evaluated feasible pool**: 위 graph에서 sound dominance를 거쳐 발견하고
   exact evaluation, constraints, deduplication을 통과한 후보 집합이다.

Provider envelope에는 실제 network source exhaustion이나 아직 보지 못한 경로의
admissible lower bound가 없다. 따라서 이 결정은 2와 3의 범위만 승인하며
network-global optimum 주장을 승인하지 않는다.

현재 graph/candidate/exactification hard cap은 비용, quota, tail latency 및
denial-of-wallet 안전 경계다. 구현은 cap이 결과의 인증을 방해하면 후보를 잘라
`COMPLETE`로 반환하지 않고 fail closed한다. 현행 wire에는 별도의 search
completeness 상태가 없다.

## Decision

1. `FASTEST`는 완전히 평가되고 constraint-feasible하며 deduplicate된 bounded pool의
   deterministic P50 argmin으로 정한다. `PUBLIC_TRANSIT_ONLY`는 같은 pool에서 모든
   Taxi leg의 upper cost 합계가 0인 부분집합의 동일 argmin으로 정한다.
2. Epsilon dominance는 표시용 Pareto/frontier 압축에만 사용한다. Exact anchor가
   epsilon representative가 아니어도 referential integrity를 위해 `routes`에
   유지하되, 실제 frontier member가 아니면 `paretoRouteIds`에 추가하지 않는다.
3. 이 보장은 immutable request와 admitted Provider payload, allowed pattern,
   constraint, exactification, graph-search 및 ranking policy 범위에 한정한다.
   Provider가 실제 network 전체를 소진했다거나 더 좋은 외부 경로가 없다는 뜻이
   아니다.
4. 새 결과의 ranking policy identifier는 `rank-0.2.0`이다. 유한 payload admission,
   bounded strategy generation, exactification, time-dependent graph search를 묶은
   combined strategy/search identifier는 `strategy-2.0.0`이다. 두 값은 immutable
   provenance이며 `rank-0.1.1`과 `strategy-1.0.0`은 historical behavior에 고정한다.
   기존 row, replay, cache, telemetry를 새 값으로 relabel하거나 backfill하지 않는다.
5. Candidate, exactification, graph-expansion, per-node-label, complete-path,
   Provider-call 및 deadline cap을 유지한다. Sound exhaustion/pruning proof 전에 cap이
   활성화되면 기존 capacity/deadline 경계를 통해 body 없이 fail closed한다. 이
   경우 `COMPLETE`, provisional exact anchor, Provider 장애 warning, 새 status 또는
   새 error/warning code를 만들지 않는다.
6. CCR-008 Finding A의 `transferCount`/`maxTransfers` 의미는 명시적으로 연기한다.
   이번 결정은 기존 정수의 의미를 변경하거나 historical 값을 정정하지 않는다.
7. CCR-008 Finding C의 additive completeness field/warning도 명시적으로 연기한다.
   현행 fail-closed 동작이 승인 범위이며 `PARTIAL`을 optimizer-certification 상태로
   확장하지 않는다.
8. OpenAPI, DBML, event, code registry, generated client에는 새 schema member가 없다.
   `rankingPolicyVersion`은 기존 opaque string을 사용하고, combined strategy/search
   ID는 기존 free-form private computation `cache.strategyPolicyVersion`에 기록한다.
   Service는 recommendation을 재계산하거나 이 private computation을 public으로
   노출하지 않는다.
9. 현재 Routing run persistence는 ranking policy만 보존한다. 전용 strategy/search
   persistence, shared-cache partition, durable telemetry field는 아직 없다. 따라서
   이번 승인은 source runtime, private computation, existing ranking persistence,
   deterministic replay 및 canonical-example coherence까지만 포함한다. Strategy ID의
   durable end-to-end provenance는 별도 additive governance 없이는 release evidence로
   주장하지 않는다.

## Alternatives Considered

1. **Network-global optimum으로 표시**: source exhaustion과 unseen lower bound가
   없으므로 거부한다.
2. **Epsilon representative를 exact anchor로 사용**: display compression과 exact
   recommendation을 혼동하므로 거부한다.
3. **Cap을 제거해 exhaustive search**: Provider quota, 비용, availability 및 6.5초
   deadline을 훼손하면서도 network exhaustion을 증명하지 못하므로 거부한다.
4. **이번 변경과 동시에 completeness wire를 추가**: consumer-first generated-client,
   registry, DB, public UX 변경이 준비되지 않았으므로 Finding C로 연기한다.
5. **유한 payload scope와 exact anchor를 새 immutable policy IDs로 승인**: 구현된
   보장을 정확히 표현하고 미구현 wire 의미를 섞지 않으므로 채택한다.

## Consequences

- Exact anchor가 epsilon 표시 집합과 독립적으로 정확해지고 Service는 Routing이
  반환한 ID를 그대로 projection한다.
- 같은 요청/Provider payload/policy snapshot의 replay는 deterministic해야 한다.
- 새 정책은 결과 membership과 recommendation을 바꿀 수 있지만 wire shape는
  바꾸지 않는다. Opaque version을 기준으로 historical 결과와 분리한다.
- `/v1/version`은 기존 schema에 따라 ranking ID를 보고한다. Strategy/search ID는
  optimize computation에만 존재하며 `/v1/version` 또는 public response에 새 field를
  임의로 추가하지 않는다.
- Process-local idempotency cache는 deployment restart 시 소멸한다. 새 policy를
  활성화할 때 process restart와 old-version response cache 비재사용/eviction이
  필수다. 향후 shared cache를 도입하면 두 policy ID를 partition key에 포함해야 한다.
- Ranking persistence는 새 ID를 보존할 수 있으나 strategy/search ID의 durable
  persistence와 telemetry는 미완료 release gate다.

## Security / Privacy / Cost

6.5초 hard deadline, 64 Provider-call cap, bounded graph caps, deterministic
admission과 load shedding을 유지한다. Policy identifiers에는 raw Provider payload,
exception, query, exact coordinate, secret 또는 user identity를 넣지 않는다. Cap
failure를 Provider 장애로 오표기하거나 더 많은 billable call로 숨기지 않는다.

## Migration and Rollback

Schema migration은 없다. 활성화 순서는 다음과 같다.

1. Runtime defaults, platform registry, private computation, `/v1/version` ranking,
   canonical examples와 producer/consumer assertions를 각각 `rank-0.2.0` 및
   `strategy-2.0.0`으로 맞춘다.
2. Exact-anchor/oracle, graph-cap fail-closed, strict budget, replay, producer-consumer
   및 public-safe projection tests를 통과한다.
3. 두 workstream approval 뒤 derived examples와 contract lock을 갱신하고 세 context
   snapshot parity를 확인한다.
4. 배포 process를 재시작하고 과거 정책 cache를 재사용하지 않는다. Historical
   persistence/replay/telemetry는 생성 당시 ID로 유지한다.

Rollback은 새 producer bundle을 끄고 이전 `rank-0.1.1`/
`strategy-1.0.0` bundle과 cache partition으로 복귀하는 것이다. 새 값으로 생성된
결과를 과거 값으로 재기록하지 않는다. Contract lock rollback은 양쪽 owner 승인,
canonical regeneration 및 context parity 뒤에만 수행한다.

## Verification

활성화 승인은 다음 evidence가 모두 있을 때만 성립한다.

- Exhaustive-small oracle과 adversarial epsilon case에서 exact `FASTEST`와 exact
  zero-Taxi-upper `PUBLIC_TRANSIT_ONLY`, referential integrity, honest
  `paretoRouteIds`가 확인된다.
- Multiple admitted itineraries, time-band reversal, transfer miss/next service,
  strict budget B/B+1, duplicate/cycle case가 deterministic replay를 통과한다.
- Candidate/exactification/graph label/expansion/complete-path/Provider-call cap과
  hard deadline이 모두 fail closed하며 provisional body/status/code를 만들지 않는다.
- `RankingPolicy`, `StrategyGenerationPolicy`, platform versions, `/v1/version`,
  optimize computation, canonical examples 및 relevant replay assertions가 새 ID로
  일치한다.
- Routing ranking persistence가 `rank-0.2.0`을 보존하고 historical rows를 relabel하지
  않는다. Strategy persistence/cache/telemetry 미완료가 release evidence에서
  명시적으로 제외된다.
- OpenAPI/example validation, producer/consumer tests, Service projection/redaction,
  contract lock, repository validation 및 세 context snapshot parity가 통과한다.

## Supersedes / Superseded By

기존 ADR을 대체하지 않는다. CCR-008 Finding B만 이 제한된 범위로 승인한다.
Finding A와 Finding C는 CCR-008에 deferred로 남는다.
