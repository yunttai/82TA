# Test and Acceptance Strategy

## 테스트 계층

| 계층 | 대상 |
|---|---|
| Unit | domain 계산, serializer, mapping signal, cost, Pareto |
| Property | budget·time·probability·dominance invariant |
| Contract | Frontend↔Service, Service↔Routing, Provider schema |
| Integration | DB·Redis·model runtime·adapter |
| Replay | 비식별 Provider snapshot으로 전체 Routing |
| E2E | React→Service→Routing→mock/real Provider |
| Model | split·calibration·slice·drift |
| Performance | 7초 deadline, concurrency, candidate 폭발 |
| Resilience | timeout, 429, schema drift, DB/Redis 장애 |
| Security | auth, CSRF, SSRF, rate, secret, artifact |
| Field | 대표 네 경로 실제 이동 |

## 불변식

- strict route의 `taxiCost.upper <= budget`
- `P90 >= P50`
- leg 시간이 역행하지 않음
- 확률 0~1
- 사용자 도착 이전 차량 제외
- 일반형 `crowded`는 seat failure penalty가 아님
- mapping LOW이면 Bus Intelligence 미적용
- missing future label은 negative가 아님
- Pareto frontier에 완전 지배 후보 없음
- 동일 snapshot replay는 동일 결과
- 따릉이 예상시간은 `ceil(직선거리 m × 3600 / 15000)` 정수 초이고 실시간 수량으로 표시하지 않음
- 따릉이 예상은 첫 pickup과 그 ID가 아닌 가장 가까운 return을 참조하며, 그런 return이 없으면 `null`

## 경계면 QA

QA는 양쪽을 동시에 읽는다.

| 생산자 | 소비자 |
|---|---|
| Routing response | generated Python client·Service projection |
| Service response | generated TypeScript client·React hook |
| Django model | serializer·public response |
| OpenAPI | handler·client·fixture |
| DBML/migration | ORM·repository |
| status enum | frontend state/render branch |

## 대표 Acceptance Scenario

1. 명지대→판교, 예산 0/5천/1만/2만
2. 판교→명지대, 저녁·막차 근접
3. 광교→판교, 신분당선·버스·택시 비교
4. 판교→광교, egress taxi와 환승 위험
5. GBIS 좌석 정보 없음 → PARTIAL
6. mapping LOW → Bus Intelligence 미적용
7. strict budget 상한 초과 후보 제거
8. Provider timeout → cache/fallback/partial
9. model artifact 손상 → fallback과 alert
10. 사용자 기록·saved place 삭제
11. 임의 장소 즐겨찾기 생성 중 어느 write가 실패해도 두 saved place, favorite, idempotency ledger row가 모두 남지 않음
12. 동일 favorite-create owner·key·body는 DB restart/Redis 장애·동시 요청 뒤에도 24시간 같은 immutable ID receipt를 201로 반환하고, unexpired key의 다른 body는 409
13. legacy opaque favorite은 quick search가 비활성화되고 typed 조건의 unknown/missing field는 fail closed
14. history request summary에 좌표·주소·Provider ID가 없고 owner-only/no-store로 제공됨
15. saved place 생성과 `place` 포함 PATCH는 현재 `PRECISE_LOCATION` 동의가 없으면 403이고, label/`isSensitive`만 바꾸는 PATCH와 DELETE는 동의 철회 후에도 owner·CSRF 검증 아래 허용됨
16. legacy favorite의 nonempty arbitrary `defaultConstraints`가 그대로 유효하고 생성 TypeScript 타입은 `Record<string, unknown>`이며 typed `searchConditions`의 unknown field는 거부됨
17. SavedPlace/FavoriteJourney POST·PATCH·DELETE는 공통 write quota 초과 시 429를 반환하고 GET response set에는 쓰기 quota의 429를 추가하지 않음
18. 첫 favorite-from-places 생성은 현재 `PRECISE_LOCATION` 동의와 write quota를 요구하지만 성공 receipt의 same-body replay는 동의 철회 뒤에도 quota 재소비 없이 성공하고, expiry 뒤 새 생성은 다시 동의를 요구함
19. ledger에는 raw idempotency key·body·response·label·display name·좌표가 없고 digest key rotation 중에도 모든 unexpired version을 조회할 수 있음
20. legacy FavoriteJourney POST/PATCH/DELETE의 canonical 4xx response set이 producer와 OpenAPI/generated client에서 일치함
21. 서울 내 두 좌표 → 인근 따릉이 위치·시속 15km 단순 예상과 실시간 수량 미제공 안내

## GA 수용

- 대표 경로 실제 P50/P90·비용 오차 측정
- strict budget 현장 위반 0건 목표
- Bus Intelligence가 ranking을 역전하는 사례
- HIGH mapping precision 99.5% 권고 gate
- P95 7초
- Provider 하나 장애 시 partial
- model rollback·GCE database backup/restore drill
- privacy 삭제·export와 보안 테스트
