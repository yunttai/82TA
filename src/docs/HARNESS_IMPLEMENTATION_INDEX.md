# Active Harness Implementation Index

## Active controls

- root/scoped instructions: `AGENTS.md`, `src/**/AGENTS.md`
- optional specialist agents: `.codex/agents/*.toml`
- task skills: `.agents/skills/*/SKILL.md`
- project settings: `.codex/config.toml`
- current runbook: `src/docs/codex/CODEX_RUNBOOK.md`
- change history: `src/docs/codex/HARNESS_CHANGELOG.md`

Agent path lists are expertise hints. Actual write scope is assigned by each task.

## Validation

```bash
# active harness
python src/scripts/validate_repository.py --harness-only

# repository layout
python src/scripts/validate_repository.py --layout-only

# full integration/release audit
python src/scripts/validate_repository.py
python src/scripts/compare_context_snapshots.py
```

The parity command compares live verified contract locks. `_workspace` and snapshots are optional diagnostics.

## Shared boundary

- Service and Routing responsibility boundaries remain architectural safety rules.
- Contract changes are impact-based and use one canonical source.
- The locked v1 harness registry is a historical compatibility artifact, not active role/path enforcement.
- Legacy prompt documents under `src/docs/codex-prompts/` are archived recipes, not required input.

Historical design records:

- `src/docs/DUAL_HARNESS_FINAL_SPEC.md`
- `src/docs/HARNESS_CONFORMANCE.md`
- `src/docs/INITIAL_CONTEXT_ALIGNMENT.md`
