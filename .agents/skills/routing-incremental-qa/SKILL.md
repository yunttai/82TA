---
name: routing-incremental-qa
description: "변경된 Routing 경계의 fixture↔adapter, mapping↔gold, algorithm↔invariant/replay, model↔runtime, private API↔consumer를 선택적으로 교차 검증한다. 명시적 경계 QA나 Routing 릴리스 검증에 사용한다."
---

# Routing Incremental QA

Start from the current diff and test only joins it can affect:

- adapter change: relevant raw fixture → canonical output, resilience, freshness
- mapping change: affected direction/branch/gold case and confidence gate
- optimizer change: counterexample/property/replay for strict budget, P90, time monotonicity, Pareto, and determinism
- Bus/model change: relevant candidate/label/calibration/artifact/runtime fallback
- private API or shared response change: affected serializer/contract/generated consumer
- explicit performance/security/release request: only the applicable load, trust, quota, and fault cases

Do not run every category after every module. Reuse green evidence while its source, fixtures, configuration, and dependencies are unchanged. Run Routing-owned tests in the Routing environment and Service consumer tests in the Service environment; do not collect mixed test trees under one runtime.

Provider partial failure and optional enrichment timeout must preserve the current fallback/`PARTIAL`/no-feasible-route meaning. Fail closed only where trust or strict feasibility cannot be certified.

Report a finding with the smallest useful evidence: affected path, expected versus actual, severity, and reproduction/retest command. Add snapshot, version, owner, or release metadata only when it is relevant to the request.
