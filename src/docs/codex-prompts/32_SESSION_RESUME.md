# 32. 새 Codex 세션에서 이어하기

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** 대화 컨텍스트가 끊겼을 때

```text
이 저장소의 이전 대화를 기억한다고 가정하지 말고 파일을 기준으로 작업을 재개해줘.

작업흐름: [service-product / routing-intelligence / integration]
목표: [이번 세션 목표]

1. 루트/하위 AGENTS.md를 읽는다.
2. repository/lock을 검증한다.
3. 해당 WORKPLAN/STATUS/HANDOFF, context snapshot, branch diff를 읽는다.
4. shared PRD와 관련 계약만 로드한다.
5. DONE을 재작성하지 않고 다음 실행 가능한 task를 선택한다.
6. 필요한 custom subagents만 위임한다.
7. 완료 후 ledgers와 validation을 갱신한다.

먼저 재개 계획과 가정/차단을 짧게 보고한 뒤 실행하라.
```
