# 34. 두 사람 Branch/Worktree 준비

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** 실제 동시 개발 전

```text
현재 Git 상태를 확인하고 두 작업흐름을 안전하게 병렬 개발할 branch/worktree 계획을 작성해줘. 명령은 제시하되 승인 없이 destructive command를 실행하지 마라.

권장 branch: workstream/service-product, workstream/routing-intelligence, integration/current, contract/<name>.

- 기준 commit과 clean status 확인
- worktree 경로/명령
- 공통 계약 commit 반영 순서
- CODEOWNERS/PR review
- generated client 처리
- context snapshot과 handoff
- 최초/반복 integration branch 전략
- conflict/rollback

제품 파일을 수정하지 마라.
```
