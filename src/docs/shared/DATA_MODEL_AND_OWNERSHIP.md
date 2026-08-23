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

## 9. Migration

- expand/contract
- large backfill 분리
- old/new version 동시 호환
- cross-service migration 금지
- legacy SQLite import 후 row count·distinct·distribution reconciliation
