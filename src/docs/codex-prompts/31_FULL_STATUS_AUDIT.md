# 31. 전체 프로젝트 현황 감사

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** 오랜 작업 후 현황 확인

```text
저장소를 수정하지 말고 전체 프로젝트 현황을 감사해줘.

- AGENTS/config/agents/skills/prompts/ledgers
- repository/lock/context parity
- Service/Routing 구현률과 tests
- OpenAPI/DBML/generated drift
- Provider capability
- data/mapping/model coverage
- R1~R4/replay
- performance/security/GCE/release
- TODO/BLOCKED/UNVERIFIED/dead code

PRD requirement별 DONE/PARTIAL/NOT_STARTED/UNVERIFIED 표와 두 담당자별 다음 작업, 통합 순서, 가장 큰 위험 10개를 제시하라. 코드 수정 금지.
```
