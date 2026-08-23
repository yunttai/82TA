# Code and Product Contract Preservation Report

- Generated: 2026-08-22T23:56:09+00:00
- User instruction: product/application code must not be modified
- Comparison source: original Claude dual-harness archive

## Result

- Protected files: **43**
- Unchanged: **42**
- Allowed harness-context document changes: **1**
- Unexpected changes or missing files: **0**

## Allowed change

- `src/docs/shared/SOURCE_LAYOUT_POLICY.md`: only active harness-control paths changed from Claude controls to Codex controls. Product requirements, API semantics, ERD, DBML and algorithms were not changed.

## Protected business artifacts

- `src/apps/**`, `src/services/**`, `src/packages/**`, `src/workers/**` existing files
- Public/Private OpenAPI and canonical examples
- Service/Routing DBML and schema ownership
- domain events and reason/warning/error registry
- shared product PRD, system architecture, ERD, data ownership, NFR, security, release gates

## Detailed status

| Status | Path |
|---|---|
| UNCHANGED | `src/apps/web/README.md` |
| UNCHANGED | `src/services/routing-api/README.md` |
| UNCHANGED | `src/services/service-api/README.md` |
| UNCHANGED | `src/packages/bus-intelligence-core/README.md` |
| UNCHANGED | `src/packages/observability/README.md` |
| UNCHANGED | `src/packages/provider-core/README.md` |
| UNCHANGED | `src/packages/routing-domain/README.md` |
| UNCHANGED | `src/workers/data-quality/README.md` |
| UNCHANGED | `src/workers/model-jobs/README.md` |
| UNCHANGED | `src/workers/transport-collector/README.md` |
| UNCHANGED | `src/contracts/openapi/common/components.v1.yaml` |
| UNCHANGED | `src/contracts/openapi/examples/public-route-search-request.json` |
| UNCHANGED | `src/contracts/openapi/examples/public-route-search-response.json` |
| UNCHANGED | `src/contracts/openapi/examples/routing-optimize-request.json` |
| UNCHANGED | `src/contracts/openapi/examples/routing-optimize-response.json` |
| UNCHANGED | `src/contracts/openapi/routing-private.v1.yaml` |
| UNCHANGED | `src/contracts/openapi/service-public.v1.yaml` |
| UNCHANGED | `src/contracts/database/migration-policy.md` |
| UNCHANGED | `src/contracts/database/routing-db.dbml` |
| UNCHANGED | `src/contracts/database/schema-ownership.yaml` |
| UNCHANGED | `src/contracts/database/service-db.dbml` |
| UNCHANGED | `src/contracts/events/domain-events.v1.yaml` |
| UNCHANGED | `src/contracts/codes/reason-warning-error-codes.yaml` |
| UNCHANGED | `src/docs/shared/API_CONTRACT_GUIDE.md` |
| UNCHANGED | `src/docs/shared/AWS_DEPLOYMENT.md` |
| UNCHANGED | `src/docs/shared/CONTEXT_MAP.md` |
| UNCHANGED | `src/docs/shared/DATA_MODEL_AND_OWNERSHIP.md` |
| UNCHANGED | `src/docs/shared/DECISION_AND_CHANGE_CONTROL.md` |
| UNCHANGED | `src/docs/shared/ERD.md` |
| UNCHANGED | `src/docs/shared/GLOSSARY.md` |
| UNCHANGED | `src/docs/shared/INTEGRATION_PLAYBOOK.md` |
| UNCHANGED | `src/docs/shared/NON_FUNCTIONAL_REQUIREMENTS.md` |
| UNCHANGED | `src/docs/shared/OBSERVABILITY_RUNBOOKS.md` |
| UNCHANGED | `src/docs/shared/PRD.md` |
| UNCHANGED | `src/docs/shared/PROJECT_CONTEXT.md` |
| UNCHANGED | `src/docs/shared/PROVIDER_CAPABILITY_MATRIX.md` |
| UNCHANGED | `src/docs/shared/README.md` |
| UNCHANGED | `src/docs/shared/RELEASE_GATES.md` |
| UNCHANGED | `src/docs/shared/REQUIREMENTS_TRACEABILITY.md` |
| UNCHANGED | `src/docs/shared/SECURITY_PRIVACY.md` |
| ALLOWED_HARNESS_CONTEXT_CHANGE | `src/docs/shared/SOURCE_LAYOUT_POLICY.md` |
| UNCHANGED | `src/docs/shared/SYSTEM_ARCHITECTURE.md` |
| UNCHANGED | `src/docs/shared/TEST_ACCEPTANCE.md` |

Machine-readable evidence: `src/docs/codex/code-preservation-report.json`.
