# Codex Harness Validation Report

- 기준일: 2026-08-23 KST
- Runtime: **Codex**
- Custom agents: **18**
- Skills: **25**
- Copy-paste prompt documents: **39**
- Nested scoped `AGENTS.md`: **11**
- Canonical context/contract files: **35**
- Package files at validation time: **316**
- Context version: **1.0.1**
- Business contract version: **1.0.0**
- Aggregate SHA-256: `c0390f148341e71d3bb9d0f7d13d3036656702c3cc477959c25a0d34a28a1b3a`

## Validation commands

```bash
python src/scripts/validate_repository.py
python src/scripts/verify_contract_lock.py
python src/scripts/snapshot_context.py service-product
python src/scripts/snapshot_context.py routing-intelligence
python src/scripts/snapshot_context.py integration
python src/scripts/compare_context_snapshots.py
```

## Results

| Check | Result |
|---|---|
| Root/nested AGENTS.md and root allowlist | PASS |
| `.codex/config.toml` | PASS |
| Custom agent TOML | PASS |
| Skill frontmatter/name/path | PASS |
| No executable scripts outside `src/` | PASS |
| Active Claude-only controls absent | PASS |
| OpenAPI YAML/local refs | PASS |
| Four canonical OpenAPI examples | PASS |
| Dual harness registry | PASS |
| Skill trigger/eval metadata | PASS |
| Contract lock | PASS |
| Service/Routing/Integration context parity | PASS |
| Product artifact preservation | PASS — 42 unchanged, 1 allowed source-layout policy change, 0 unexpected |

## Codex execution assets

- Root and scoped `AGENTS.md`
- `.agents/skills/*/SKILL.md`
- `.codex/agents/*.toml`
- `.codex/config.toml`
- durable `WORKPLAN.md`, `STATUS.md`, `HANDOFF.md`
- 36 task-specific prompts plus index/master/quick reference
- repository and context validators

## Runtime note

Static structure, contract, hashes, prompts, and context parity were validated in this environment. Interactive Codex delegation itself must be exercised in the user's Codex session; use `/agent` to inspect named subagents and the included work-plan ledgers to preserve state.

## Preservation evidence

See:

- `src/docs/codex/CODE_PRESERVATION_REPORT.md`
- `src/docs/codex/code-preservation-report.json`
