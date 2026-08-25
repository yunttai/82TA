# Data Model and Ownership

## 1. Database per Service

```text
Service Product owns Service DB.
Routing & Intelligence owns Routing DB.
```

상대 DB를 직접 읽지 않는다. 필요 정보는 API 또는 비식별 event로 전달한다.

## 2. Service DB 전용

- 계정·session·social identity
- 사용자 preference·privacy setting
- saved place·favorite journey
- route search public snapshot
- user feedback·consent·audit
- guest/authenticated session hash와 revoke 상태
- data export·deletion job 상태와 내부 artifact reference

## 3. Routing DB 전용

- Provider capability·health
- canonical route·stop·provider entity mapping
- bus vehicle·trip·arrival·location observation
- route run·candidate·leg·transfer·Bus Intelligence
- model family·version·metric·deployment·prediction audit
- ingestion checkpoint·data quality

## 4. Service→Routing 전송 가능

- opaque request ID
- origin/destination coordinate와 region hint
- departure time·arrival deadline
- taxi budget·walk·transfer·taxi leg constraints
- risk/walk/transfer aversion numeric value
- locale·timezone

## 5. 전송 금지

- user ID·email·이름·전화번호
- saved place label
- 사용자 검색 이력 전체
- social account ID

## 6. 시간 semantics

- `observedAt`: 실제 관측 시각
- `validAt`/valid range: 예보·mapping 유효시각
- `ingestedAt`: 시스템 수신시각
- `createdAt`: 레코드 생성시각

## 7. Raw Payload

약관이 허용할 때만 제한된 object storage에 저장한다. 불가하면 request fingerprint, schema version, normalized result만 남긴다.

## 8. Retention 기본안

| 데이터 | 기본 보존 |
|---|---|
| 비회원 검색 | 24시간~7일 |
| 회원 검색 기록 | 기본 90일, 사용자 설정 |
| saved place | 삭제 또는 계정 종료까지 |
| public result snapshot | 30~90일 |
| provider metric | 90일 이상 집계 |
| normalized GBIS observation | 장기, 약관 검토 |
| raw provider payload | 최소 기간·약관 준수 |
| model artifact·metric | 재현을 위해 장기 |
| security audit | 정책상 필요한 기간 |
| guest session | 최대 24시간, revoke/expiry 후 token material 제거 |
| data export artifact | download 만료 후 즉시 또는 운영 정책상 최단 기간 |
| data-rights job metadata | 법적·운영 증빙 기간, exact exported content 제외 |
| favorite creation idempotency receipt | 정확히 24시간 active replay 후 purge 대상; 사용자 export에서 제외 |

`saveToHistory=false` 검색은 결과 조회·idempotency에 필요한 짧은 TTL만 사용한다. `true`는 로그인 사용자와 현재 `SEARCH_HISTORY` 동의를 요구한다. owner 경계는 user 또는 anonymous session 중 정확히 하나여야 하며 Routing에는 어느 owner 식별자도 전달하지 않는다.

Public 1.5 favorite quick search는 기존 `favorite_journey.default_constraints` JSONB에 검증된 `FavoriteJourneySearchConditionsV1`을 저장한다. 별도 column이나 backfill은 필요하지 않다. 기존 arbitrary object는 그대로 보존하고 typed 값으로 추론하지 않으며, 사용자가 다시 저장하기 전에는 quick search를 비활성화한다. 같은 JSONB에는 절대 출발시각, 도착 마감, `saveToHistory`, 경로 결과·추천 ID·ranking provenance를 저장하지 않는다.

임의 장소 즐겨찾기 생성은 두 `saved_place`, 한 `favorite_journey`, 한 `favorite_creation_idempotency` receipt를 같은 Service DB transaction에 기록한다. 실패 시 네 row를 모두 rollback한다. 원장은 owner/key HMAC digest unique constraint로 동시 생성을 직렬화하고 24시간 동안 DB-authoritative replay를 보장한다. raw key·request/response·label·display name·좌표는 원장에 저장하지 않는다. 만료 row만 cleanup하며, digest key rotation은 unexpired row의 이전 version을 유지한다. active receipt의 세 resource FK는 hard delete를 막고 soft delete 뒤 replay는 resource를 복구하지 않는다. 계정 hard delete는 ledger를 먼저 지우며 사용자 export에는 장소·즐겨찾기만 포함하고 내부 digest/ledger는 제외한다. 이 과정과 history summary는 Service 내부이며 Routing DB나 Routing request에 saved-place label, user ID 또는 favorite ID를 추가하지 않는다.

## 9. Migration

- expand/contract
- large backfill 분리
- old/new version 동시 호환
- cross-service migration 금지
- `favorite_creation_idempotency`는 additive expand migration으로 먼저 배포하고 old Service overlap을 허용한다. endpoint rollback은 24시간 receipt drain/compatibility reader 뒤에만 table을 contract한다.
- legacy SQLite import 후 row count·distinct·distribution reconciliation
