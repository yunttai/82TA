# Source Layout Policy

## Root allowlist

- `.codex/` — Codex project config and custom subagents
- `.agents/skills/` — Codex project skills
- `_workspace/` — durable plans, status, handoffs, evidence
- `src/` — every product artifact and executable script
- `AGENTS.md`, `README.md`, `.gitignore`

## `src/` only

Application code, product documentation, PRD, ERD, OpenAPI, DBML, migrations, tests, generated clients, IaC, CI sources, scripts, model jobs and executable helpers must live under `src/`.

## Codex scope instructions

Root and nested `AGENTS.md` files define path-scoped rules. Closer files apply to their subtree. `.codex/agents/*.toml` defines project custom subagents; `.agents/skills/*/SKILL.md` defines reusable workflows.

## Forbidden

- `.claude/` or `CLAUDE.md` as active controls
- executable scripts under `.agents/` or `.codex/`
- duplicated workstream copies of shared machine contracts
- product source outside `src/`

## Validation

```bash
python src/scripts/validate_repository.py
python src/scripts/verify_contract_lock.py
```
