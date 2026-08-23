# Workstream PRD — React Web App & Django Service Backend

## 1. 목적

Service Product 작업흐름은 사용자의 입력·계정·장소·검색 기록과 사용자 화면을 소유한다. Routing 알고리즘을 재구현하지 않고 `RoutingGateway`를 통해 private contract를 소비한다.

## 2. 입력과 출력

### 입력

- 장소·좌표
- 출발·도착 시각 조건
- taxi budget과 strict 여부
- max walk·transfer·taxi legs
- optimization profile·accessibility
- guest/session/user context

### 출력

- Public Route Search response
- 네 추천 카드와 Pareto 비교
- 지도 geometry와 leg timeline
- Bus Intelligence user-safe presentation
- warning·support·capability
- 검색 기록·즐겨찾기·설정·피드백

## 3. 범위

### Frontend

- 모바일 우선 React+TypeScript PWA
- Kakao Maps JavaScript SDK
- 장소 검색·현재 위치·지도 선택
- 예산·시간·제약 입력
- 검색 진행과 결과 state
- FASTEST/STABLE/EFFICIENT/TRANSIT_ONLY 카드
- route leg·map polyline·Bus details
- guest·login·history·favorite·preference
- privacy·data delete/export UI
- accessibility·responsive·offline shell

### Service Backend

- Django auth/session/CSRF
- Kakao Local proxy와 cache
- user/guest input validation·quota
- Routing Gateway와 generated client
- public projection·history snapshot
- saved place·favorite·feedback
- consent·privacy·delete/export
- capability·support status
- public error mapping·idempotency

## 4. 비범위

- 교통 Provider raw response 해석
- Provider retry/fallback orchestration
- Kakao Transit↔GBIS identity mapping
- Bus ETA·Seat Risk 추론
- candidate generation·cost·Pareto·ranking
- model registry
- Routing DB query

## 5. 아키텍처

```text
React Web App
  -> Public API Client (generated)
    -> Django Service Backend
      -> RoutingGateway Protocol
        -> Http / Stub / Replay / InProcess Adapter
```

### Frontend Feature Slice

```text
app-shell
place-search
route-search-form
route-search-state
route-recommendation-list
route-map
route-detail
bus-intelligence-panel
account
history
favorites
preferences
support-status
privacy
```

### Service App

```text
identity
consent
preferences
places
journeys
favorites
feedback
routing_client
operations
```

## 6. 기능 요구

### SP-FR-001 장소

- query 2자 이상, server validation
- Kakao Local 결과를 canonical PlaceRef로 변환
- 최근·저장 장소와 Provider 결과를 명시적으로 구분
- exact coordinate를 log에서 제외

### SP-FR-002 검색 생성

- `POST /api/v1/route-searches`
- idempotency·correlation
- guest token 또는 user ownership
- request limits
- Routing deadline 전달
- timeout/error를 표준 Problem Details로 변환

### SP-FR-003 결과 projection

보존:

- ranking·P50·P90·fare range
- legs·geometry
- provenance·confidence·coverage
- reason·warning

제거:

- raw payload
- plate
- internal DB IDs
- model URI·feature vector
- Provider credential·quota detail

### SP-FR-004 UI 상태

```text
IDLE
VALIDATING
SEARCHING
COMPLETE
PARTIAL
NO_FEASIBLE_ROUTE
PROVIDER_UNAVAILABLE
EXPIRED
```

`PARTIAL`은 실패 화면이 아니다.

### SP-FR-005 지도

- mode별 일관된 style token
- geometry가 없는 leg를 정상 road path처럼 직선으로 표시하지 않음
- transfer WALK 별도
- upstream stop에서 가까운/추천 정류장 함께 표시
- user location은 session state로만 보유

### SP-FR-006 결과 카드

- total P50·P90·arrival range
- taxi expected·upper·budget status
- saved time vs baseline
- walk·transfer·taxi leg count
- reliability
- top reasons·warnings
- data source·freshness

### SP-FR-007 Bus Panel

- user arrival at stop
- candidate vehicles
- ETA source/range
- no-seat/low-seat probability
- boardability proxy disclosure
- expected/P90 wait
- mapping/model/coverage를 사용자 친화적으로 표시

### SP-FR-008 계정

- guest first
- optional login
- secure cookie·CSRF
- history save opt-in
- saved places·favorites
- preferences version
- account deletion·data export

### SP-FR-009 Capability

- Routing capability를 public-safe하게 projection
- unsupported control을 disabled/hidden
- degraded reason 표시
- V2 realtime reroute false

## 7. 데이터

Service DB 원본은 `src/contracts/database/service-db.dbml`이다.

- exact coordinate·saved place는 encrypted at rest와 최소 접근
- `public_result`는 versioned snapshot
- user/guest ownership constraint
- delete/retention job
- Routing opaque IDs는 FK가 아님

## 8. Contract 규칙

- generated clients를 사용하고 hand-written duplicate DTO 금지
- unknown enum fallback
- P90<P50이면 response를 invalid로 처리·관측
- strict route인데 upper>budget이면 UI에서 숨기는 것으로 해결하지 않고 contract violation으로 처리
- reason/warning registry에 없는 code를 안전 generic message로 표시하되 telemetry

## 9. Security

- REST·Mobility·GBIS key Browser 노출 금지
- Kakao JS key domain 제한
- CSP·XSS output encoding
- CSRF·session cookie
- rate limit·guest abuse
- exact coordinate·email·token redaction
- owner authorization for search/history/favorite

## 10. 성능

- Service overhead P95 budget 약 500ms 목표
- generated client·connection pool
- public result cache와 idempotency
- Frontend route details lazy render
- 지도 geometry virtualization/decimation 필요 시 적용
- Web performance budget 별도 계측

## 11. 수용 기준

- Mock Routing으로 E2E 가능
- Real Routing response와 same client
- public API↔React type 교차 검증
- COMPLETE/PARTIAL/error/expired UI
- guest·user ownership
- search history privacy
- exact location log 없음
- accessibility 기본 검사
- P95 end-to-end gate에서 Service가 병목 아님
