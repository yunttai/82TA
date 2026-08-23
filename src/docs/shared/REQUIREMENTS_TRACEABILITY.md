# Requirements Traceability

## 1. 목적

공통 PRD 요구사항이 API·DB·구현 소유권·테스트·릴리스 게이트까지 연결되는지 추적한다. 이 문서는 사람이 읽는 색인이고, 기계 판독 원본은 `src/contracts/traceability/requirements-traceability.yaml`이다.

## 2. 추적 규칙

각 요구사항은 다음 항목을 가져야 한다.

- `owner`: `service-product`, `routing-intelligence`, `joint`
- `contracts`: OpenAPI·DBML·code registry·event 경로
- `implementationPaths`: 실제 구현이 위치할 `src/` 경로
- `tests`: unit·contract·integration·E2E·replay·field test ID
- `releaseGate`: 출시 전 통과 조건
- `evidence`: 완료 시 생성해야 할 결과물

공통 요구사항의 의미가 바뀌면 PRD만 수정하지 않는다. traceability, 관련 계약, 예제, 테스트, changelog, contract lock을 함께 갱신한다.

## 3. 핵심 추적표

| 요구사항 | 소유 | 계약 | 구현 | 검증 |
|---|---|---|---|---|
| FR-PLACE-001 | Service | Public OpenAPI | `src/services/service-api`, `src/apps/web` | CT-SVC-PLACE-001, E2E-SEARCH-001 |
| FR-ROUTE-001~010 | Routing | Private OpenAPI, canonical schema | `src/packages/routing-domain` | UT-ROUTE-*, PROP-ROUTE-*, REPLAY-R1~R4 |
| FR-BUS-001~010 | Routing | Routing DBML, BusLegIntelligence | `src/packages/bus-intelligence-core` | MAP-GOLD-*, MODEL-SEAT-*, MODEL-ETA-* |
| FR-OPT-001~008 | Routing | RouteCandidate, code registry | `src/packages/routing-domain` | PROP-BUDGET-001, PROP-PARETO-001 |
| FR-UI-001~009 | Service | Public OpenAPI, code registry | `src/apps/web`, public projection | CT-UI-*, A11Y-*, E2E-* |
| FR-IAM-001~007 | Service | Service DBML, Public OpenAPI | `src/services/service-api` | SEC-IAM-*, DATA-DELETE-* |
| FR-OPS-001~006 | Joint/Routing | health/version/capability, events | `src/services`, `src/workers`, `src/infra` | RES-*, PERF-*, DR-* |

## 4. 완료 판정

구현 PR은 관련 요구사항 ID와 테스트 ID를 기록한다. 요구사항에 `releaseGate`와 evidence가 없으면 `DONE`으로 전환하지 않는다. QA는 구현 존재 여부가 아니라 **PRD → 계약 → 생산자 → 소비자 → 저장소 → 테스트**의 연결을 교차 검증한다.
