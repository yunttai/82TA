# Shared Contracts Scope

- Joint stewardship. Use `$shared-contract-governance` when a change crosses workstream boundaries or changes shared meaning.
- Contract updates are impact-based: change only the affected OpenAPI, DBML, event, code, example, generated client, and tests.
- Update versions and `CONTRACT_LOCK.json` only for intentional canonical changes authorized by the task; never use the lock to hide drift.
- Product code changes are outside this directory.
