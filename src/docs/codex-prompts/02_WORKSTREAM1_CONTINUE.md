# 02. 1번 작업 이어서 진행

**사용 시점:** 이전 Service 세션 다음 작업

```text
$service-product-orchestrator

이전 Service Product 작업을 이어서 진행해줘.

1. WORKPLAN/STATUS/HANDOFF, 최신 context snapshot, branch diff를 읽어라.
2. DONE을 재작성하지 말고 dependency가 해소된 PENDING/BLOCKED/UNVERIFIED부터 선택하라.
3. context hash가 다르면 구현을 중단하고 drift를 보고하라.
4. 독립 작업만 필요한 Service custom subagents에 위임하고 primary thread가 모두 기다린 뒤 통합하라.
5. Routing 미완료는 canonical Stub/Replay로 유지하고 실연동 완료라고 표현하지 마라.
6. component→contract→integration 순서로 검증하고 STATUS/HANDOFF를 갱신하라.
7. 관련 없는 파일은 수정하지 마라.

선택 task, dependency, 완료 evidence, 새 계약 요구, 다음 최우선 task를 보고하라.
```
