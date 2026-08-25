# Codex 전체 복붙 프롬프트 모음

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

각 프롬프트는 독립적으로 복사할 수 있다. `[ ]` placeholder를 실제 값으로 바꾼다.

## 00. 저장소 최초 점검

사용 시점: Codex에서 저장소를 처음 열었을 때

```text
저장소를 수정하지 말고 먼저 구조와 현재 상태를 점검해줘.

1. 루트 AGENTS.md와 현재 작업 디렉터리까지 적용되는 모든 하위 AGENTS.md를 읽어라.
2. .codex/config.toml, .codex/agents, .agents/skills 구조를 확인하라.
3. 다음을 실행하라.
   - python src/scripts/validate_repository.py
   - python src/scripts/verify_contract_lock.py
4. CONTEXT_MANIFEST, CONTRACT_LOCK, harness registry, shared PRD, Context Map, OpenAPI, DBML, code registry를 읽어라.
5. Service Product와 Routing & Intelligence의 소유 경계, 금지 의존성, contextVersion/contractVersion/aggregateSha256을 요약하라.
6. _workspace의 WORKPLAN, STATUS, HANDOFF를 읽고 DONE/PENDING/BLOCKED/UNVERIFIED를 정리하라.
7. 제품 코드·계약·문서를 아직 수정하지 마라.

최종 출력: 활성 instruction files, 검증 결과, 두 작업흐름 상태, 계약 상태, 위험/drift, 다음 추천 지시 3개.
```

## 01. 1번 Service Product 최초 구현

사용 시점: 개발자 1이 처음 구현을 시작할 때

```text
$service-product-orchestrator

Service Product 작업흐름의 초기 구현을 시작해줘. 1번 담당 범위만 구현한다.

- repository/contract 검증과 service-product context snapshot을 실행하라.
- AGENTS.md, shared PRD, Public/Private OpenAPI, Service DBML, Service workstream 문서를 읽어라.
- WORKPLAN.md를 실제 vertical slice로 작성하라.
- 필요한 custom subagents에 독립 작업을 위임하라: service-product-lead, service-ux-engineer, service-frontend-engineer, service-backend-engineer, service-data-engineer, service-security-engineer, service-qa-engineer.
- 먼저 canonical Stub/Replay RoutingGateway로 Frontend→Service→Mock Routing 흐름을 만든다.
- React Web/PWA, 장소검색, 조건, 대표 네 결과, 지도/상세, COMPLETE/PARTIAL/NO_FEASIBLE/ERROR 상태를 구현한다.
- Django Service에 인증/guest/place proxy/search/RoutingGateway/history/favorites/preferences/feedback을 구현한다.
- Service가 GBIS, Mobility, 모델, ranking을 직접 다루지 않게 한다.
- Public API/generated client/UI/DB migration contract test를 작성한다.
- 정확 위치·토큰·키 로그를 검증한다.
- 계약에 없는 필드는 임의 추가하지 말고 change request로 BLOCKED 처리한다.
- 테스트와 전체 validation 후 STATUS/HANDOFF를 갱신한다.

Routing 소유 경로는 수정하지 마라. 최종 보고: 변경 파일, 완료 requirements, tests, mock/real 상태, 계약 영향, 보안/privacy, blockers, 다음 지시.
```

## 02. 1번 작업 이어서 진행

사용 시점: 이전 Service 세션 다음 작업

```text
$service-product-orchestrator

이전 Service Product 작업을 이어서 진행해줘.

1. WORKPLAN/STATUS/HANDOFF, 최신 context snapshot, branch diff를 읽어라.
2. DONE을 재작성하지 말고 dependency가 해소된 PENDING/BLOCKED/UNVERIFIED부터 선택하라.
3. context hash가 다르면 구현을 중단하고 drift를 보고하라.
4. 독립 작업만 필요한 Service custom subagents에 위임하고 primary thread가 모두 기다린 뒤 통합하라.
5. Routing 미완료는 canonical Stub/Replay로 유지하고 실연동 완료라고 표현하지 마라.
6. component→contract→integration 순서로 검증하고 STATUS/HANDOFF를 갱신하라.
7. 관련 없는 파일은 수정하지 마라.

선택 task, dependency, 완료 evidence, 새 계약 요구, 다음 최우선 task를 보고하라.
```

## 03. 1번 특정 기능 추가

사용 시점: Service UI/API 기능 추가

```text
$service-product-orchestrator

Service Product에 다음 기능을 추가해줘.

기능: [기능명/사용자 요구]

- Service 소유 경로만 수정한다.
- 사용자 스토리, 상태 전이, Public API/DB/privacy 영향을 먼저 분석한다.
- Routing 의미나 ranking을 Service에서 바꾸지 않는다.
- 공통 계약이 필요하면 먼저 change request를 작성하고 구현을 멈춘다.
- 필요한 UX/Frontend/Backend/Data/Security/QA custom subagents만 위임한다.
- loading/empty/partial/error/unsupported/accessibility를 포함한다.
- unit/contract/E2E와 repository validation을 통과한다.
- WORKPLAN/STATUS/HANDOFF를 갱신한다.

최종 보고: 요구→구현 파일→tests→계약 영향→미해결.
```

## 04. 1번 버그 수정

사용 시점: React/Django Service 결함

```text
Service Product의 다음 버그를 수정해줘.

버그: [증상/재현/기대]

1. AGENTS.md와 계약을 읽는다.
2. service-qa-engineer 또는 service-ux-engineer에 재현과 소유 경로 파악을 위임한다.
3. 원인 확정 후 frontend/backend owner에게 최소 수정과 회귀 test를 위임한다.
4. Routing/contract 원인이면 cast·임시 필드·재계산으로 숨기지 말고 integration finding을 작성한다.
5. 테스트와 validation을 실행하고 STATUS에 원인/재발방지를 기록한다.

관련 없는 파일을 수정하지 마라. 실제 원인, 수정, 회귀 테스트, 계약 영향, 남은 위험을 보고하라.
```

## 05. 1번 단독 QA

사용 시점: 2번과 합치기 전 Service 검증

```text
$service-incremental-qa

Service Product 작업흐름을 검증해줘. 먼저 코드를 수정하지 말고 findings를 작성하라.

검증: Public OpenAPI↔Django, Django↔generated TS client, client↔React, null/unknown/unsupported, route 값 재계산 금지, auth/IDOR/CSRF/rate limit, 위치/secret 로그, Service DBML↔models/migrations, Stub/Replay, accessibility/responsive/PWA, unit/contract/E2E.

각 finding에 severity, 파일/심볼, 재현, requirement/contract, owner, retest를 기록하고 PASS/CONDITIONAL/FAIL/UNVERIFIED로 판정하라.
```

## 06. 2번 Routing & Intelligence 최초 구현

사용 시점: 개발자 2가 처음 구현을 시작할 때

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

## 07. 2번 작업 이어서 진행

사용 시점: 이전 Routing 세션 다음 작업

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

## 08. 외부 Provider 연동

사용 시점: 신규 API/응답 변경/키 검증

```text
$provider-adapter-delivery

다음 Provider capability를 검증하고 Adapter를 구현 또는 수정해줘.

Provider/Capability: [예: Kakao Mobility MULTI_DESTINATION]

- 공식 문서와 현재 key 실제 호출 가능성을 구분한다.
- 키 값을 출력/기록하지 않는다.
- DOCUMENTED→KEY_VERIFIED→PRODUCTION_APPROVED 상태를 각각 판정한다.
- endpoint allowlist, request/response schema, null/0, 좌표/시간/단위, timeout/retry/circuit/quota/cache/retention을 정의한다.
- 정상/빈결과/timeout/429/5xx/schema drift/stale fixture를 만든다.
- raw shape를 canonical domain에 누출하지 않는다.
- 미승인 기능이면 capability false와 fallback을 유지한다.
- tests와 capability matrix/STATUS/HANDOFF를 갱신한다.
```

## 09. Kakao↔GBIS 매핑

사용 시점: 노선/정류장/방향 매핑

```text
$transport-mapping-delivery

[대상 경로/노선]의 Provider transit 결과를 GBIS canonical route/stop/direction에 매핑하는 기능을 구현·검증해줘.

- 이름만으로 확정하지 않는다.
- 노선 유형, 승하차 정류장, 좌표, sequence, direction, 기종점, geometry를 evidence로 사용한다.
- gold fixture와 ambiguous/opposite/A-B branch/turning point 사례를 만든다.
- HIGH/MEDIUM/LOW threshold와 review queue를 구현한다.
- LOW는 Bus Intelligence 미적용이다.
- mapping version/evidence/validity/audit를 저장한다.
- coverage와 HIGH precision을 보고한다.
```

## 10. Bus Intelligence/ETA 개발

사용 시점: ETA/Seat/Boardability/Wait

```text
$bus-intelligence-delivery
$routing-data-mlops

Bus Intelligence의 다음 범위를 개발·검증해줘: [ETA/Seat Risk/Boardability/Expected Wait/전체].

- 기존 데이터 inventory와 label policy를 먼저 감사한다.
- 동일 vehicle trip과 target station/time 실제 미래관측만 label로 사용한다.
- 미래관측 없음은 NULL/unobserved다.
- ETA와 Seat model을 분리한다.
- time/trip grouped split, baseline, route/time/horizon slice, calibration/interval을 검증한다.
- train/serve feature parity, safe artifact, registry, shadow/canary/rollback을 구현한다.
- 일반버스와 좌석버스 정책을 분리한다.
- 결과가 expected/P90 bus wait와 route ranking에 실제 영향을 주는 replay를 제시한다.
- 데이터 부족은 ACTIVE로 과장하지 말고 SHADOW/UNVERIFIED로 남긴다.
```

## 11. 경로 최적화 알고리즘 개발

사용 시점: candidate/time/budget/Pareto

```text
$route-optimizer-delivery

다음 Routing 알고리즘 기능을 구현해줘: [기능].

- canonical request와 Provider/Bus Intelligence typed input만 사용한다.
- 허용 pattern과 후보 cap을 지킨다.
- 각 leg는 앞 leg 종료시각으로 재평가한다.
- taxi dispatch wait, transit wait, transfer buffer, Bus expected wait를 분리한다.
- strict mode는 taxi leg upper cost 합이 budget 이하만 허용한다.
- transfer feasibility, epsilon Pareto, duplicate removal, FASTEST/STABLE/EFFICIENT/PUBLIC_TRANSIT_ONLY를 검증한다.
- reason/warning/provenance/ranking version을 남긴다.
- property test와 deterministic replay를 추가한다.
- 6.5초 내부 budget을 측정한다.
```

## 12. 2번 단독 QA

사용 시점: Service와 합치기 전 Routing 검증

```text
$routing-incremental-qa

Routing & Intelligence만 통합 전 검증해줘. 먼저 findings만 작성한다.

Adapter schema/failure/cache/quota, mapping precision/direction, label/trip leakage, ETA/Seat/calibration, expected wait, candidate/time progression, transfer, strict budget, Pareto, Private OpenAPI, no identity/cross-DB, replay, P95, security를 검사하라.

finding마다 severity, 파일/심볼, fixture/replay, invariant, owner, retest를 기록하고 PASS/CONDITIONAL/FAIL/UNVERIFIED로 판정하라.
```

## 13. 공통 계약 변경안만 작성

사용 시점: 아직 구현 승인 전

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

## 14. 승인된 계약 변경 적용

사용 시점: 13번 승인 후

```text
$shared-contract-governance

승인된 변경안을 적용해줘.

승인된 change request: [경로/내용]

- 승인 범위를 재확인한다.
- PRD/acceptance, OpenAPI, DBML, events, code registry, examples, compatibility, traceability를 atomic하게 수정한다.
- generated clients를 src/generated에 재생성한다.
- producer/consumer tests와 migrations를 양쪽에 반영한다.
- contractVersion/contextVersion 정책을 적용한다.
- 두 담당자 승인 evidence가 있은 뒤에만 update_contract_lock.py --approved-change를 실행한다.
- 양쪽 snapshot과 parity를 검증한다.
- STATUS/HANDOFF/changelog를 갱신한다.
```

## 15. DB 스키마/Migration 변경

사용 시점: Service 또는 Routing DB 변경

```text
$shared-contract-governance

다음 DB 변경을 설계·적용해줘: [변경].

- 어느 bounded context 소유인지 먼저 확정한다.
- DBML/ERD/data ownership/data retention을 갱신한다.
- Django migration, backfill, index/lock/query impact, expand-contract 순서, rollback/forward-fix를 설계한다.
- 상대 DB foreign key/direct query를 만들지 않는다.
- API/event 영향이 있으면 같은 change set에 포함한다.
- migration tests와 staging rehearsal를 작성한다.
- 승인 없는 contract lock 갱신 금지.
```

## 16. Reason/Warning/Error 코드 변경

사용 시점: 사용자 설명/오류 코드 변경

```text
$shared-contract-governance

다음 Reason/Warning/Error code 변경을 제안 또는 적용해줘: [변경].

- reason, warning, error를 정확히 분류한다.
- 기존 의미와 중복/충돌을 검사한다.
- canonical registry, OpenAPI examples, domain producer, Service projection, UI localization/renderer, tests를 함께 맞춘다.
- consumer의 unknown-code fallback을 검증한다.
- 제거/의미변경이면 breaking/deprecation을 적용한다.
```

## 17. 두 작업흐름 Context 동기화

사용 시점: 따로 작업한 후 통합 전

```text
$shared-context-loader
$integration-coherence-qa

Service Product와 Routing & Intelligence의 context를 동기화해줘. 제품 코드는 수정하지 마라.

1. repository/lock을 검증한다.
2. 두 WORKPLAN/STATUS/HANDOFF와 branch diff를 읽는다.
3. 두 snapshot을 새로 생성하고 compare_context_snapshots.py를 실행한다.
4. contextVersion, contractVersion, aggregate hash, canonical file hashes, generated client version을 비교한다.
5. drift가 있으면 어느 branch가 어떤 canonical 파일을 변경했는지 분류한다.
6. 승인된 change인지 확인하고, 아니라면 lock 갱신/병합을 금지한다.
7. 통합 가능 여부와 필요한 선행 작업을 _workspace/integration에 기록한다.
```

## 18. 1번→2번 인수인계

사용 시점: Service 요구를 Routing에 전달

```text
Service Product의 현재 상태를 Routing & Intelligence에 인수인계할 수 있게 정리해줘. 제품 코드는 수정하지 마라.

- Service WORKPLAN/STATUS/diff/tests를 읽는다.
- Private Routing 계약에서 실제로 소비하는 필드·상태·error/warning을 목록화한다.
- Stub/Replay fixture와 UI 상태 matrix를 연결한다.
- Routing에 필요한 변경은 구현 요청이 아니라 contract/capability/fixture 요구로 작성한다.
- Service가 임시 가정한 부분을 UNVERIFIED로 표시한다.
- _workspace/service-product/HANDOFF.md를 갱신한다.
```

## 19. 2번→1번 인수인계

사용 시점: 실제 Routing을 Service에 연결 전

```text
Routing & Intelligence 결과를 Service Product에 인수인계할 수 있게 정리해줘. 제품 코드는 수정하지 마라.

- Routing WORKPLAN/STATUS/diff/replay/capability/model state를 읽는다.
- Private API 구현 상태와 canonical examples parity를 작성한다.
- COMPLETE/PARTIAL/no-route/error, nullable recommendation, warnings, freshness, model/mapping coverage를 명시한다.
- 실제 Provider 검증 여부와 fixture-only 상태를 구분한다.
- 생성 client와 integration prerequisites를 목록화한다.
- _workspace/routing-intelligence/HANDOFF.md를 갱신한다.
```

## 20. 1번·2번 최초 통합

사용 시점: 두 작업흐름을 처음 실제 연결

```text
$integration-coherence-qa

Service Product와 Routing & Intelligence를 처음 통합해줘.

- 두 HANDOFF와 context snapshot을 읽고 parity가 아니면 중단한다.
- integration WORKPLAN을 작성하고 contract-steward, architecture-auditor, integration-qa 및 필요한 양쪽 QA에 독립 검증을 위임한다.
- Service HttpRoutingGateway를 실제 Private API에 연결한다.
- service JWT, deadline, idempotency, correlation, timeout을 검증한다.
- canonical mock/replay와 real response parity를 비교한다.
- Public projection이 내부 raw/debug/user-identity 경계를 지키는지 확인한다.
- COMPLETE/PARTIAL/NO_FEASIBLE/503/504를 E2E로 검증한다.
- DB ownership, no cross-query, no identity in Routing을 확인한다.
- R1~R4 smoke/replay와 P95를 실행한다.
- findings를 owner에게 고치게 한 뒤 최종 PASS/FAIL/UNVERIFIED를 작성한다.
```

## 21. 이후 반복 통합

사용 시점: 기능 slice를 주기적으로 합칠 때

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

## 22. PR/브랜치 병합 준비

사용 시점: 실제 Git 병합 직전

```text
$integration-coherence-qa

다음 브랜치/PR이 병합 가능한지 검토해줘: [브랜치/PR]. 먼저 수정하지 마라.

- 소유 경로 위반
- unapproved shared changes
- contract lock/context parity
- generated client drift
- DB migration/rollback
- producer/consumer tests
- deterministic replay
- strict budget/time invariants
- security/privacy
- P95/quota/cost
- WORKPLAN/HANDOFF completeness
- unresolved FAIL/UNVERIFIED

판정: READY, READY_WITH_ACCEPTED_RISK, NOT_READY. 필요한 선행 commit과 병합 순서를 제시하라.
```

## 23. 통합 충돌 해결

사용 시점: 두 작업흐름이 다르게 수정했을 때

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

## 24. 보안·개인정보 리뷰

사용 시점: 큰 기능/통합/릴리스 전

```text
$platform-release-gate

[범위]의 보안·개인정보 리뷰를 수행해줘. 먼저 findings만 작성한다.

검증: root/nested AGENTS 경계, auth/IDOR/CSRF/CORS/CSP, service-to-service auth, SSRF/egress allowlist, API key, GCE edge/rate/Denial-of-Wallet, exact location/logs/retention/deletion, DB/GCS/Redis encryption, model artifact/hash/pickle, mapping/data poisoning, dependency/container/IaC/SBOM, admin/audit/rollback.

각 finding에 severity, exploit/impact, evidence, owner, fix, retest를 기록하고 release blocker를 명시한다.
```

## 25. 성능·SLO 최적화

사용 시점: P95 7초/비용 문제

```text
$routing-security-performance

[시나리오]의 성능·신뢰성을 측정하고 P95 7초 목표를 맞춰줘.

- cold/warm, Provider 지연, cache hit/miss, candidate dense, concurrent, identical burst, matrix unavailable를 분리한다.
- trace로 validation/transit/taxi/GBIS/model/optimizer/serialization을 측정한다.
- Provider calls, candidate count, DB/Redis, CPU/memory, cost/search를 기록한다.
- 정확성/strict budget/partial semantics를 희생하지 않는다.
- optional enrichment/candidate cap/cache/single-flight/deadline/circuit 조정안을 제시한다.
- before/after P50/P95/P99와 regression tests를 보고한다.
```

## 26. 기존 3주 데이터 감사

사용 시점: DB/통계를 제공받았을 때

```text
$routing-data-mlops

제공된 기존 BusCrowdRisk 데이터/DB를 수정하지 말고 감사해줘.

- schema/hash/기간/행/노선/방향/차량/trip/time slice
- arrival/location/seat missing, duplicate, out-of-order, station sequence
- target observation coverage와 미래관측 없음 처리
- capacity evidence
- weather/traffic/context coverage
- current model diagnostics/calibration/artifact safety
- leakage 위험

결과를 데이터 inventory, quality report, migration reconciliation, model feasibility, 추가 수집 우선순위로 작성한다. 수치를 추측하지 않는다.
```

## 27. 모델 재학습·승격

사용 시점: 데이터 감사 후

```text
$bus-intelligence-delivery
$routing-data-mlops

[ETA/Seat] 모델을 재학습하고 승격 후보를 평가해줘.

- 승인된 snapshot/feature/target version을 고정한다.
- time/trip grouped split과 baselines를 만든다.
- route/time/horizon slices, calibration/interval, coverage, latency를 평가한다.
- train/serve parity와 artifact metadata/hash/model card를 생성한다.
- 기존 ACTIVE 대비 replay/ranking 영향과 regression을 비교한다.
- 기준 미달이면 REGISTERED/SHADOW에 두고 ACTIVE로 승격하지 않는다.
- 승격 시 canary/rollback/monitoring을 준비한다.
```

## 28. Provider 장애 대응

사용 시점: 실제 장애/쿼터 소진

```text
$provider-adapter-delivery
$integration-coherence-qa

[Provider/Capability] 장애를 진단하고 안전하게 대응해줘.

- auth/429/quota/timeout/5xx/schema/network를 분류한다.
- 키 값을 출력하지 않는다.
- circuit/cache/fallback/partial 영향을 확인한다.
- strict budget 또는 mapping/seat 정확성이 검증 불가하면 해당 후보/기능을 차단한다.
- 사용자 warning/status와 운영 alert/runbook을 갱신한다.
- 정상화 후 canary/probe와 regression fixture를 추가한다.
- incident timeline, 영향, 임시조치, 근본원인, 재발방지를 작성한다.
```

## 29. 판매 가능한 Release Gate

사용 시점: Closed Beta/GA 직전

```text
$platform-release-gate
$integration-coherence-qa

[릴리스 버전]을 판매/운영 가능한 release gate로 검증해줘.

- 기능/대표 R1~R4/field test
- contract/context/generated clients
- strict budget, ETA/seat coverage/calibration
- Provider production approval/terms/quota/cost
- P95/availability/partial/fallback
- auth/privacy/location/deletion
- threat model/security scans/SBOM
- GCE HA/backup/restore/rollback/observability/runbooks
- admin/model/mapping audit
- unresolved risks/TBD

PASS, CONDITIONAL, FAIL로 판정하고 blocking items, accepted risks(owner/expiry), rollback, post-release monitoring을 작성한다.
```

## 30. 배포·모델·계약 롤백

사용 시점: 통합/배포 후 문제

```text
문제를 더 확산시키지 말고 다음 rollback을 계획·실행해줘: [서비스/모델/계약/DB].

- 현재 영향과 last known good version을 확인한다.
- 데이터 손실 가능성과 backward compatibility를 평가한다.
- application/image/feature flag/model registry/cache/migration 각각의 rollback 가능성을 구분한다.
- destructive DB rollback 대신 forward fix가 안전한지 판단한다.
- contract consumer/producer overlap을 확인한다.
- smoke/replay/security와 context/lock을 재검증한다.
- incident와 재진입 조건을 기록한다.
```

## 31. 전체 프로젝트 현황 감사

사용 시점: 오랜 작업 후 현황 확인

```text
저장소를 수정하지 말고 전체 프로젝트 현황을 감사해줘.

- AGENTS/config/agents/skills/prompts/ledgers
- repository/lock/context parity
- Service/Routing 구현률과 tests
- OpenAPI/DBML/generated drift
- Provider capability
- data/mapping/model coverage
- R1~R4/replay
- performance/security/GCE/release
- TODO/BLOCKED/UNVERIFIED/dead code

PRD requirement별 DONE/PARTIAL/NOT_STARTED/UNVERIFIED 표와 두 담당자별 다음 작업, 통합 순서, 가장 큰 위험 10개를 제시하라. 코드 수정 금지.
```

## 32. 새 Codex 세션에서 이어하기

사용 시점: 대화 컨텍스트가 끊겼을 때

```text
이 저장소의 이전 대화를 기억한다고 가정하지 말고 파일을 기준으로 작업을 재개해줘.

작업흐름: [service-product / routing-intelligence / integration]
목표: [이번 세션 목표]

1. 루트/하위 AGENTS.md를 읽는다.
2. repository/lock을 검증한다.
3. 해당 WORKPLAN/STATUS/HANDOFF, context snapshot, branch diff를 읽는다.
4. shared PRD와 관련 계약만 로드한다.
5. DONE을 재작성하지 않고 다음 실행 가능한 task를 선택한다.
6. 필요한 custom subagents만 위임한다.
7. 완료 후 ledgers와 validation을 갱신한다.

먼저 재개 계획과 가정/차단을 짧게 보고한 뒤 실행하라.
```

## 33. V2 실시간 재추천 시작

사용 시점: Release 1 이후

```text
$shared-contract-governance

V2 실시간 재추천 기능의 contract-first 설계를 시작해줘. 즉시 구현하지 말고 proposal부터 작성한다.

요구: current journey state, current location, completed legs, actual taxi spend, remaining budget, delays/boarding failure, reroute result, route-switch hysteresis, push/notification, location consent/background handling.

- Service/Routing 책임을 분리한다.
- identity는 Routing에 보내지 않는다.
- 위치 frequency/retention/privacy/battery를 정의한다.
- contract/events/DBML/state machine/security/SLO/cost 영향을 작성한다.
- 5분 이득 또는 기존 경로 실패 위험 등 switching policy를 버전화한다.
- Release 1 API compatibility와 migration을 제안한다.
```

## 34. 두 사람 Branch/Worktree 준비

사용 시점: 실제 동시 개발 전

```text
현재 Git 상태를 확인하고 두 작업흐름을 안전하게 병렬 개발할 branch/worktree 계획을 작성해줘. 명령은 제시하되 승인 없이 destructive command를 실행하지 마라.

권장 branch: workstream/service-product, workstream/routing-intelligence, integration/current, contract/<name>.

- 기준 commit과 clean status 확인
- worktree 경로/명령
- 공통 계약 commit 반영 순서
- CODEOWNERS/PR review
- generated client 처리
- context snapshot과 handoff
- 최초/반복 integration branch 전략
- conflict/rollback

제품 파일을 수정하지 마라.
```

## 35. Codex 하네스만 수정

사용 시점: AGENTS/skills/agents/prompts 변경

```text
$harness-evolution

제품 코드와 비즈니스 계약을 건드리지 않고 Codex 하네스만 다음과 같이 수정해줘: [변경].

- 변경 전 보호 대상 application/OpenAPI/DBML/PRD/algorithm 파일 SHA-256을 고정한다.
- 허용 범위: AGENTS.md, .codex, .agents, Codex/harness docs, prompt library, _workspace templates, harness validation scripts, context-only metadata.
- custom agent/skill/prompt/registry/eval/validation 일관성을 유지한다.
- active Claude-only controls를 만들지 않는다.
- repository/trigger/context 검증을 실행한다.
- 변경 후 보호 대상 hash를 비교해 preservation report를 작성한다.
- product contractVersion은 비즈니스 의미가 바뀌지 않으면 변경하지 않는다.
```
