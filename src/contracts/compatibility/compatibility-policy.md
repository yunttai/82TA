# Contract Compatibility Policy

## Major Change

- required field 삭제·이름 변경
- field 의미·단위 변경
- enum 값의 기존 의미 변경
- endpoint 제거·method 변경
- null 가능성을 제거해 기존 응답이 invalid가 됨

major URL 또는 compatibility adapter가 필요하다.

## Compatible Minor Change

- optional field 추가
- optional endpoint 추가
- reason/warning code 추가
- unknown enum 처리를 전제로 한 enum 추가

## 배포 순서

1. Producer가 optional field와 old behavior를 함께 제공
2. Consumer가 새 generated client로 갱신
3. Feature flag로 사용
4. 사용률·오류 telemetry 확인
5. deprecation 공지와 기간
6. old field 제거는 major 또는 합의된 migration window

## Gate

- OpenAPI diff
- generated client diff
- producer contract test
- consumer contract test
- example fixture validation
- DB migration compatibility
- context/contract lock update
- 양쪽 contract guardian 승인

## 1.1.0 compatibility decision

- 분류: backward-compatible minor.
- `POST /api/v1/route-searches`의 `422`와 `504`는 이미 구현된 canonical
  Problem 응답을 문서화한 additive response-set correction이다. Private
  `401 SERVICE_AUTH_REQUIRED`는 계속 Public-safe
  `503 TRANSIT_PROVIDER_UNAVAILABLE`로 축약한다.
- 추가된 Public endpoint, optional request/response field, response header, error code는 기존 1.0 consumer를 invalid하게 만들지 않는다.
- 기존 `DELETE /api/v1/me/data`는 유지하고 새 deletion-job endpoint의 compatibility alias로 deprecate한다.
- preference `If-Match`는 1.1 first-party client에 필수인 운영 정책이지만 OpenAPI에서는 1.0 migration window를 위해 optional이다. 미제공 요청 허용은 telemetry 후 제거하며 제거 시 major 또는 별도 versioned endpoint가 필요하다.
- Private `avoidHighBusSeatRisk`와 `busIntelligenceCoverage`는 optional이다. 구 Routing producer/consumer는 각각 값을 무시하거나 coverage를 `UNKNOWN`으로 projection할 수 있다.
- Private request `contractVersion: "1.0"`은 1.x wire compatibility family로 유지한다. OpenAPI metadata와 repository contract version은 `1.1.0`이다.
- Routing `/v1/version.contractVersion`은 그 repository/OpenAPI metadata를
  보고한다. optimize body의 `"1.0"`과 같은 값으로 해석하지 않는다.
- `rankingPolicyVersion`은 opaque provenance다. 1.1.0 당시 실행 정책의 canonical
  식별자는 `rank-0.1.1`이었으며 Service는 이를 enum화하거나 재계산하지 않는다.
  과거에 저장된 다른 식별자는 당시의 historical provenance로 보존하고
  일괄 재기록하지 않는다.
- 이번 교정은 code enum/registry를 확장하지 않는다. 좌석·버스 근거가
  없으면 provider `messageCode`는 `null`, route/response warning은 등록된
  `BUS_DATA_UNAVAILABLE`를 사용하며 missing 값을 zero risk로 해석하지 않는다.
- DBML은 마지막 target state다. migration은 새 table을 추가하고, 새 `NOT NULL` column은 nullable 또는 safe default로 expand→backfill→constraint 순서를 따른다. old Service binary가 새 schema와 함께 동작하는 overlap 뒤 write/read를 전환한다.
- domain event payload와 event version은 변경하지 않는다. data-rights job은 Service DB 내부 lifecycle이며 cross-workstream event를 새로 요구하지 않는다.

## 1.2.0 compatibility decision

- 분류: backward-compatible Public API minor.
- 이메일 가입·로그인 endpoint는 additive이며 기존 guest/session consumer 동작을 바꾸지 않는다.
- `SessionContext.email`은 optional이고 USER 본인 session 응답에만 포함한다. 1.1 consumer는 이를 무시할 수 있다.

## 1.3.0 compatibility decision

- 회원가입 요청은 전용 `EmailRegistrationInput`으로 확장한다. 로그인 요청의 `EmailCredentialInput`은 유지한다.
- `SessionContext.nickname`은 optional additive field이며 USER 본인 session에만 포함한다.
- 기존 profile은 migration에서 비식별 기본 닉네임 `82TA 사용자`로 채운다.
- 필수 개인정보 처리 동의는 가입 시 true여야 하고, 네 선택 목적은 독립 boolean으로 명시한다.
- Routing Private API와 Routing DB에는 영향이 없다.
- Service DBML의 기존 `auth_user.email`과 `password_hash`, `authenticated_session`을 사용하므로 shared DB target shape와 Routing boundary에는 변화가 없다.
- 로그인 실패는 `INVALID_CREDENTIALS`, 중복 가입은 `ACCOUNT_ALREADY_EXISTS`로 표현하며 기존 오류 코드는 유지한다.
- Routing OpenAPI, domain event payload와 event version은 변경하지 않는다.

## 1.4.0 compatibility decision

- 분류: backward-compatible Public/Private API minor.
- 공통 `RouteLeg`에 optional `waitDuration`과 `travelDuration`을 추가한다.
  기존 `duration`, route 총시간, 순위, 비용과 ID의 의미는 바뀌지 않는다.
- 필드 부재는 구 producer 또는 미지원 상태이며 알려진 0과 구분한다. 새 Routing
  producer는 평가된 모든 leg에 두 필드를 제공하고 Service는 재계산 없이 전달한다.
- component P90은 각각 보수적인 marginal estimate이므로 합산해 전체 P90을
  재계산하지 않는다. 기존 `duration`이 authoritative total이다.
- `PlaceRef.address`는 optional nullable additive field다. 도로명 주소를 우선하고
  없으면 지번 주소를 제공하며, 값이 없으면 consumer는 주소 행을 숨긴다.
- `provider`, `providerPlaceId`, `regionCode`는 장소 검색 결과의 사용자용 보조
  label로 노출하지 않는다.
- DBML, migration, event, code registry와 optimize request wire family `1.0`은
  변경하지 않는다.

## 1.6.0 compatibility decision

- 분류: backward-compatible Public API minor. 기존 endpoint와 required
  `FavoriteJourney.defaultConstraints`를 유지하면서 optional typed
  `searchConditions`, optional `requestSummary`, 신규 atomic create endpoint를
  추가한다.
- 기존 opaque favorite row는 그대로 유효하다. Service는 legacy JSON을 typed
  조건으로 추측하지 않고 `searchConditions`를 null/absent로 반환하며 새 consumer는
  quick search를 비활성화한다. opaque field는 arbitrary JSON property를 허용하고
  generated TypeScript에서는 `Record<string, unknown>`으로 보존한다. 제거·narrowing은
  Public major에서만 한다.
- `PublicRouteSearchPreferences` 추출은 기존 inline schema와 field·required·enum·범위가
  동일한 구조적 refactor이며 기존 route-search wire 의미를 바꾸지 않는다.
- 기존 `favorite_journey.default_constraints` JSONB가 새 versioned value를 수용하므로
  DDL과 backfill이 없다. old Service binary는 이를 opaque object로 round-trip할 수 있다.
- `POST /api/v1/me/favorite-journeys/from-places`는 additive endpoint다. 두 saved
  place, favorite, digest-only ledger receipt를 한 transaction으로 만들며 24시간
  DB-authoritative owner-scoped idempotency를 제공한다. 기존 1.5 consumer가 사용하던
  collection CRUD와 서울 자전거 endpoint는 그대로 유지한다.
- additive Service DB ledger table은 database contract 1.3.0 expand다. old Service는
  table을 무시할 수 있고 기존 table/column에는 backfill이나 narrowing이 없다. endpoint
  rollback은 unexpired receipt drain/reader overlap 뒤 table contract를 수행한다.
- SavedPlace POST의 current `PRECISE_LOCATION` gate와 표준 400/401/403 응답,
  coordinate-changing PATCH의 400/401 응답은 위치 보존 정책과 이미 등록된 Problem을
  명시한 additive response-set correction이다. label/`isSensitive`-only PATCH와 DELETE는
  위치 동의 철회 뒤에도 가능하며 기존 USER·owner·CSRF 검증은 바뀌지 않는다.
- SavedPlace/FavoriteJourney POST·PATCH·DELETE의 `429 RATE_LIMITED`는 producer의 공유
  `favorite-location-write` quota를 문서화한 additive response다. GET에는 적용하지 않는다.
- Legacy FavoriteJourney POST의 400/401/403/404, PATCH의 400/401, DELETE의 401은
  producer가 이미 반환하는 canonical Problem status를 명시한 additive response-set
  correction이다. 성공 body, owner/consent 의미와 atomic from-places endpoint는 바뀌지 않는다.
- `requestSummary`는 optional coordinate/provider-free history display data다. 필드가
  없는 old response와 legacy row는 계속 유효하며 consumer는 summary를 route request로
  사용하지 않는다.
- Private Routing OpenAPI, generated Python client, Routing DB, event, error-code registry,
  route/ranking/budget semantics은 변경하지 않는다.

## 1.5.0 compatibility decision

- 분류: backward-compatible Public API minor.
- `GET /api/v1/bike-options`와 전용 응답 schema는 additive endpoint다. 기존
  Public consumer, route-search 요청·응답, 추천 순위와 Private Routing 계약은
  바뀌지 않는다.
- 자전거 시간은 서버가 대여소 사이 WGS84 직선거리를 시속 15km로 나누어
  정수 초로 제공한다. 도로·자전거길 경로시간이나 실시간 자전거 수량으로
  표현하지 않는다.
- 대여소 자료의 기준 월·공개일·출처·라이선스와 `NOT_PROVIDED` availability 상태를
  응답에 포함한다. 설치 거치대 수는 실시간 대여 가능 자전거 수가 아니다.
- 대여소는 요청 좌표와 5km 이내에서 거리·station ID 순으로 결정한다. 지원
  범위 밖은 오류로 위장하지 않고 빈 목록과 `null` 예상시간을 반환한다.
- DBML, migration, event, code registry, Private Routing API, ranking 및 route ID는
  변경하지 않는다.

## `rank-0.2.0` / `strategy-2.0.0` policy decision

- 분류: wire-compatible executable-policy revision. Existing request/response keys,
  types, enum values, nullability, HTTP statuses, DBML, events, and generated clients
  do not change. Consumers already treat `rankingPolicyVersion` and the free-form
  computation cache metadata as opaque provenance.
- `rank-0.2.0` identifies exact `FASTEST` and exact zero-Taxi-upper-cost
  `PUBLIC_TRANSIT_ONLY` anchors selected from the fully evaluated, constraint-feasible,
  deduplicated pool. Epsilon dominance only compresses the display/frontier set.
- `strategy-2.0.0` is one combined identifier for the currently implemented finite
  admitted-payload strategy, exactification, and bounded time-dependent graph-search
  policy. It does not certify Provider source exhaustion or a network-global optimum.
- Candidate, exactification, graph expansion, per-node label, complete-path,
  Provider-call, and deadline caps remain mandatory. If an active cap makes the
  bounded result uncertified, the producer fails closed through the existing
  capacity/deadline response; it must not emit `COMPLETE`, a provisional optimum,
  a new status, or an unregistered warning.
- CCR-008 Finding A (`transferCount`/`maxTransfers`) and Finding C (additive
  completeness metadata/warning) remain deferred. This decision must not be used to
  infer or backfill either meaning.
- Historical `rank-0.1.1` and `strategy-1.0.0` values remain immutable provenance.
  Existing rows, replay bundles, telemetry, and cached responses are not relabeled.
  Rollout requires a process restart and eviction/non-reuse of old-version response
  caches so an old result cannot be served under the new runtime identifiers.
- Current Routing persistence has a ranking-policy column but no dedicated combined
  strategy/search-policy column; current public projection intentionally omits
  computation metadata. Therefore this approval covers the runtime policy,
  `/v1/version` ranking value, private computation provenance, existing ranking
  persistence, deterministic replay, and version-coherent canonical examples only.
  It does not claim full strategy provenance in durable persistence, shared cache, or
  telemetry. Any such release claim requires a separately governed additive contract
  and storage/observability change.
- Activation conditions: policy defaults, Routing `/v1/version`, optimize computation,
  platform versions, deterministic canonical examples, producer/consumer assertions,
  and replay fixtures must all report the new identifiers; all bounded-cap tests must
  prove fail-closed behavior; both workstreams must approve the derived examples and
  contract-lock refresh. Until then the change is not merge/release evidence.
