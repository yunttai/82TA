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
POST   /api/v1/route-searches
GET    /api/v1/route-searches/{searchId}
POST   /api/v1/route-searches/{searchId}/feedback
GET/PUT /api/v1/me/preferences
GET/POST /api/v1/me/saved-places
GET/POST /api/v1/me/favorite-journeys
DELETE /api/v1/me/data
GET    /api/v1/support/capabilities
```

Public API는 내부 provider status 전체, 원문 번호판, raw payload, artifact URI, feature vector를 노출하지 않는다.

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
