# API Contract Guide

## 1. 계약 원본

```text
src/contracts/openapi/common/components.v1.yaml
src/contracts/openapi/service-public.v1.yaml
src/contracts/openapi/routing-private.v1.yaml
```

이 세 파일 외에 동일 request/response schema를 복사해 만들지 않는다.

## 2. 공통 규칙

- media type: `application/json`, 오류는 `application/problem+json`
- field naming: camelCase
- timestamp: ISO 8601 timezone offset 필수
- duration: integer seconds
- distance: integer meters
- money: integer KRW
- coordinate: WGS84 `lon`, `lat`
- probability/confidence score: 0.0~1.0
- public ID: opaque UUID/ULID
- 모든 비싼 POST는 `Idempotency-Key` 지원
- 모든 요청은 `X-Correlation-Id` 전달
- Routing 요청은 `X-Request-Deadline` 전달

## 3. Public Service API

핵심 endpoint:

```text
GET    /api/v1/places/suggest
GET    /api/v1/places/reverse-geocode
POST   /api/v1/guest-sessions
GET/DELETE /api/v1/session
POST   /api/v1/route-searches
GET    /api/v1/route-searches/{searchId}
POST   /api/v1/route-searches/{searchId}/feedback
GET/PUT /api/v1/me/preferences
GET/POST /api/v1/me/saved-places
PATCH/DELETE /api/v1/me/saved-places/{savedPlaceId}
GET/POST /api/v1/me/favorite-journeys
PATCH/DELETE /api/v1/me/favorite-journeys/{favoriteJourneyId}
GET      /api/v1/me/consents
PUT      /api/v1/me/consents/{consentType}
POST     /api/v1/me/data-exports
GET      /api/v1/me/data-exports/{jobId}
POST     /api/v1/me/data-deletions
GET      /api/v1/me/data-deletions/{jobId}
DELETE /api/v1/me/data  # deprecated compatibility alias
GET    /api/v1/support/capabilities
```

Public API는 내부 provider status 전체, 원문 번호판, raw payload, artifact URI, feature vector를 노출하지 않는다.

### Public→Private 정책

- `DEPART_AT`만 Private 1.x로 전달한다. `ARRIVE_BY`는 `ARRIVE_BY_UNSUPPORTED`이며 Service가 시각을 역산하지 않는다.
- Public `allowedModes`와 `avoidHighBusSeatRisk`는 Private의 같은 의미 필드로 pass-through한다. 생략된 mode 목록만 canonical 전체 목록으로 채운다.
- `saveToHistory`·owner·consent·guest token·user identity는 Routing으로 전송하지 않는다.
- `baseline`은 Routing의 `publicTransitOnly` recommendation ID가 지시한 route다. Service가 새 baseline을 고르지 않는다.
- Public `support`는 Routing capability를 축약하며 missing coverage는 `UNKNOWN`이다.

### Route leg 시간 구성

- `RouteLeg.duration`은 기존과 동일하게 해당 leg에 귀속된 전체 경과시간이다.
- optional `waitDuration`은 사용자가 해당 leg를 탈 준비가 된 뒤 실제 이동이
  시작되기까지의 버스·철도 승차 대기 또는 택시 배차 대기다.
- optional `travelDuration`은 승차·배차 대기 이후 실제 이동시간이다.
- 새 Routing producer는 두 component를 모두 제공한다. 필드 부재는 구 producer
  응답이며 알려진 0분으로 해석하지 않는다.
- 시간대별 재평가와 상관관계 때문에 component P90을 단순 합산해 전체 P90을
  다시 계산하지 않는다. `duration`과 route `totalDuration`이 최종 권위값이다.

## 4. Private Routing API

```text
POST /v1/routes/optimize
GET  /v1/capabilities
GET  /v1/health/live
GET  /v1/health/ready
GET  /v1/version
```

관리 endpoint는 private network와 별도 운영 권한을 요구한다.

## 5. Partial Response

`200 PARTIAL` 가능:

- GBIS 좌석만 없음
- GITS context 없음
- 자체 ETA 대신 provider 또는 historical fallback
- Taxi Bridge enrichment 실패
- geometry 일부 누락

전체 실패:

- 좌표·제약 invalid
- transit과 taxi-only 모두 생성 불가
- strict budget 검증을 할 수 없음
- contract major 불일치

## 6. Versioning

- required field의 의미 변경·삭제는 major change
- optional field 추가는 compatible minor change
- enum consumer는 unknown value를 처리
- Routing producer는 Service consumer보다 먼저 backward-compatible field를 배포
- deprecation 기간 뒤 제거
- compatible minor는 OpenAPI/DB/code registry metadata의 minor를 올리되, Private request의 `contractVersion: "1.0"`은 1.x wire compatibility family로 유지한다.
- `/v1/version.contractVersion`은 현재 로드된 Private OpenAPI의 repository
  metadata(`1.2.0`)를 보고한다. optimize request/response body의 wire family
  `1.0`과 구분한다.
- `rankingPolicyVersion`은 exact opaque provenance이며 Service가 의미를
  추론하거나 다시 계산하지 않는다.

## 7. Generated Clients

OpenAPI에서 생성되는 코드는 다음에만 둔다.

```text
src/generated/service-client-ts
src/generated/routing-client-python
src/generated/contract-models
```

generated code를 직접 수정하지 않는다. CI는 원본과 생성 결과 diff를 검사한다.

## 8. Contract Change Checklist

- [ ] PRD requirement ID 연결
- [ ] OpenAPI와 examples 수정
- [ ] code registry 수정
- [ ] DBML/migration 영향 분석
- [ ] consumer/provider contract test
- [ ] security/privacy 영향
- [ ] backward compatibility
- [ ] context version·lock 갱신
- [ ] 양쪽 하네스 QA 승인
