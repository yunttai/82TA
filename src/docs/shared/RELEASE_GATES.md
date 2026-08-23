# Release Gates

## Foundation

- [ ] 두 오케스트레이터와 agent/skill 구조 검증
- [ ] 모든 제품 산출물 `src/` 아래
- [ ] common contracts와 lock 검증
- [ ] React→Service→Mock Routing E2E
- [ ] 두 서비스 독립 build/test

## Provider Alpha

- [ ] Kakao Transit/Walk 실제 key 검증
- [ ] Kakao Directions fare/duration/traffic 검증
- [ ] multi-destination/origin/future capability 기록
- [ ] GBIS 주요 endpoint fixture
- [ ] timeout/retry/circuit/cache
- [ ] schema drift fixture

## Routing Alpha

- [ ] TRANSIT_ONLY, TAXI_TRANSIT, TRANSIT_TAXI, TAXI_ONLY
- [ ] strict budget invariant 100%
- [ ] bounded candidate generation
- [ ] Pareto invariant
- [ ] partial degradation
- [ ] 대표 네 방향 결과
- [ ] P95 7초 측정

## Bus Intelligence

### Go

- [ ] HIGH mapping precision gold set
- [ ] target stop·user arrival 기준
- [ ] missing target NULL
- [ ] temporal/trip split
- [ ] ETA interval·seat calibration
- [ ] boardability proxy 표시
- [ ] fallback·stale·coverage
- [ ] ranking reversal replay

### No-Go

- route number only mapping
- random row split metric만 존재
- missing target을 0으로 학습
- artifact provenance/hash 없음
- unsupported route에 임의 확률

## Closed Beta

- [ ] 회원·비회원·기록·즐겨찾기·설정·삭제
- [ ] 지도·partial·unsupported UX
- [ ] API↔client↔UI coherence
- [ ] security test
- [ ] field test
- [ ] provider/model/mapping dashboard

## GA

- [ ] availability 99.9% 목표
- [ ] P95 7초, P99 10초 또는 explicit partial
- [ ] strict budget 현장 위반 0건 목표
- [ ] HIGH mapping precision 99.5% 권고
- [ ] model rollback 15분 이내
- [ ] RDS restore drill
- [ ] WAF·rate limit·secret rotation·audit
- [ ] 사용자 데이터 삭제·export
- [ ] Provider production approval·비용 계획
- [ ] 개인정보·위치정보·약관 검토
- [ ] 장애 runbook·지원 범위 공개
