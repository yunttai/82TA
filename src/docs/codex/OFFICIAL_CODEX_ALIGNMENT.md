# Codex 공식 구조 정렬

이 하네스는 다음 Codex 프로젝트 구조를 따른다.

- `AGENTS.md`: 프로젝트 범위 지시. 루트에서 현재 작업 디렉터리까지 계층적으로 적용한다.
- `.agents/skills/<name>/SKILL.md`: 저장소 범위 재사용 스킬. `name`, `description` frontmatter를 갖고 `$skill-name`으로 명시 호출한다.
- `.codex/agents/*.toml`: 저장소 범위 custom agent. `name`, `description`, `developer_instructions`를 사용한다.
- `.codex/config.toml`: 프로젝트 subagent 설정.
- Primary thread: 작업계획, delegation, wait, conflict resolution, final consolidation.
- `/agent`: interactive session에서 subagent 확인/전환.

공식 참고:

- AGENTS.md: https://developers.openai.com/codex/guides/agents-md/
- Skills: https://developers.openai.com/codex/skills/
- Subagents/custom agents: https://developers.openai.com/codex/subagents/
