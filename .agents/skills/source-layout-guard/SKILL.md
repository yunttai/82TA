---
name: source-layout-guard
description: "Enforce the src-only product artifact policy and Codex control-file allowlist. Use after harness changes, new files, repository audits, integration, and release."
---
# Source Layout Guard

Run `python src/scripts/validate_repository.py --layout-only`.

Allow root only: `.codex`, `.agents`, `_workspace`, `src`, `AGENTS.md`, `README.md`, `.gitignore`, optional `.git`.

Executable implementation belongs under `src/`. `.codex` and `.agents` may contain only TOML/Markdown/reference data, not Python/shell implementation. Reject `.claude` and active `CLAUDE.md`. Reject duplicated YAML/JSON/DBML machine contracts in workstream docs.
