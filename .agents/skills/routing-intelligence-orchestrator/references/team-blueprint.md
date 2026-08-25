# Routing Delegation Blueprint

Delegation is optional. Use the primary thread for a focused implementation. When the user asks for delegation or the task has genuinely independent work, assign at most:

- one implementation specialist with the smallest write scope
- one independent reviewer/QA with a non-overlapping test or review scope

Add contract, architecture, security/performance, integration, or release expertise only when the actual diff crosses that boundary. Do not create standing Provider/Mapping/Bus/Optimizer/API teams for a local gap.

Return changed files, checks, contract impact, and unresolved risk to the primary task. Write `_workspace` handoff/version/hash records only when long-running coordination needs durable state or the user explicitly requests them.
