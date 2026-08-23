# 82TA

## Mission

Build a commercial-quality, budget-constrained, time-dependent multimodal route recommendation product for Gyeonggi South ↔ Seoul. The product combines walking, taxi, bus, subway, and GTX; applies Bus Intelligence to relevant Gyeonggi bus legs; and returns FASTEST, STABLE, EFFICIENT, and PUBLIC_TRANSIT_ONLY recommendations.

The accepted architecture is one monorepo with two independently deployable workstreams:

1. **Service Product** — React Web/PWA + Django Service Backend
2. **Routing & Intelligence** — transport providers, canonical mapping, Bus Intelligence, ETA, candidate generation, strict budget, transfer risk, Pareto ranking

The shared internal boundary is `POST /v1/routes/optimize`. Do not move provider orchestration into Service. Do not move user identity or favorites into Routing.

## Instruction discovery

Codex reads this root file and the nearest nested `AGENTS.md` files. Before editing a path, read every applicable instruction file from the repository root down to that path. A closer scoped file overrides a broader rule only for its subtree.

## Repository roots

- `.codex/`: Codex project config and custom subagents
- `.agents/skills/`: reusable Codex skills
- `.codegraph/`: ignored local CodeGraph index; never a product artifact
- `_workspace/`: durable work plans, handoffs, audits, and integration evidence
- `src/`: all product artifacts, product documentation, contracts, implementation, tests, infrastructure, and executable scripts
- `AGENTS.md`, `README.md`, `.gitignore`: root entry files

Do not create product code, PRDs, ERDs, API specs, migrations, tests, IaC, generated clients, or executable scripts outside `src/`.

## Canonical context — read before work

Always read:

1. `src/contracts/CONTEXT_MANIFEST.json`
2. `src/contracts/CONTRACT_LOCK.json`
3. `src/docs/shared/PROJECT_CONTEXT.md`
4. `src/docs/shared/PRD.md`
5. `src/docs/shared/CONTEXT_MAP.md`
6. relevant OpenAPI/DBML/code registry files
7. applicable workstream documents
8. latest `_workspace/<workstream>/WORKPLAN.md`, `STATUS.md`, `HANDOFF.md`

Run before changes:

```bash
python src/scripts/validate_repository.py
python src/scripts/verify_contract_lock.py
```

If validation or the contract lock fails, stop product implementation. Diagnose drift; do not silently regenerate shared definitions.

## Workstream ownership

### Workstream 1 — Service Product

Owned:

- `src/apps/web/**`
- `src/services/service-api/**`
- `src/docs/harnesses/service-product/**`

Responsibilities:

- React/TypeScript Web/PWA
- Kakao Maps browser rendering
- place search UX and Kakao Local through Service Backend
- auth, guest sessions, preferences, history, favorites, feedback
- public Service API
- `RoutingGateway` consumer
- public-safe response projection

Forbidden:

- browser direct calls to Routing
- direct GBIS/Kakao Mobility/model orchestration
- Routing DB reads
- recalculating route ranking, duration, fare, or model probability

### Workstream 2 — Routing & Intelligence

Owned:

- `src/services/routing-api/**`
- `src/packages/routing-domain/**`
- `src/packages/provider-core/**`
- `src/packages/bus-intelligence-core/**`
- `src/workers/**`
- `src/docs/harnesses/routing-intelligence/**`

Responsibilities:

- provider adapters and capability gates
- canonical route/stop model and Kakao↔GBIS mapping
- Bus ETA, seat risk, boardability proxy, expected wait
- multimodal candidates and time-dependent costs
- transfer feasibility, strict taxi budget, Pareto/ranking
- collectors, data quality, model lifecycle, deterministic replay

Forbidden:

- Service DB or user identity access
- account/history/favorites logic
- provider raw shapes in optimizer/public clients
- missing values treated as zero risk
- untrusted pickle artifacts

### Shared paths

- `src/contracts/**`
- `src/docs/shared/**`
- `src/generated/**`
- `src/tests/contracts/**`
- `src/tests/integration/**`
- `src/infra/**`

Use `$shared-contract-governance` before editing shared API, DB, event, enum, reason/warning/error, or semantic definitions.

## Codex skills

Explicitly invoke material workflows with `$skill-name`:

- `$service-product-orchestrator`
- `$routing-intelligence-orchestrator`
- `$shared-contract-governance`
- `$integration-coherence-qa`
- `$platform-release-gate`
- `$harness-evolution`

Supporting delivery skills live under `.agents/skills/`.

## Codex custom subagents

Use named custom subagents from `.codex/agents/*.toml` for independent work. The primary thread owns the plan, waits for all delegated work, resolves conflicts, and consolidates the final diff. Use `/agent` interactively to inspect or continue a subagent thread.

For each delegated task, record in `_workspace/<workstream>/WORKPLAN.md`:

- task ID
- custom agent
- owned paths
- dependencies
- contract inputs
- acceptance criteria
- test command
- status
- handoff file

Subagents may write only within assigned paths and must return a structured summary.

## Contract-first rule

For shared behavior changes:

1. create a contract change request
2. update PRD/acceptance when semantics change
3. update OpenAPI, DBML, code registry, examples, and events together
4. evaluate backward compatibility
5. update the contract lock only after joint approval
6. regenerate clients under `src/generated/`
7. update producer and consumer contract tests
8. rerun context snapshots for both workstreams

Never create local copies of shared DTOs, ERDs, or enums in a workstream.

## Correctness invariants

- timezone-aware ISO 8601; durations integer seconds
- distance integer meters; money integer KRW
- WGS84 longitude/latitude
- `P90 >= P50`
- strict budget uses sum of taxi upper-cost estimates
- `null`, `unknown`, `unsupported`, numeric zero are distinct
- Bus Intelligence only after mapping confidence gate
- user arrival time at stop determines candidate buses
- general bus crowding is not automatically boarding-failure penalty
- partial provider failure is explicit
- route results preserve provider/model/ranking/mapping provenance

## Harness-only requests

When asked to change only Codex controls, prompts, or orchestration:

- do not modify application source, business OpenAPI contracts, ERDs, DBML, product PRD, or model algorithms
- change only `AGENTS.md`, `.codex/`, `.agents/`, Codex/harness docs, `_workspace` templates, and harness validation scripts
- generate before/after SHA-256 preservation evidence for protected product artifacts

## Completion

Run the smallest relevant tests, then:

```bash
python src/scripts/validate_repository.py
python src/scripts/verify_contract_lock.py
```

For integration/release:

```bash
python src/scripts/snapshot_context.py service-product
python src/scripts/snapshot_context.py routing-intelligence
python src/scripts/compare_context_snapshots.py
```

Report changed files, product/contract impact, tests, unresolved risks/TBDs, rollback, and context parity.
