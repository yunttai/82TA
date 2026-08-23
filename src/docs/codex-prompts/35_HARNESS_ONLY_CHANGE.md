# 35. Codex 하네스만 수정

**사용 시점:** AGENTS/skills/agents/prompts 변경

```text
$harness-evolution

제품 코드와 비즈니스 계약을 건드리지 않고 Codex 하네스만 다음과 같이 수정해줘: [변경].

- 변경 전 보호 대상 application/OpenAPI/DBML/PRD/algorithm 파일 SHA-256을 고정한다.
- 허용 범위: AGENTS.md, .codex, .agents, Codex/harness docs, prompt library, _workspace templates, harness validation scripts, context-only metadata.
- custom agent/skill/prompt/registry/eval/validation 일관성을 유지한다.
- active Claude-only controls를 만들지 않는다.
- repository/trigger/context 검증을 실행한다.
- 변경 후 보호 대상 hash를 비교해 preservation report를 작성한다.
- product contractVersion은 비즈니스 의미가 바뀌지 않으면 변경하지 않는다.
```
