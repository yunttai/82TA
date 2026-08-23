# Glossary and Canonical Semantics

이 문서의 용어와 단위는 두 하네스가 공통으로 사용한다. 같은 개념에 별도 이름을 만들지 않는다.

## 제품·경로

| 용어 | 정의 |
|---|---|
| Route Search | 사용자 입력 하나에 대한 전체 최적화 실행 |
| Route Candidate | 제약과 평가를 거치는 하나의 완성 여정 후보 |
| Route Leg | WALK, TAXI, BUS, SUBWAY, GTX, TRANSFER, WAIT 중 하나의 연속 구간 |
| Transit Baseline | taxi cost가 0인 최상의 대중교통 비교 경로 |
| FASTEST | strict feasible 후보 중 P50 총시간 최소 |
| STABLE | P90과 실패 위험이 가장 낮은 추천 |
| EFFICIENT | 추가 taxi cost 대비 절감시간이 큰 Pareto point |
| Pareto Frontier | 시간·비용·위험에서 다른 후보에 완전히 지배되지 않는 집합 |
| Taxi Bridge | 두 대중교통망 사이의 짧은 taxi 연결 leg |
| Upstream Stop | 같은 노선의 진행방향 상류에서 먼저 승차하기 위한 정류장 |

## 시간·비용

| 용어 | 정의 |
|---|---|
| P50 | 중앙 예상값. 동일 조건의 절반 정도가 이 값 이내일 것으로 보는 값 |
| P90 | 보수적 예상값. 약 90%가 이 값 이내일 것으로 보는 값 |
| Taxi Dispatch Wait | 택시 호출부터 승차까지의 대기. 공개 driving route와 별도 |
| Taxi Cost Expected | 택시 예상비 중앙값 |
| Taxi Cost Upper | 예산 엄수 판정에 사용하는 보수적 상한 |
| Strict Budget | 모든 taxi leg의 upper 합계가 사용자 예산 이하인 정책 |
| Transfer Margin | 다음 leg 탑승 가능 시간에서 필수 이동·buffer를 뺀 여유 |
| Expected Delay | 실패 확률과 실패 시 추가 대기를 결합한 기대 지연 |

## Bus Intelligence

| 용어 | 정의 |
|---|---|
| Seat Unavailable Probability | 목표 승차 정류장 도착 시 잔여좌석이 0일 확률 |
| Low Seat Probability | 목표 정류장에서 잔여좌석이 임계값 이하일 확률 |
| Boardability Proxy | 실제 승차 outcome이 없을 때 좌석 가용성으로 근사한 값 |
| Actual Boarding Probability | 실제 승차 성공·실패 label이 있을 때만 사용하는 확률 |
| Candidate Vehicle | 사용자 정류장 도착시각 이후 도착하는 평가 대상 차량 |
| Expected Wait | 첫 차량 실패와 다음 차량을 포함한 기대 대기시간 |
| P90 Wait | 보수적 대기시간 |
| Trip Identity | route·direction·vehicle·service date·trip start를 결합한 운행 단위 |
| Mapping Confidence | 외부 transit step이 canonical GBIS route·station·direction과 일치하는 신뢰도 |
| Coverage | LIVE, PARTIAL, HISTORICAL, UNSUPPORTED 등 적용 데이터 수준 |

## 데이터 출처

| 값 | 의미 |
|---|---|
| OBSERVED | 공식 실시간 관측 |
| PROVIDER_ESTIMATE | 외부 API의 ETA·요금·시간 추정 |
| MODEL_PREDICTED | 자체 모델 예측 |
| HISTORICAL_PROXY | 과거 이력·prior 기반 fallback |
| USER_INPUT | 사용자가 직접 입력 |
| UNKNOWN | 판단 불가 |

## 계약 단위

| 값 | 규칙 |
|---|---|
| Coordinate | WGS84, `lon`, `lat` |
| Timestamp | ISO 8601, timezone offset 필수 |
| Duration | integer seconds |
| Distance | integer meters |
| Money | integer KRW |
| Probability | 0.0~1.0 |
| Public ID | opaque UUID 또는 ULID |

## 금지 표현

- `0석 = 확정 승차 실패`
- `택시비 확정`
- `예측 ETA = 공식 실시간`
- `데이터 없음 = 위험 낮음`
- `boardability proxy = 실제 승차 확률`
- `일반버스 혼잡 = 다음 차량을 기다려야 함`
