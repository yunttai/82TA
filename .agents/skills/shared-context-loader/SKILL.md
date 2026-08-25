---
name: shared-context-loader
description: "Load the minimum canonical context needed for a Service, Routing, integration, continuation, or drift investigation. Use snapshots only when a durable diagnostic artifact is explicitly useful."
---
# Shared Context Loader

1. Read the applicable `AGENTS.md` chain and inspect the current implementation first.
2. For local work, load affected source, nearby tests, and directly consumed contracts only.
3. For shared API/semantic work, additionally load the manifest, lock, affected canonical files, generated clients, producers, and consumers.
4. For deployment, security, integration, or release work, add only the relevant NFR, runbook, and evidence.
5. Run the smallest relevant validation. Verify the full contract lock when canonical files are involved or parity is being assessed.
6. Do not require `_workspace` state. It is optional, gitignored, and may be stale.
7. When a snapshot is explicitly requested, `snapshot_context.py` overwrites one current file by default; use `--archive` only for deliberate historical evidence.
8. Never update canonical files or the lock merely to make context checks pass.
