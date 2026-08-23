# CI/CD templates

PR:

- source layout/contract lock
- lint/type/unit/property
- OpenAPI/DBML/examples
- consumer/provider contract
- migration checks
- fixture replay
- frontend build/accessibility
- SAST/dependency/container/IaC scan
- SBOM

Main:

- build immutable artifacts/images
- dev deploy + smoke
- staging integration/performance
- production approval/release tag
- rolling or blue/green
- code/model/database rollback

The templates under `github-actions/` cover contracts, backend tests and
migration drift, frontend type/unit/build, Chromium mobile E2E, Docker and
Terraform checks, filesystem security scan, SBOM, immutable ECR publishing,
one-off migration, ECS rollout/rollback, S3 asset caching, CloudFront
invalidation, and staging smoke.

`bootstrap-routing-staging.yml` is a separate, confirmation-gated one-off
workflow. It verifies the bootstrap/migration task definitions use the same
immutable image, runs the master-scoped PostGIS/role bootstrap, runs Django
migrations as `routing_migrator`, then grants runtime DML/sequence access to
`routing_app` and revokes migrator schema creation. It never creates or reads a secret value in GitHub;
the Terraform-created secret containers must already be populated by the audited
secret operator.

They are intentionally inert in this location. Activating them under root
`.github/workflows/` is a repository control/ADR decision, not an automatic
side effect of this implementation. Before activation configure a protected
`staging` GitHub Environment and only these non-secret variables:

- `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`
- `SERVICE_ECR_REPOSITORY`, `SERVICE_ECS_CLUSTER`, `SERVICE_ECS_SERVICE`
- `SERVICE_ECS_SUBNETS` as comma-separated subnet IDs and
  `SERVICE_ECS_SECURITY_GROUP`
- `WEB_BUCKET`, `CLOUDFRONT_DISTRIBUTION_ID`, `STAGING_URL`
- domain-restricted `KAKAO_JS_API_KEY`, published
  `PRIVACY_DOCUMENT_VERSION` equal to Terraform
  `consent_document_version`/ECS `SERVICE_CONSENT_DOCUMENT_VERSION`
- The separately protected `staging-routing-database` GitHub Environment is the
  only environment allowed to run Routing database bootstrap. It requires
  `ROUTING_ECS_CLUSTER`,
  `ROUTING_ECS_SUBNETS`, `ROUTING_ECS_SECURITY_GROUP`,
  `ROUTING_DATABASE_BOOTSTRAP_TASK_DEFINITION`, and
  `ROUTING_MIGRATION_TASK_DEFINITION` from reviewed Terraform outputs, plus the
  dedicated `ROUTING_AWS_DATABASE_BOOTSTRAP_ROLE_ARN`.

No long-lived AWS key belongs in GitHub. The deploy role trust is limited to
the repository and the protected `staging` environment through OIDC. Terraform
apply/bootstrap uses a separate reviewed administrative role; the deploy role
cannot mutate VPC, RDS, WAF, IAM, or secret values.
The normal Routing deploy role can update only the named Routing service with a
Routing API task-definition family. The database role can run only the
bootstrap/migration families in the named cluster and Routing subnets, and can
pass only their two execution roles. `DescribeTaskDefinition` remains a
read-only wildcard because ECS does not support resource-level authorization
for that action; `RegisterTaskDefinition` is intentionally absent.
The deployment fails before task registration when the rendered Django consent
version differs from `VITE_PRIVACY_DOCUMENT_VERSION`.
