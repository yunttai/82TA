# Harness Tests

`revfactory/harness` 방식의 agent/skill/orchestrator 구조를 Codex-native control files로 정적·드라이런 검증한다.

검증 대상:

- root/nested AGENTS.md
- `.codex/config.toml` and custom agents
- `.agents/skills` frontmatter and trigger evals
- two workstream ledgers
- contract lock/context parity
- Codex primary-thread delegation lifecycle
- source-layout policy

실제 Codex interactive environment에서는 `/agent`로 subagent 실행 상태와 handoff를 추가 확인한다.
