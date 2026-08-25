# Codex 프롬프트 인덱스

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

아래 파일은 과거 흐름을 추적할 때만 참고한다. 새 작업에 코드블록을 그대로 붙여넣지 말고, 현재 `AGENTS.md`와 관련 skill에 따라 요청한 slice만 최소 범위로 수행한다.

| 번호 | 프롬프트 | 사용 시점 |
|---:|---|---|
| 00 | [저장소 최초 점검](00_REPOSITORY_ORIENTATION.md) | Codex에서 저장소를 처음 열었을 때 |
| 01 | [1번 Service Product 최초 구현](01_WORKSTREAM1_INITIAL.md) | 개발자 1이 처음 구현을 시작할 때 |
| 02 | [1번 작업 이어서 진행](02_WORKSTREAM1_CONTINUE.md) | 이전 Service 세션 다음 작업 |
| 03 | [1번 특정 기능 추가](03_WORKSTREAM1_FEATURE.md) | Service UI/API 기능 추가 |
| 04 | [1번 버그 수정](04_WORKSTREAM1_BUGFIX.md) | React/Django Service 결함 |
| 05 | [1번 단독 QA](05_WORKSTREAM1_QA.md) | 2번과 합치기 전 Service 검증 |
| 06 | [2번 Routing & Intelligence 최초 구현](06_WORKSTREAM2_INITIAL.md) | 개발자 2가 처음 구현을 시작할 때 |
| 07 | [2번 작업 이어서 진행](07_WORKSTREAM2_CONTINUE.md) | 이전 Routing 세션 다음 작업 |
| 08 | [외부 Provider 연동](08_PROVIDER_INTEGRATION.md) | 신규 API/응답 변경/키 검증 |
| 09 | [Kakao↔GBIS 매핑](09_TRANSPORT_MAPPING.md) | 노선/정류장/방향 매핑 |
| 10 | [Bus Intelligence/ETA 개발](10_BUS_INTELLIGENCE_ETA.md) | ETA/Seat/Boardability/Wait |
| 11 | [경로 최적화 알고리즘 개발](11_ROUTE_OPTIMIZER.md) | candidate/time/budget/Pareto |
| 12 | [2번 단독 QA](12_WORKSTREAM2_QA.md) | Service와 합치기 전 Routing 검증 |
| 13 | [공통 계약 변경안만 작성](13_CONTRACT_CHANGE_PROPOSAL.md) | 아직 구현 승인 전 |
| 14 | [승인된 계약 변경 적용](14_APPLY_APPROVED_CONTRACT_CHANGE.md) | 13번 승인 후 |
| 15 | [DB 스키마/Migration 변경](15_DATABASE_SCHEMA_CHANGE.md) | Service 또는 Routing DB 변경 |
| 16 | [Reason/Warning/Error 코드 변경](16_CODE_REGISTRY_CHANGE.md) | 사용자 설명/오류 코드 변경 |
| 17 | [두 작업흐름 Context 동기화](17_CONTEXT_SYNC.md) | 따로 작업한 후 통합 전 |
| 18 | [1번→2번 인수인계](18_HANDOFF_SERVICE_TO_ROUTING.md) | Service 요구를 Routing에 전달 |
| 19 | [2번→1번 인수인계](19_HANDOFF_ROUTING_TO_SERVICE.md) | 실제 Routing을 Service에 연결 전 |
| 20 | [1번·2번 최초 통합](20_FIRST_INTEGRATION.md) | 두 작업흐름을 처음 실제 연결 |
| 21 | [이후 반복 통합](21_REGULAR_INTEGRATION.md) | 기능 slice를 주기적으로 합칠 때 |
| 22 | [PR/브랜치 병합 준비](22_MERGE_READINESS.md) | 실제 Git 병합 직전 |
| 23 | [통합 충돌 해결](23_INTEGRATION_CONFLICT_RESOLUTION.md) | 두 작업흐름이 다르게 수정했을 때 |
| 24 | [보안·개인정보 리뷰](24_SECURITY_REVIEW.md) | 큰 기능/통합/릴리스 전 |
| 25 | [성능·SLO 최적화](25_PERFORMANCE_SLO.md) | P95 7초/비용 문제 |
| 26 | [기존 3주 데이터 감사](26_DATA_AUDIT.md) | DB/통계를 제공받았을 때 |
| 27 | [모델 재학습·승격](27_MODEL_RETRAIN.md) | 데이터 감사 후 |
| 28 | [Provider 장애 대응](28_PROVIDER_OUTAGE.md) | 실제 장애/쿼터 소진 |
| 29 | [판매 가능한 Release Gate](29_RELEASE_GATE.md) | Closed Beta/GA 직전 |
| 30 | [배포·모델·계약 롤백](30_ROLLBACK.md) | 통합/배포 후 문제 |
| 31 | [전체 프로젝트 현황 감사](31_FULL_STATUS_AUDIT.md) | 오랜 작업 후 현황 확인 |
| 32 | [새 Codex 세션에서 이어하기](32_SESSION_RESUME.md) | 대화 컨텍스트가 끊겼을 때 |
| 33 | [V2 실시간 재추천 시작](33_V2_REALTIME_REROUTING.md) | Release 1 이후 |
| 34 | [두 사람 Branch/Worktree 준비](34_BRANCH_WORKTREE_SETUP.md) | 실제 동시 개발 전 |
| 35 | [Codex 하네스만 수정](35_HARNESS_ONLY_CHANGE.md) | AGENTS/skills/agents/prompts 변경 |
