---
name: harness-evolution
description: "Audit and improve Codex AGENTS.md, custom agents, skills, prompts, ledgers, trigger coverage, validation and orchestration without changing product code. Use for harness audits, repeated failures, role changes, trigger gaps, migration cleanup, and harness-only updates."
---
# Harness Evolution

1. Treat this as harness-only unless explicitly authorized otherwise.
2. Hash protected product artifacts before changes.
3. Audit root/nested AGENTS.md, `.codex/config.toml`, custom agents, skills, prompt library, registry, evals, ledgers and validation.
4. Generalize repeated problems into the smallest layer: instruction, agent, skill, orchestrator, prompt, or deterministic script.
5. Do not modify business OpenAPI, DBML, product PRD or algorithms.
6. Run trigger/eval and repository checks.
7. Compare protected hashes and write a preservation report.
8. Update Codex migration/runbook docs and changelog.
