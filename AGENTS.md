# 82TA

## Mission and current-state rule

Build and operate the budget-constrained, time-dependent multimodal route product for Gyeonggi South ↔ Seoul.

The repository's implementation, tests, migrations, and active deployment workflows are the baseline for maintenance work. Product documents may describe intended or future architecture; a mismatch is evidence to record, not permission for the harness to rewrite working code or infrastructure. GCE is the required and only supported cloud compute deployment platform; do not add another cloud path or dual-cloud parity unless a later explicit product/architecture decision supersedes ADR-0012. The exact GCE topology may evolve with implementation evidence.

The stable service boundary remains:

- **Service Product**: React Web/PWA and Django Service Backend
- **Routing & Intelligence**: providers, canonical mapping, Bus Intelligence, optimization, and the private Routing API
- Shared internal API: `POST /v1/routes/optimize`

Keep provider orchestration out of Service and user identity, history, and favorites out of Routing.

## Instruction and repository layout

Read this file and the nearest nested `AGENTS.md` for any path you edit. Closer instructions add local safety constraints; they do not turn roadmap material into an implementation mandate.

- `.codex/`, `.agents/`: Codex controls
- `.codegraph/`: ignored local index
- `_workspace/`: optional, gitignored working notes; never canonical or required to be current
- `.github/`: CI/CD and repository automation
- `src/`: product code, contracts, docs, tests, infrastructure, and executable scripts

Keep product implementation, product contracts, migrations, tests, IaC, and executable product scripts under `src/`, except conventional repository automation under `.github/`.

## Read and validation scope

Load only the context needed for the requested change:

- Local implementation change: applicable `AGENTS.md`, affected source, nearby tests, and directly consumed contracts.
- Shared API or semantic change: `CONTEXT_MANIFEST.json`, `CONTRACT_LOCK.json`, affected OpenAPI/DBML/event/code files, producers, consumers, and generated clients.
- Data, security, deployment, or release work: the relevant shared requirements and operational evidence.
- Harness-only work: harness controls and enough product evidence to prove preservation; do not treat product docs as an implementation backlog.

Use CodeGraph first when `.codegraph/` exists and code relationships need discovery. Keep the query bounded to the affected symbol or call path, then move to the requested implementation. Reuse findings from the current task while the relevant source has not changed; repeated broad exploration is not a completion requirement. Existing unrelated validation failures should be reported and separated from regressions introduced by the task; they do not automatically authorize broader repairs.

## Implementation-first rule

When the user asks to implement, fix, or continue code, the result must include that requested implementation and relevant verification. An audit, plan, CCR/ADR proposal, workspace ledger, or release verdict is not a substitute unless a concrete unresolved decision actually prevents the code change.

- Start with one bounded discovery pass and edit the production call path promptly.
- Do not expand a local implementation into architecture, governance, integration, security, or release work unless the diff changes that boundary or the user asked for it.
- On continuation, reuse still-valid source findings, contract hashes, and passing test evidence. Do not recreate snapshots, ledgers, plans, or rerun unchanged suites merely because a new task turn began.
- Missing live provider credentials or production approval do not block pure-domain or fixture-backed offline work. They block only the live capability or production claim that depends on them.

## Narrow-default scope and questions

Use the narrowest interpretation that satisfies the requested change and matches an existing production path. Adjacent capabilities are separate work, not implicit acceptance criteria. For example, shared coordination for rate limiting or idempotency does not also require Provider-response caching, cache-retention policy, or cloud rollout unless the user asked for those outcomes.

- Do not pause for scope confirmation when the named slice has one safe, reversible, implementation-backed interpretation. Record adjacent ideas as out of scope or TBD and continue.
- Ask only when unresolved alternatives would materially change public/shared semantics, data ownership or privacy, security posture, an irreversible action, or external state beyond the task's authority.
- A shared path is not itself an approval gate. Inspect the current diff and active writers, preserve compatible edits, and coordinate only an actual overlapping change.
- Activating or extending repository-local PR validation is routine implementation when the user requested working CI. Separate authority is needed only for secrets/permissions, deployment, destructive behavior, billing, or another external side effect.
- Completion evidence stops at the environment named by the task. Local or PR-CI proof does not imply a deployed-GCE check; a GCE deployment claim requires GCE evidence. Never revive a removed AWS path as a prerequisite.
- When the user explicitly requests speed or minimal verification, run the smallest checks that directly exercise the changed behavior plus mandatory safety/contract checks actually triggered by the diff.

## Workstream boundaries

The following are architectural responsibilities, not exclusive agent ownership declarations.

### Service Product

- Primary trees: `src/apps/web/**`, `src/services/service-api/**`
- Owns browser UX, public API, accounts, places, preferences, history, favorites, feedback, `RoutingGateway`, and public-safe projection.
- Must not call Routing from the browser, orchestrate transport providers/models, read the Routing DB, or recalculate Routing-owned ranking, duration, fare, ETA, or probability.

### Routing & Intelligence

- Primary trees: `src/services/routing-api/**`, `src/packages/**`, `src/workers/**`
- Owns provider adapters, mapping, Bus Intelligence, candidate generation, cost, feasibility, ranking, collectors, and model lifecycle.
- Must not access Service identity/data or expose provider raw shapes as canonical/public DTOs.

### Shared surfaces

For `src/contracts/**`, `src/docs/shared/**`, `src/generated/**`, `src/tests/contracts/**`, `src/tests/integration/**`, and `src/infra/**`, inspect the affected producers and consumers. Synchronous approval is required only when the task lacks authority for a material semantic, ownership, security, irreversible, or external-state decision. A shared path alone is not a gate, and unrelated artifacts do not need to change.

## Contract changes are impact-based

Before changing a shared surface, identify its actual consumers and compatibility impact. Update only affected artifacts:

- API shape or semantics: relevant OpenAPI, examples, generated client, producer/consumer tests, changelog, and lock.
- Persistence shape: relevant DBML/model/migration and data tests.
- Event or code vocabulary: only the relevant registry/event schemas and consumers.
- Cross-workstream meaning, ownership boundary, production cloud/provider strategy, or backward-incompatible behavior: record the decision/CCR or ADR and update affected acceptance material.

Do not require DBML, events, and code registries to change when they are unaffected. Never create workstream-local copies of shared DTOs, ERDs, or enums. Regenerate and update `CONTRACT_LOCK.json` only for intentional canonical changes authorized by the task; do not alter it to hide drift.

## Agents, skills, and workspace

Custom agents and orchestrator skills are optional tools for genuinely independent or specialized work. A profile's listed paths are expertise hints, not standing ownership. When delegating, the primary task assigns the smallest non-overlapping write scope and owns integration. A focused change should use the primary thread or, when delegation is authorized and useful, at most one implementation specialist plus one independent reviewer; broader fan-out requires genuinely independent work or an explicit user request. Finish or release delegated roles when their bounded task ends. Use `_workspace` notes only when a long-running or delegated task benefits from them; stale or absent workspace files must not block routine work.

Invoke only the skill(s) materially relevant to the request. Do not chain planning, governance, QA, and release workflows for a local change unless its risk or boundary impact calls for them.

## Correctness and safety invariants

When the affected feature uses these concepts, preserve:

- timezone-aware ISO 8601; duration seconds, distance meters, money KRW; WGS84 coordinates
- `P90 >= P50`
- strict budget based on the sum of taxi upper-cost estimates
- distinct `null`, `unknown`, `unsupported`, and numeric zero
- Bus Intelligence only after its mapping-confidence gate
- bus candidates evaluated at the user's arrival time at the boarding stop
- general crowding not treated as boarding failure without supporting evidence
- explicit partial provider failure and provider/model/ranking/mapping provenance
- unverified external/model capability stays disabled, `unsupported`, or `PARTIAL`; the harness must not claim it works
- no untrusted pickle artifacts, secret leakage, or cross-context database reads

Fail closed for authentication, trust/schema validation, model artifact integrity, and values required to certify strict feasibility. Optional exactification or enrichment failures follow the existing fallback, candidate-drop, `PARTIAL`, or no-feasible-route semantics; do not convert them into a blanket 5xx/504 without an explicit contract requirement.

## Harness-only changes

For requests limited to Codex controls, prompts, orchestration, or validators:

- do not modify application source, business OpenAPI, ERD/DBML, product PRD, algorithms, migrations, or deployment implementation
- limit changes to `AGENTS.md` files, `.codex/`, `.agents/`, harness/Codex docs, optional `_workspace` templates, `src/tests/harness/**`, and harness validation/context scripts
- calculate before/after SHA-256 evidence for protected product artifacts

## Proportionate completion

- Routine code/docs patch: targeted tests or checks for touched behavior.
- Shared boundary, migration, security, provider, or model change: add the relevant contract/integration/data/security evidence.
- Integration or release decision: run repository/lock validation, live context parity, and the applicable release gates.
- Harness-wide change: run harness registry/eval/layout checks, full repository and contract-lock validation, and protected-hash comparison.

Run tests in the runtime that owns them. Routing package/API tests use the Routing runtime; Service/API/Web tests use the Service runtime; use a prepared integration environment for cross-workstream tests. Do not collect unrelated Service and Routing test directories under one environment. Run targeted checks while iterating and at most one relevant aggregate suite after the diff stabilizes; reuse a passing result while its code and dependencies remain unchanged.

Snapshot files and `_workspace` ledgers are optional diagnostics, not completion evidence. Do not issue `GO`/`NO_GO` or deployment-readiness verdicts for an ordinary implementation request. Report changed files, product/contract impact, checks run, known risks, and rollback guidance in proportion to the change.
