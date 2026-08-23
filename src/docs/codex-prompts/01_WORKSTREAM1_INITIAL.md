# 01. 1번 Service Product 최초 구현

**사용 시점:** 개발자 1이 처음 구현을 시작할 때

```text
$service-product-orchestrator

Service Product 작업흐름의 초기 구현을 시작해줘. 1번 담당 범위만 구현한다.

- repository/contract 검증과 service-product context snapshot을 실행하라.
- AGENTS.md, shared PRD, Public/Private OpenAPI, Service DBML, Service workstream 문서를 읽어라.
- WORKPLAN.md를 실제 vertical slice로 작성하라.
- 필요한 custom subagents에 독립 작업을 위임하라: service-product-lead, service-ux-engineer, service-frontend-engineer, service-backend-engineer, service-data-engineer, service-security-engineer, service-qa-engineer.
- 먼저 canonical Stub/Replay RoutingGateway로 Frontend→Service→Mock Routing 흐름을 만든다.
- React Web/PWA, 장소검색, 조건, 대표 네 결과, 지도/상세, COMPLETE/PARTIAL/NO_FEASIBLE/ERROR 상태를 구현한다.
- Django Service에 인증/guest/place proxy/search/RoutingGateway/history/favorites/preferences/feedback을 구현한다.
- Service가 GBIS, Mobility, 모델, ranking을 직접 다루지 않게 한다.
- Public API/generated client/UI/DB migration contract test를 작성한다.
- 정확 위치·토큰·키 로그를 검증한다.
- 계약에 없는 필드는 임의 추가하지 말고 change request로 BLOCKED 처리한다.
- 테스트와 전체 validation 후 STATUS/HANDOFF를 갱신한다.

Routing 소유 경로는 수정하지 마라. 최종 보고: 변경 파일, 완료 requirements, tests, mock/real 상태, 계약 영향, 보안/privacy, blockers, 다음 지시.
```
