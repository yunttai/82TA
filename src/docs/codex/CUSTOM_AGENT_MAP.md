# Codex Custom Agent Map

Custom agent는 필요할 때 선택하는 전문 역할이며 상시 path owner가 아니다. 실제 수정 범위는 primary task가 비중복 write scope로 정한다.

## Service Product

| Agent | 전문 영역 |
|---|---|
| service-product-lead | 큰 Service slice의 계획·의존성·통합 |
| service-ux-engineer | 상태·정보구조·접근성 |
| service-frontend-engineer | React/PWA/Kakao Map |
| service-backend-engineer | Django Public API/RoutingGateway |
| service-data-engineer | Service DB·보존·삭제 |
| service-security-engineer | auth/privacy/abuse |
| service-qa-engineer | 변경된 API↔UI↔DB 경계 QA |

## Routing & Intelligence

| Agent | 전문 영역 |
|---|---|
| routing-technical-lead | 큰 Routing slice의 dependency/deadline/fan-in |
| provider-integration-engineer | Adapter/cache/resilience |
| transport-mapping-engineer | route/stop/direction mapping |
| route-optimization-engineer | candidate/time/budget/Pareto |
| bus-intelligence-engineer | ETA/seat/wait |
| routing-data-ml-engineer | collector/dataset/model registry |
| routing-security-performance-engineer | private auth/SSRF/quota/SLO |
| routing-qa-engineer | 변경된 Adapter→API 경계 QA |

## Shared

| Agent | 전문 영역 |
|---|---|
| contract-steward | 실제 영향받는 shared contract와 compatibility |
| architecture-auditor | bounded context, DB ownership, current↔target gap |
| integration-qa | producer-consumer와 release-dependent evidence |

## 위임 원칙

- local task는 primary가 직접 수행해도 된다.
- 위임은 사용자가 요청했거나 독립 작업의 병렬화가 실질적으로 유리할 때만 하며, focused task는 최대 한 implementer와 한 reviewer를 사용한다.
- profile의 path 목록은 expertise hint다.
- 각 delegated task에는 명시적 write scope와 acceptance/check를 준다.
- 같은 파일이나 넓은 glob을 여러 agent에 동시에 배정하지 않는다.
- 결과 통합과 conflict resolution은 primary가 담당한다.
- durable ledger는 선택 사항이며 current source와 git diff를 대체하지 않는다.
- 구현 요청에 audit/governance/integration/security/release agent를 자동으로 붙이지 않고, ordinary implementation에 release verdict를 만들지 않는다.
