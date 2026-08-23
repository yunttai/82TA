# Orchestrator Dry Runs

## DR-SVC-001 정상 vertical slice

입력: `명지대→판교 경로 검색 결과 화면과 Service API 구현`

예상:

1. Service context snapshot 생성
2. PRD `FR-PLACE`, `FR-UI`, Public/Private contract 연결
3. lead·UX·Frontend·Backend·QA 팀
4. Stub/Replay RoutingGateway로 병렬 구현
5. producer/consumer incremental QA
6. real Routing은 available하면 integration, 아니면 UNVERIFIED
7. 최종 산출물은 `src/apps/web`, `src/services/service-api`, `src/tests`

금지:

- Service가 GBIS를 직접 호출
- Frontend가 private Routing API를 호출
- 새 common field를 수작업으로 추가

## DR-SVC-002 부분 재실행

입력: `PARTIAL 결과 카드만 보완`

예상: 기존 snapshot hash 확인, UX+Frontend+QA만 구성, 다른 Service 모듈과 Routing은 변경하지 않는다.

## DR-RT-001 정상 Routing slice

입력: `명지대→판교 taxi-transit 후보와 Bus Intelligence 구현`

예상:

1. Routing snapshot
2. provider/mapping 팀
3. intelligence/optimization 팀 재구성
4. private API/performance 팀
5. deterministic replay와 Service generated client 검증
6. 모든 코드·모델 metadata·test는 `src/`

## DR-RT-002 Provider 오류

Kakao multi-destination 미검증 → capability false, bounded single-direction fallback, 정상 지원처럼 표시하지 않는다.

## DR-INT-001 계약 drift

Service snapshot과 Routing snapshot hash 불일치 → merge·E2E 중단, contract change audit, lock 갱신 전 재개 금지.

## DR-LAYOUT-001 루트 위반

Agent가 루트 `frontend/`를 생성 → source-layout-guard FAIL, `src/apps/web/`로 이동하고 모든 참조 갱신.
