---
name: harness-evolution
description: "Audit and improve Codex AGENTS.md, custom agents, skills, prompts, optional workspace notes, trigger coverage, validation, and orchestration without changing product behavior. Use for harness audits, excessive process, repeated failures, role overlap, trigger gaps, migration cleanup, and harness-only updates."
---
# Harness Evolution

1. Treat the request as harness-only unless the user explicitly authorizes product changes.
2. Define protected product artifacts and record their aggregate SHA-256 before editing.
3. Use the current implementation and active workflows as evidence; roadmap or historical docs must not force implementation changes.
4. Remove duplicated or unconditional process at the smallest useful layer. Preserve only safety boundaries and checks justified by the task's impact.
5. Do not modify business OpenAPI, DBML, product PRD, application behavior, migrations, algorithms, or deployment implementation.
6. Validate active agent/skill syntax and distinct, non-overlapping positive/negative trigger coverage. Treat legacy registries, prompts, snapshots, and gitignored ledgers as non-authoritative.
7. Run proportionate harness checks, then the full repository and contract-lock checks for a harness-wide change.
8. Compare protected hashes and publish a preservation report plus a concise harness changelog.
