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

## GA 수용

- 대표 경로 실제 P50/P90·비용 오차 측정
- strict budget 현장 위반 0건 목표
- Bus Intelligence가 ranking을 역전하는 사례
- HIGH mapping precision 99.5% 권고 gate
- P95 7초
- Provider 하나 장애 시 partial
- model rollback·RDS restore drill
- privacy 삭제·export와 보안 테스트
