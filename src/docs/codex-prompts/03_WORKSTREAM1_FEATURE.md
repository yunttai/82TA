# 03. 1번 특정 기능 추가

**사용 시점:** Service UI/API 기능 추가

```text
$service-product-orchestrator

Service Product에 다음 기능을 추가해줘.

기능: [기능명/사용자 요구]

- Service 소유 경로만 수정한다.
- 사용자 스토리, 상태 전이, Public API/DB/privacy 영향을 먼저 분석한다.
- Routing 의미나 ranking을 Service에서 바꾸지 않는다.
- 공통 계약이 필요하면 먼저 change request를 작성하고 구현을 멈춘다.
- 필요한 UX/Frontend/Backend/Data/Security/QA custom subagents만 위임한다.
- loading/empty/partial/error/unsupported/accessibility를 포함한다.
- unit/contract/E2E와 repository validation을 통과한다.
- WORKPLAN/STATUS/HANDOFF를 갱신한다.

최종 보고: 요구→구현 파일→tests→계약 영향→미해결.
```
