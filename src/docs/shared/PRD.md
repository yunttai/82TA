# Product Requirements Document

## 0. 문서 메타데이터

| 항목 | 값 |
|---|---|
| 제품 | Budget Route Platform |
| 문서 버전 | 1.1.0 |
| 상태 | Baseline / 공동 원본 |
| 기준일 | 2026-08-23 KST |
| 적용 작업흐름 | Service Product, Routing & Intelligence |
| 원본 상세 기획 | `src/docs/reference/FINAL_INTEGRATED_PLAN_v1.md` |
| 변경 절차 | ADR + 공통 계약 PR + 두 QA 승인 + lock 갱신 |

## 1. 비전

경기 남부와 서울 사이를 이동하는 사용자가 제한된 택시 예산을 가장 효과적인 구간에 사용하도록 돕는다. 일반 길찾기의 예정 소요시간뿐 아니라 택시 대기, 실시간 도로상황, 버스 ETA, 좌석 부족으로 인한 첫 차량 실패, 환승 불확실성을 하나의 총시간 분포로 계산한다.

## 2. 문제

기존 경로 결과는 다음 질문에 충분히 답하지 못한다.

- 택시를 전 구간이 아니라 일부만 사용할 때 최적 구간은 어디인가?
- 버스가 도착해도 좌석 부족으로 타지 못할 가능성을 어떻게 반영하는가?
- 평균 50분과 P90 80분인 경로를 안정적인 60분 경로와 어떻게 비교하는가?
- 가까운 정류장이 항상 실제로 가장 빠른 승차 지점인가?
- 사용자의 전체 택시 예산을 여러 taxi leg에 어떻게 배분하는가?

## 3. 목표

### G-001 경로 가치

사용자가 지정한 taxi budget 안에서 순수 대중교통보다 실제 시간 절감 가능성이 있는 복합교통 경로를 제공한다.

### G-002 승차 가능성 반영

지원되는 경기 광역·좌석버스 구간에서 사용자 도착시각 이후 후보 차량의 ETA와 좌석 가용성을 경로 대기시간에 반영한다.

### G-003 안정성

P50뿐 아니라 P90, 예측구간, 환승 여유, 데이터 최신성으로 경로의 위험을 표현한다.

### G-004 설명 가능성

각 추천에 계산 근거가 되는 reason code, warning code, provenance를 제공한다.

### G-005 상용 운영 가능성

Provider 장애, quota, 모델 drift, 개인정보, 복구, 비용을 운영 가능한 방식으로 관리한다.

### G-006 병렬 개발과 합류

두 작업흐름이 별도 구현되더라도 동일한 계약·용어·DB 소유권을 사용하고 계약 테스트로 안전하게 합친다.

## 4. 비목표

- 실제 택시 호출·배차 중개
- 턴바이턴 자동차·도보 내비게이션
- 버스 좌석 예약 또는 승차 성공 보장
- 전국 모든 버스의 좌석 예측
- 데이터 없이 생성한 정밀한 실시간 지하철 혼잡
- 무제한 교통수단 조합의 완전 일반 그래프 탐색
- 근거 없는 자연어 AI 설명
- V1의 이동 중 백그라운드 위치 추적과 실시간 재추천

## 5. 사용자

| Persona | 핵심 요구 | 성공 판단 |
|---|---|---|
| 경기권 통근자 | 광역버스 만차와 지각 회피 | 정시 도착 가능성과 대체 경로 |
| 통학생 | 제한된 예산으로 수업 시각 준수 | 최소 필요 예산과 안정성 |
| 비역세권 사용자 | 어느 역·정류장까지 택시를 쓸지 | 추가 비용 대비 절감시간 |
| 약속 이동 사용자 | 평균보다 지연 위험이 중요 | P90과 환승 위험 |
| 동행 그룹 | 택시비 분담 | 총액과 1인당 비용 |

## 6. 핵심 사용자 여정

### UJ-001 현재 출발 검색

1. 사용자가 출발지·목적지·지금 출발·택시 예산을 입력한다.
2. Service Backend가 입력과 quota를 검증한다.
3. Routing Server가 transit baseline과 taxi 결합 후보를 계산한다.
4. 지원 버스 구간을 GBIS와 매핑하고 Bus Intelligence를 적용한다.
5. 네 추천과 Pareto 비교를 반환한다.
6. Web App이 지도·카드·경고·근거를 표시한다.

### UJ-002 미래 출발 검색

현재 출발 Provider와 미래 운행 Provider의 capability를 구분한다. 미래 대중교통을 현재 경로와 동일한 정확도로 표현하지 않는다.

### UJ-003 선탑승 정류장

가까운 정류장과 같은 노선 상류 정류장을 비교하여 taxi access 비용보다 좌석 가용성·대기시간 개선이 큰 경우 별도 후보를 제공한다.

### UJ-004 부분 장애

GBIS 좌석 데이터가 없더라도 transit·taxi 경로를 `PARTIAL`로 제공하고 좌석 정보 미지원으로 표시한다. 필수 transit과 taxi-only 모두 생성할 수 없으면 오류를 반환한다.

### UJ-005 기록과 즐겨찾기

비회원은 즉시 검색 가능하다. 회원은 동의에 따라 검색 이력·저장 장소·즐겨찾기·선호를 관리하고 삭제·내보내기를 요청할 수 있다. 즐겨찾기는 두 Service 소유 저장 장소와 버전이 지정된 검색 조건을 보존하며, 한 번의 사용자 동작으로 클릭 시점의 새 `DEPART_AT` 검색을 시작한다. 과거 결과나 절대 출발시각은 재사용하지 않는다.

## 7. 기능 요구사항

### 7.1 장소와 입력

| ID | 요구사항 | 우선순위 | 소유 |
|---|---|---:|---|
| FR-PLACE-001 | 장소명·주소 자동완성과 좌표 확정 | P0 | Service |
| FR-PLACE-002 | 브라우저 현재 위치를 일회성 사용 | P0 | Service |
| FR-PLACE-003 | 지도에서 직접 좌표 선택 | P1 | Service |
| FR-PLACE-004 | 좌표→주소·행정구역 표시 | P0 | Service |
| FR-INPUT-001 | 지금 출발과 지정 시각 출발 | P0 | Shared |
| FR-INPUT-002 | taxi budget 0·5천·1만·2만·직접 입력 | P0 | Service |
| FR-INPUT-003 | max walk, transfer, taxi legs | P0 | Shared |
| FR-INPUT-004 | 도착 마감시각·목표 정시 확률 | P1 | Shared |
| FR-INPUT-005 | 접근성·도보 회피·혼잡 회피 | P1 | Service |

### 7.2 경로 생성

| ID | 요구사항 | 우선순위 | 소유 |
|---|---|---:|---|
| FR-ROUTE-001 | `TRANSIT_ONLY` 후보 | P0 | Routing |
| FR-ROUTE-002 | `TAXI_TRANSIT` 후보 | P0 | Routing |
| FR-ROUTE-003 | `TRANSIT_TAXI` 후보 | P0 | Routing |
| FR-ROUTE-004 | `TAXI_TRANSIT_TAXI` 후보 | P0 | Routing |
| FR-ROUTE-005 | `TAXI_ONLY` 후보 | P0 | Routing |
| FR-ROUTE-006 | `UPSTREAM_STOP_TAXI_TRANSIT` | P1/GA | Routing |
| FR-ROUTE-007 | `TRANSIT_TAXI_BRIDGE_TRANSIT` | P1/GA | Routing |
| FR-ROUTE-008 | 앞 leg 결과 시각으로 뒤 leg 비용 재평가 | P0 | Routing |
| FR-ROUTE-009 | 후보 상한과 단계별 pruning | P0 | Routing |
| FR-ROUTE-010 | strict budget은 taxi upper cost 기준 | P0 | Routing |

### 7.3 Bus Intelligence

| ID | 요구사항 | 우선순위 | 소유 |
|---|---|---:|---|
| FR-BUS-001 | Kakao BUS step을 GBIS route·station·direction과 매핑 | P0 | Routing |
| FR-BUS-002 | HIGH mapping만 자동 적용 | P0 | Routing |
| FR-BUS-003 | 사용자 도착시각 이전 차량 제외 | P0 | Routing |
| FR-BUS-004 | 공식 ETA 우선, 자체 ETA fallback | P0 | Routing |
| FR-BUS-005 | 목표 정류장 no-seat·low-seat 확률 | P0 | Routing |
| FR-BUS-006 | boardability가 실제 outcome인지 proxy인지 명시 | P0 | Routing |
| FR-BUS-007 | 후보 차량 여러 대 기반 expected·P90 wait | P0 | Routing |
| FR-BUS-008 | 좌석형과 일반형 혼잡 정책 분리 | P0 | Routing |
| FR-BUS-009 | freshness·coverage·model version 제공 | P0 | Routing |
| FR-BUS-010 | missing label을 negative로 사용하지 않음 | P0 | Routing |

### 7.4 최적화와 추천

| ID | 요구사항 | 우선순위 | 소유 |
|---|---|---:|---|
| FR-OPT-001 | P50·P90·taxi upper·walk·transfer risk 계산 | P0 | Routing |
| FR-OPT-002 | 지배 후보 제거와 Pareto Frontier | P0 | Routing |
| FR-OPT-003 | FASTEST 반환 | P0 | Routing |
| FR-OPT-004 | STABLE 반환 | P0 | Routing |
| FR-OPT-005 | EFFICIENT 반환 | P0 | Routing |
| FR-OPT-006 | PUBLIC_TRANSIT_ONLY 반환 | P0 | Routing |
| FR-OPT-007 | 동일 경로 중복 제거 | P0 | Routing |
| FR-OPT-008 | 구조화된 reason·warning 생성 | P0 | Routing |

### 7.5 사용자 결과

| ID | 요구사항 | 우선순위 | 소유 |
|---|---|---:|---|
| FR-UI-001 | 네 추천 카드와 baseline 비교 | P0 | Service |
| FR-UI-002 | P50·P90·도착 범위 | P0 | Service |
| FR-UI-003 | taxi expected·lower·upper와 strict 상태 | P0 | Service |
| FR-UI-004 | mode별 leg와 지도 geometry | P0 | Service |
| FR-UI-005 | 버스 후보 ETA·좌석·expected wait | P0 | Service |
| FR-UI-006 | provenance·freshness·confidence | P0 | Service |
| FR-UI-007 | COMPLETE·PARTIAL·unsupported·expired 상태 | P0 | Service |
| FR-UI-008 | 추천 이유와 주요 warning | P0 | Service |
| FR-UI-009 | 지원 지역·기능 capability 표시 | P0 | Service |

### 7.5.1 따릉이 보조 옵션

| ID | 요구사항 | 우선순위 | 소유 |
|---|---|---:|---|
| FR-BIKE-001 | 서울시 공식 스냅샷에서 좌표 반경 5km 이내 출발지·목적지 인근 따릉이 대여소 위치 제공 | P1 | Service |
| FR-BIKE-002 | 가장 가까운 서로 다른 두 대여소 사이 직선거리와 일반 자전거 시속 15km 기준 예상시간 계산 | P1 | Service |
| FR-BIKE-003 | 따릉이 옵션을 기존 경로 순위와 분리하고 직선거리 계산·실시간 수량 미제공을 명시 | P1 | Service |

### 7.6 계정과 개인정보

| ID | 요구사항 | 우선순위 | 소유 |
|---|---|---:|---|
| FR-IAM-001 | 비회원 즉시 검색 | P0 | Service |
| FR-IAM-002 | 선택적 로그인 | P1 | Service |
| FR-IAM-003 | 검색 기록·저장 장소·즐겨찾기 | P1 | Service |
| FR-IAM-004 | 이동 선호 설정 | P1 | Service |
| FR-IAM-005 | 검색 기록·장소·계정 삭제 | P0/GA | Service |
| FR-IAM-006 | 사용자 데이터 export | P1/GA | Service |
| FR-IAM-007 | 위치·피드백 동의 기록 | P0/GA | Service |

Service 계정·개인정보 계약은 다음을 만족한다.

- V1 선택 로그인은 이메일과 12자 이상의 비밀번호로 가입·로그인하며, 비밀번호 원문은 저장·로그·응답하지 않고 적응형 단방향 hash만 저장한다. 로그인 실패는 계정 존재 여부를 구분하지 않는 동일 오류를 반환한다.
- 가입은 2~20자의 표시 닉네임과 현재 개인정보 처리·데이터 권리 문서의 필수 확인을 요구한다. 검색 기록, 정확한 저장 장소, 제품 분석, 경로 의견의 선택 동의는 각각 독립적이고 기본 거절이며 가입 후 변경할 수 있다.
- guest credential은 짧은 수명의 opaque 값으로 발급하고 서버에는 hash만 저장한다.
- `saveToHistory=true`는 로그인 사용자와 유효한 `SEARCH_HISTORY` 동의를 요구한다. guest 검색 결과는 응답·idempotency TTL 동안만 보유하고 이력 목록에 넣지 않는다.
- preference GET은 version ETag를 반환하며, first-party update는 `If-Match`로 충돌을 검출한다. 1.0 consumer의 무조건 PUT은 migration window 동안만 허용한다.
- saved place와 favorite journey의 update/delete는 owner 검증과 soft delete를 적용한다.
- 임의 장소 두 곳으로 즐겨찾기를 만드는 작업은 두 saved place, favorite journey, digest-only idempotency receipt를 하나의 Service DB transaction으로 생성한다. 부분 성공은 허용하지 않는다. 동일 owner·key·body는 24시간 동안 재시작이나 Redis 장애 뒤에도 같은 불변 ID receipt를 반환한다. 첫 생성만 현재 `PRECISE_LOCATION` 동의와 write quota를 소비하고, receipt replay는 새 위치 write가 아니므로 이를 다시 요구하지 않는다.
- 즐겨찾기의 검색 조건은 canonical taxi budget·Public 검색 preference·추천 종류만 버전과 함께 저장한다. 출발시각은 클릭 시점에 timezone-aware `DEPART_AT`으로 생성하고, `saveToHistory`는 저장하지 않고 현재 `SEARCH_HISTORY` 동의로 판단한다.
- 검색 기록 응답의 선택적 request summary는 표시명·출발시각·예산·preference만 포함하며 좌표·주소·Provider ID가 없어 재검색 입력으로 사용할 수 없다.
- export와 deletion은 비동기 job이며 owner만 상태를 조회한다. export download URL은 짧은 수명이고 계정 삭제는 관련 위치·장소·검색·동의·feedback의 retention/backup 삭제 정책까지 추적한다.

### 7.7 운영

| ID | 요구사항 | 우선순위 | 소유 |
|---|---|---:|---|
| FR-OPS-001 | Provider capability와 상태 추적 | P0 | Routing |
| FR-OPS-002 | 수집 checkpoint·DLQ·품질 검사 | P0 | Routing |
| FR-OPS-003 | Model Registry·shadow·canary·rollback | P0/GA | Routing |
| FR-OPS-004 | Public·Routing health·version endpoint | P0 | Shared |
| FR-OPS-005 | 검색당 Provider 호출 수와 비용 추적 | P0/GA | Shared |
| FR-OPS-006 | 계약·모델·ranking 버전으로 deterministic replay | P0 | Routing |

## 8. 비즈니스 규칙

| ID | 규칙 |
|---|---|
| BR-001 | 총 taxi upper cost가 strict budget을 초과하면 후보를 제거한다. |
| BR-002 | `P90 >= P50`이어야 한다. |
| BR-003 | 데이터 없음·미지원·오래됨을 위험 0으로 표현하지 않는다. |
| BR-004 | 일반형 버스 crowded는 기본적으로 승차 실패 대기 penalty가 아니다. |
| BR-005 | mapping LOW이면 Bus Intelligence를 적용하지 않는다. |
| BR-006 | 택시 예상비는 확정 결제액이 아니다. |
| BR-007 | boardability proxy는 승차 보장이 아니다. |
| BR-008 | explain text는 reason/warning code와 수치에서 만들어야 한다. |
| BR-009 | Service Backend는 Routing 결과의 시간·비용·순위를 재계산하지 않는다. |
| BR-010 | Routing Server는 user ID·email·saved place label을 받지 않는다. |

### 8.1 Public Service → Private Routing 변환 정책

| Public 입력/출력 | Service 정책 |
|---|---|
| `departure.type=DEPART_AT` | `departure.time`을 Private `departureTime`으로 그대로 전달한다. timezone-aware 값만 허용한다. |
| `departure.type=ARRIVE_BY` | Private 1.x가 해당 검색 유형을 표현하지 못하므로 `400 ARRIVE_BY_UNSUPPORTED`를 반환한다. 추정 출발시각으로 바꾸지 않는다. |
| `arrivalDeadline` | 값이 있으면 그대로 전달하며 Service가 출발시각을 역산하지 않는다. |
| `preferences.allowedModes` | 명시값을 Private `constraints.allowedModes`로 그대로 전달한다. 생략 시 canonical mode 전체를 사용하며 Service는 후보를 생성·제거하지 않는다. |
| `avoidHighBusSeatRisk` | Private `preference.avoidHighBusSeatRisk`로 그대로 전달한다. Bus Intelligence 지원·순위 영향은 Routing 책임이다. |
| `saveToHistory` | Service-local 저장·동의 정책에만 사용하고 Routing으로 전달하지 않는다. |
| Private recommendation IDs | 동일 `routeId`를 가진 Private route를 public card로 projection한다. ID가 없거나 일치하지 않으면 `null`과 explicit warning/status를 유지한다. |
| `baseline` | Private `publicTransitOnly` recommendation ID가 가리키는 route를 그대로 사용한다. Service가 baseline을 선택하거나 재계산하지 않는다. |
| `support` | Routing capabilities의 동일 필드를 축약 projection한다. `busIntelligenceCoverage`가 없으면 `UNKNOWN`; Service가 상향 추정하지 않는다. |

## 9. Canonical 상태

```text
RouteSearchStatus: VALIDATING, SEARCHING, COMPLETE, PARTIAL,
                   NO_FEASIBLE_ROUTE, PROVIDER_UNAVAILABLE, EXPIRED

DataOrigin: OBSERVED, PROVIDER_ESTIMATE, MODEL_PREDICTED,
            HISTORICAL_PROXY, USER_INPUT, UNKNOWN

ConfidenceGrade: HIGH, MEDIUM, LOW, UNKNOWN
```

상세 enum은 `src/contracts/codes/reason-warning-error-codes.yaml`과 OpenAPI를 따른다.

## 10. 데이터 요구사항

- 좌표: WGS84, `lon`·`lat`
- 시간: ISO 8601 timezone offset 필수
- 기간: integer seconds
- 거리: integer meters
- 금액: integer KRW
- 확률: 0.0~1.0
- 외부 ID와 canonical ID를 분리
- observation에 observed·ingested time, source, schema version, quality flag 저장
- 사용자 데이터와 교통·모델 데이터 분리
- Provider 약관상 저장 불가 데이터는 raw 저장 금지

## 11. 모델 요구사항

### ETA

- official provider ETA가 유효하면 우선 사용
- 자체 LightGBM regression baseline과 quantile/conformal interval
- 시간·trip group 기반 분할
- MAE, Median AE, P90 AE, interval coverage

### Seat Risk

- target stop에서 `P(remainSeat=0)`, `P(remainSeat<=2)`, 필요 시 `<=5`
- future observation 결측은 `NULL`
- PR-AUC, Brier, ECE, calibration diagram
- route·direction·time·station sequence slice

### Expected Wait

- 여러 후보 차량 ETA와 boardability proxy 결합
- tail probability는 historical headway로 보수 처리
- 경로 ranking reversal 사례로 제품 가치 검증

## 12. 외부 Provider

| 영역 | Primary | Fallback·보조 |
|---|---|---|
| 장소·주소 | Kakao Local | 추가 geocoder 검토 |
| 현재 대중교통 | Kakao Maps Public Transit | TMAP·ODsay adapter |
| 도보 | Kakao Maps Walk | transit 내부 walk·보수 fallback |
| 현재 택시 | Kakao Mobility Directions | provider adapter 교체 가능 |
| taxi matrix | Kakao multi-destination/origin | bounded single directions |
| 경기버스 | GBIS v2 | 최근 snapshot·historical |
| 도로 context | GITS | Kakao driving traffic·historical |
| 날씨 | KMA | recent valid snapshot |
| 공휴일 | KASI | 내부 calendar |

실제 키 검증 전 기능은 `DOCUMENTED`, `KEY_VERIFIED`, `PRODUCTION_APPROVED`를 구분한다.

## 13. 비기능 요구 요약

- Public route search availability 월 99.9% 제안
- 정상 검색 P50 3.5초, P95 7초
- 필수 Provider 정상 시 Internal Routing API 오류 0.5% 미만 제안
- strict budget 검증 가능한 응답에서 위반 0건 목표
- HIGH mapping precision 99.5% 권고 gate
- model artifact rollback 15분 이내
- 일부 Provider 장애 시 `PARTIAL`
- 정확한 좌표·번호판·API key를 일반 로그에 남기지 않음

세부사항은 `NON_FUNCTIONAL_REQUIREMENTS.md`, `SECURITY_PRIVACY.md`를 따른다.

## 14. 분석과 피드백

수집 가능한 사용자 지표:

- 추천 유형 선택
- 검색→상세→즐겨찾기 전환
- actual duration·taxi cost·bus outcome에 대한 선택적 feedback
- 예측 vs actual 오차
- 사용자 이탈 원인과 warning

정확한 위치와 민감 label은 분석 dataset에서 축약·비식별한다.

## 15. 단계와 출시 조건

| 단계 | 목적 | Exit |
|---|---|---|
| Foundation | 두 하네스, contracts, mock E2E | contract·src layout 검증 통과 |
| Internal Alpha | 실제 Provider와 baseline route | 대표 네 방향에서 유효 결과 |
| Model Alpha | ETA·Seat 분리와 replay | offline·latency gate |
| Closed Beta | 전체 UX·계정·운영 | P95·예산·경로 유효성 |
| GA | 보안·복구·약관·비용 | `RELEASE_GATES.md` 전부 통과 |
| V2 | 실시간 재추천·개인화 | 별도 위치 동의·remaining journey 검증 |

## 16. 대표 검증 경로

1. 명지대학교 자연캠퍼스 → 판교
2. 판교 → 명지대학교 자연캠퍼스
3. 광교 → 판교
4. 판교 → 광교

각 경로를 평일 첨두·비첨두·주말·강수·막차 근접 시간과 0·5천·1만·2만·3만 원 예산으로 평가한다.

## 17. 제품 수용 기준

- 네 추천 유형이 계약에 맞게 반환된다.
- strict budget 위반이 없다.
- 좌석 위험이 경로 순위를 바꾸는 검증 사례가 있다.
- 선탑승 정류장 후보가 실제 총시간을 줄이는 사례가 있다.
- 데이터 미지원과 낮은 위험이 구분된다.
- API 일부 장애가 전체 500으로 전파되지 않는다.
- 사용자 위치·저장 장소의 삭제와 보존 정책이 동작한다.
- 두 하네스가 같은 OpenAPI·ERD·enum·context hash를 사용한다.
