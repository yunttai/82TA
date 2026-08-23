# 22. PR/브랜치 병합 준비

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
