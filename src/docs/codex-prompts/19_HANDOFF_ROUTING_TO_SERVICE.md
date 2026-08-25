# 19. 2번→1번 인수인계

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** 실제 Routing을 Service에 연결 전

```text
Routing & Intelligence 결과를 Service Product에 인수인계할 수 있게 정리해줘. 제품 코드는 수정하지 마라.

- Routing WORKPLAN/STATUS/diff/replay/capability/model state를 읽는다.
- Private API 구현 상태와 canonical examples parity를 작성한다.
- COMPLETE/PARTIAL/no-route/error, nullable recommendation, warnings, freshness, model/mapping coverage를 명시한다.
- 실제 Provider 검증 여부와 fixture-only 상태를 구분한다.
- 생성 client와 integration prerequisites를 목록화한다.
- _workspace/routing-intelligence/HANDOFF.md를 갱신한다.
```
