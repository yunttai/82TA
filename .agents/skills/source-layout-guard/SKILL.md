---
name: source-layout-guard
description: "Keep product implementation under src while allowing conventional repository controls and CI/CD. Use after harness changes, new files, repository audits, integration, and release."
---
# Source Layout Guard

Run:

```bash
python src/scripts/validate_repository.py --layout-only
```

Product code, product contracts, migrations, tests, IaC, and executable product scripts belong under `src/`. Conventional repository controls are allowed at the root, including `.codex/`, `.agents/`, ignored `.codegraph/`, optional `_workspace/`, `.github/`, Git/editor configuration, license, security, and contribution files.

`.codex/` and `.agents/` may contain declarative TOML/Markdown/reference data, not product implementation. Reject active `.claude/` or `CLAUDE.md` controls and duplicated canonical YAML/JSON/DBML contracts in workstream documentation.
