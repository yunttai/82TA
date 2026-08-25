# Product Artifact Preservation Report

- Generated: 2026-08-25T08:53:30Z
- Change type: harness-only, focused-scope and approval-bottleneck relaxation
- Result: **PASS**

## Protected scope

The protected set contains product implementation, business contracts, generated clients, migrations, non-harness tests, infrastructure/deployment implementation, active GitHub workflows, and canonical product documentation. Harness controls were excluded: all `AGENTS.md`, `.codex/**`, `.agents/**`, `_workspace/**`, root README, Codex/harness/prompt docs, harness tests, and harness validation/context scripts.

The aggregate is SHA-256 over sorted UTF-8 records in the form `<Windows-relative-path>\0<file-sha256>`, each terminated by LF. Runtime/build directories are excluded.

| Evidence | Before | After |
|---|---:|---:|
| Protected files | 642 | 642 |
| Aggregate SHA-256 | `4b34d51e2f1eb058e86fd19b47f61aea219222feda41d55fe7cf1e39705719df` | `4b34d51e2f1eb058e86fd19b47f61aea219222feda41d55fe7cf1e39705719df` |
| Unexpected protected changes | 0 | 0 |

## Canonical contract evidence

- Canonical files: 39
- Contract/context version: 1.4.0
- Live lock aggregate: `59729c98afc71606db1577871f1516421c913453034b8974720afb51dd96cd46`
- `verify_contract_lock.py`: PASS

No application code, Redis behavior, business OpenAPI, DBML, events/codes, migrations, generated client, active GCE workflow, Docker Compose deployment implementation, algorithm, or shared product meaning was changed. Only harness controls, harness tests, and harness documentation were updated.

Machine-readable evidence: `code-preservation-report.json`.
