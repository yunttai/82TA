# ADR-0012: Atomic typed favorite quick search

- 상태: Accepted
- 날짜: 2026-08-25
- 결정자: Service Product, Routing & Intelligence contract reviewers
- 관련 요구사항: UJ-005, FR-IAM-003, SP-FR-008
- 관련 계약: Public Service OpenAPI 1.5.0, Service DBML, CCR-20260825-FAVORITE-QUICK-SEARCH

## Context

Public 1.4의 `FavoriteJourney.defaultConstraints`는 임의 object라 generated client가
검색 요청을 안전하게 만들 수 없다. 또한 사용자가 임의의 출발지와 목적지를 바로
즐겨찾기로 추가하려면 브라우저가 saved-place 두 건과 favorite 한 건을 독립적으로
생성해야 했고, 중간 실패 시 고아 장소나 불완전한 사용자 상태가 남을 수 있었다.

즐겨찾기는 과거 경로 결과가 아니라 새 경로 검색의 입력이어야 한다. 저장된 절대
출발시각은 빠르게 오래되며, 검색 기록과 정확한 장소 저장 동의는 사용자가 언제든
변경할 수 있다. Service의 사용자 데이터 의미를 Routing으로 이동해서도 안 된다.

## Decision

Public 1.5에 optional `FavoriteJourney.searchConditions`를 추가한다. V1 조건은 다음
필드만 갖는 closed schema다.

- `schemaVersion=1`
- `departurePolicy=DEPART_AT_CLICK`
- canonical `TaxiBudget`
- Public route-search preferences와 requested recommendation 종류

절대 출발시각, 도착 마감, `saveToHistory`, route/result/rank ID는 저장하지 않는다.
사용자가 즐겨찾기를 실행할 때 Web은 현재 owner의 두 active SavedPlace를 확인하고
timezone-aware 클릭 시각으로 기존 Public route-search를 정확히 한 번 호출한다.
검색 기록 저장은 그때의 `SEARCH_HISTORY` 동의로 결정한다.

Public 1.x 호환을 위해 required opaque `defaultConstraints`를 deprecated 상태로
유지한다. legacy row를 typed 조건으로 추측하지 않고 새 조건이 없으면 quick search를
비활성화한다.

임의 장소 생성에는 idempotent
`POST /api/v1/me/favorite-journeys/from-places`를 추가한다. 현재 USER와
`PRECISE_LOCATION` 동의를 검증한 뒤 saved place 두 건과 favorite 한 건을 같은 Service
DB transaction에서 생성한다. 같은 transaction에 Service 소유
`favorite_creation_idempotency` row를 기록하고, 같은 owner·key·canonical body의
24시간 내 재시도는 DB 원장에서 동일한 불변 ID receipt를 재구성해 201로 반환한다.
이 replay는 새 위치를 저장하지 않으므로 현재 `PRECISE_LOCATION` 동의를 다시 요구하지
않고 write quota도 다시 소비하지 않는다. unexpired key를 다른 body에 사용하면 409다.
만료 후 요청은 새 생성이므로 당시의 위치 동의를 다시 검증한다.

Receipt는 `favoriteJourneyId`, 두 saved-place ID, `createdAt`,
`idempotencyExpiresAt`만 포함한다. mutable resource 표현은 owner-scoped 목록 API에서
새로 읽는다.

History에는 optional coordinate/provider-free `RouteSearchRequestSummary`를 제공한다.
이는 표시 전용이며 route search 재구성에 사용하지 않는다.

## Alternatives Considered

1. 기존 `defaultConstraints`를 typed required schema로 교체: 이미 허용된 임의 JSON과
   기존 consumer를 깨므로 거부했다.
2. 브라우저에서 saved-place 두 건과 favorite을 세 번 POST: 부분 성공과 재시도 중복을
   막을 원자적 경계가 없어 거부했다.
3. Favorite에 PlaceRef와 좌표 snapshot을 중복 저장: 장소 수정과 삭제 의미가 갈리고
   민감 위치 복제량이 늘어 거부했다.
4. 전용 Routing favorite endpoint: 사용자 identity와 저장 장소 소유권을 Routing으로
   이동시키므로 거부했다.

## Consequences

- Public API에는 optional typed fields와 additive endpoint가 생기며 기존 1.x consumer는
  계속 동작한다.
- Service producer는 typed validation, owner/consent 확인, DB transaction,
  owner-scoped durable idempotency를 구현해야 한다.
- Web consumer는 새 generated type만 사용하고 legacy row를 실행하지 않는다.
- Routing API, provider orchestration, optimizer와 ranking에는 변화가 없다.

## Security / Privacy / Cost

정확한 두 좌표와 사용자가 붙인 label은 민감한 Service 데이터다. 첫 생성은 USER
session, CSRF, 현재 `PRECISE_LOCATION` 동의, rate limit, `no-store`, 로그 redaction,
삭제·export·retention 적용을 요구한다. 성공 receipt replay는 USER·CSRF·owner를 계속
검증하지만 새 위치 write가 아니므로 동의와 write quota를 재소비하지 않는다.
Idempotency key와 canonical request는 서로 다른 domain의 versioned HMAC으로만 저장한다.
raw key·body·response·label·display name·좌표는 원장과 log에 남기지 않는다. History 표시명도 집 주소가 될 수 있어 coordinate가
없더라도 민감하게 취급한다. 새 Provider 호출은 없어 외부 API 비용 증가는 없다.

## Migration and Rollback

기존 `default_constraints` JSONB에는 DDL이나 backfill이 없다. additive ledger table은
expand migration으로 먼저 배포하며 old binary는 이를 무시한다. ledger, 두 saved place,
favorite은 한 transaction에서 commit/rollback한다. unique owner/key digest가 동시 생성의
직렬화 지점이다. expiry cleanup은 `expires_at <= now()` row만 지우고 unexpired 24시간
replay를 보존한다. digest key rotation은 모든 unexpired row의 version을 조회할 key ring을
유지해야 하며 current key만 즉시 교체해서는 안 된다. active ledger FK는 resource hard
delete를 보호하고 soft delete 뒤 replay는 ID receipt만 반환하며 자원을 부활시키지 않는다.
계정 삭제는 ledger를 먼저 지우고 export에서는 내부 ledger/digest를 제외한다.

rollback은 새 endpoint write를 먼저 중지한 뒤 24시간 replay/drain 또는 compatibility
reader를 유지하고 Web을 되돌린다. 그 뒤에만 ledger table을 제거할 수 있다. 구 Service는
typed JSON을 opaque object로 보존할 수 있다. Public 1.x field 제거는 별도 major 결정이다.

## Verification

- OpenAPI/example validation과 generated-client reproducibility
- legacy favorite acceptance와 strict V1 rejection tests
- 두 saved place와 favorite의 transaction rollback 및 idempotent retry tests
- restart/Redis 장애·동시 요청 뒤에도 DB receipt replay, body mismatch 409, 24시간 expiry,
  consent 철회 후 same-body replay와 expiry 후 새 생성 consent gate tests
- owner, CSRF, PRECISE_LOCATION consent, no-store와 redaction tests
- click-time departure와 한 번의 Public route-search POST consumer test
- Service/Routing context parity와 unchanged Private Routing hashes

## Supersedes / Superseded By

없음.
