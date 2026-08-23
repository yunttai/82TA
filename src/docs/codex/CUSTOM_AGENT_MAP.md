# Codex Custom Agent Map

## Service Product

| Agent | 역할 | 주 소유 |
|---|---|---|
| service-product-lead | 계획·의존성·통합 | Service 전체 |
| service-ux-engineer | 상태·정보구조·접근성 | UI spec |
| service-frontend-engineer | React/PWA/Kakao Map | `src/apps/web` |
| service-backend-engineer | Django Public API/RoutingGateway | `src/services/service-api` |
| service-data-engineer | Service DB·보존·삭제 | Service models/migrations |
| service-security-engineer | auth/privacy/abuse | Service security |
| service-qa-engineer | API↔UI↔DB QA | Service/cross tests |

## Routing & Intelligence

| Agent | 역할 | 주 소유 |
|---|---|---|
| routing-technical-lead | dependency/deadline/fan-in | Routing 전체 |
| provider-integration-engineer | Adapter/cache/resilience | provider-core |
| transport-mapping-engineer | route/stop/direction | mapping |
| route-optimization-engineer | candidate/time/budget/Pareto | routing-domain |
| bus-intelligence-engineer | ETA/seat/wait | bus-intelligence-core |
| routing-data-ml-engineer | collector/dataset/registry | workers/model |
| routing-security-performance-engineer | private auth/SSRF/quota/SLO | Routing/platform |
| routing-qa-engineer | Adapter→API QA | Routing tests |

## Shared

| Agent | 역할 |
|---|---|
| contract-steward | OpenAPI/DBML/events/codes/version |
| architecture-auditor | bounded context, ownership, src-only, integration |
| integration-qa | producer-consumer, replay, merge/release gate |

## 위임 원칙

- Primary thread가 plan과 최종 diff를 소유한다.
- 독립 작업만 병렬 위임한다.
- 같은 파일을 두 subagent에 동시에 쓰게 하지 않는다.
- subagent는 배정 경로와 acceptance/test를 받는다.
- 결과를 기다린 뒤 primary thread가 conflict를 해결한다.
- 대화가 아니라 WORKPLAN/STATUS/HANDOFF에 durable state를 남긴다.
