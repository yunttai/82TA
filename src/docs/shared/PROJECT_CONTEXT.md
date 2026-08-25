# Project Context — Budget-Constrained Multimodal Route Platform

## 1. 문서 역할

이 문서는 두 개발 하네스가 매 실행 전에 읽는 최소 공통 컨텍스트다. 제품 목표, 용어, 경계, 금지사항을 요약한다. 세부 요구사항은 `PRD.md`, 기계 판독 계약은 `src/contracts/`를 따른다.

## 2. 제품 정의

> 사용자가 허용한 택시 총예산 안에서 택시·버스·지하철·GTX·도보를 조합하고, 실시간 교통과 경기버스 좌석 부족으로 인한 추가 대기까지 반영하여 실제 도착시간이 가장 빠르거나 안정적인 경로를 추천한다.

기술명:

> Budget-Constrained Time-Dependent Multimodal Route Optimizer with Bus Boardability Intelligence

## 3. 초기 범위

| 항목 | 확정값 |
|---|---|
| 지역 | 경기 남부 ↔ 서울. 대표 검증 축은 명지대↔판교, 광교↔판교 |
| 제공 | 경로 추천. 턴바이턴 내비게이션·택시 호출·버스 예약은 제외 |
| 사용자 앱 | React 기반 모바일 우선 웹앱·PWA |
| Public Backend | Django Service Backend |
| Core Backend | Django Routing & Intelligence Server + Django 독립 Python domain |
| 배포 | GCE 필수. 현재 단일 VM + Docker Compose + Nginx |
| 응답 목표 | 정상 검색 P95 7초 이내 |
| 실시간 재추천 | V2 |
| 기존 자산 | `yunttai/BusCrowdRisk-KOR`를 Bus Intelligence 영역으로 재구성 |
| 모델 | ETA와 Seat Risk를 분리하여 초기 제품부터 포함 |

## 4. 사용자 질문

- 택시비를 1만 원까지 사용할 때 어디까지 택시를 타야 가장 빨리 도착하는가?
- 다음 광역버스가 좌석 부족이면 지하철역으로 택시 이동하는 편이 빠른가?
- 가까운 정류장보다 상류 정류장에서 먼저 타는 편이 유리한가?
- 평균은 빠르지만 실패 위험이 큰 경로와 P90이 안정적인 경로 중 무엇을 선택해야 하는가?
- 추가 5천 원이 실제로 몇 분을 줄이는가?

## 5. 네 가지 출력

1. `FASTEST` — strict budget을 만족하는 후보 중 P50 총시간 최소
2. `STABLE` — P90과 실패 위험이 가장 낮은 후보
3. `EFFICIENT` — Pareto Frontier에서 추가 비용 대비 시간 절감 최대
4. `PUBLIC_TRANSIT_ONLY` — 택시비 0인 비교 기준

## 6. 핵심 차별 기능

- 사용자 정류장 도착시각 이후의 후보 차량만 평가
- 목표 정류장 도착 시 좌석 부족·저좌석 확률
- 첫 차량 실패와 다음 차량까지 포함한 기대·P90 대기시간
- 가까운 정류장과 상류 정류장의 택시비·승차 가능성·총시간 비교
- 택시 총액 상한과 시간의 Pareto 최적화
- 관측·외부 추정·자체 예측·과거 proxy를 구분한 provenance

## 7. 두 작업흐름

### Service Product Harness

소유:

- `src/apps/web`
- `src/services/service-api`
- 사용자 계정·설정·장소 검색·검색 기록·즐겨찾기·피드백
- Public API와 사용자 응답 projection

금지:

- GBIS raw JSON 해석
- Kakao Transit↔GBIS 매핑
- 모델 artifact 로드
- 후보 생성·Pareto·ranking
- Provider fallback 순서 결정

### Routing & Intelligence Harness

소유:

- `src/services/routing-api`
- `src/packages/routing-domain`
- `src/packages/bus-intelligence-core`
- `src/packages/provider-core`
- `src/workers/*`
- Provider 연동·매핑·모델·최적화

금지:

- 이메일·이름·전화번호·social ID 수신
- 검색 기록·즐겨찾기 UX 정책
- Frontend 화면용 임의 응답 구조 설계
- Service DB 직접 조회

## 8. 공통 계약 원본

두 하네스가 공동으로 읽고 변경한다.

```text
src/docs/shared/*
src/contracts/openapi/*
src/contracts/database/*
src/contracts/events/*
src/contracts/codes/*
```

각 작업흐름 문서는 공통 내용을 복제하지 않고 링크한다. 계약 변경은 `shared-contract-governance`를 통해 처리한다.

## 9. 절대 제품 규칙

1. 사용자가 정류장에 도착하기 전 지나가는 차량은 후보가 아니다.
2. 좌석형과 일반형 버스의 혼잡 의미를 구분한다.
3. 정보 없음은 위험 0이 아니다.
4. Bus Intelligence가 경로 시간과 순위에 실제 영향을 준다.
5. 택시 주행시간과 배차·탑승 대기시간을 분리한다.
6. 택시비는 모든 택시 leg의 총액과 범위다.
7. strict budget은 `taxiCost.upper <= budget`일 때만 통과한다.
8. 노선·정류장 매핑이 불확실하면 Bus Intelligence를 적용하지 않는다.
9. 실제 승차 outcome이 없으면 `actualBoardingProbability`를 주장하지 않는다.
10. 미래 관측 결측을 음성 label로 만들지 않는다.
11. 확률은 calibration과 coverage를 평가한 뒤 표시한다.
12. 설명은 구조화된 reason/warning code에서 만든다.
13. 두 서비스는 서로의 DB를 직접 조회하지 않는다.
14. 모든 제품 산출물은 `src/` 아래에 둔다.

## 10. 현재 미확정 항목

- Kakao Maps 대중교통·도보 API 실제 키 검증
- Kakao Mobility 다중 목적지·출발지·미래 경로 권한
- 약 3주 데이터의 실제 행 수, 노선·방향·시간대 coverage
- 기존 모델 diagnostics, calibration, label 결측률
- GITS 접근 상태와 bus route↔road link 매핑 가치
- 외부 API의 상용 사용·저장·과금 승인

미확정 항목을 구현 완료처럼 표현하지 않고 capability와 release gate로 관리한다.
