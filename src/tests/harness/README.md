# Harness Tests

Active checks are intentionally narrow:

- filesystem-backed custom-agent TOML and skill frontmatter/name/path
- positive and negative trigger-matrix coverage for every active skill
- product-under-`src` layout with conventional `.github` controls allowed
- Python/YAML/JSON syntax and, in full mode, existing product contract checks
- scenario dry-runs for implementation-first scope, evidence reuse, bounded delegation, owner-specific test runtimes, and PARTIAL versus fail-closed semantics

`src/contracts/harness/harness-registry.v1.yaml`, eval metadata, prompt recipes, `_workspace` ledgers, and historical snapshots are retained for compatibility/reference but are not active coverage by themselves.

```bash
python src/scripts/validate_repository.py --harness-only
python src/scripts/validate_repository.py --layout-only
python src/scripts/validate_repository.py
```

The trigger validator proves case coverage and schema, not actual model routing behavior. Interactive skill-selection evals may be run independently when needed.

`orchestrator-dry-runs.md` is the behavioral expectation set for regressions observed in real tasks; it does not require snapshot or workspace artifacts to prove execution.
