---
name: shared-context-loader
description: "Load and snapshot the canonical context for service-product, routing-intelligence, or integration. Use at the start of work, continuation, integration, drift investigation, and session resume."
---
# Shared Context Loader

1. Read applicable AGENTS.md files.
2. Run repository and lock validation.
3. Read context manifest, lock, platform versions, shared PRD/context map, relevant OpenAPI/DBML/code registry.
4. Read the selected workstream WORKPLAN/STATUS/HANDOFF.
5. Run `python src/scripts/snapshot_context.py <service-product|routing-intelligence|integration>`.
6. Record contextVersion, contractVersion, aggregateSha256, branch/worktree, changed canonical files, current blockers.
7. Do not update the lock or canonical files merely because snapshots differ.
