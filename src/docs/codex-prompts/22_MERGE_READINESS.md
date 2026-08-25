# 22. PR/브랜치 병합 준비

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** 실제 Git 병합 직전

```text
$integration-coherence-qa

다음 브랜치/PR이 병합 가능한지 검토해줘: [브랜치/PR]. 먼저 수정하지 마라.

- 소유 경로 위반
- unapproved shared changes
- contract lock/context parity
- generated client drift
- DB migration/rollback
- producer/consumer tests
- deterministic replay
- strict budget/time invariants
- security/privacy
- P95/quota/cost
- WORKPLAN/HANDOFF completeness
- unresolved FAIL/UNVERIFIED

판정: READY, READY_WITH_ACCEPTED_RISK, NOT_READY. 필요한 선행 commit과 병합 순서를 제시하라.
```
