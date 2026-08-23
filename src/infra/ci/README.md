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

They are intentionally inert in this location. Activating them under root
`.github/workflows/` is a repository control/ADR decision, not an automatic
side effect of this implementation. Before activation configure a protected
`staging` GitHub Environment and only these non-secret variables:

- `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`
- `SERVICE_ECR_REPOSITORY`, `SERVICE_ECS_CLUSTER`, `SERVICE_ECS_SERVICE`
- `SERVICE_ECS_SUBNETS` as comma-separated subnet IDs and
  `SERVICE_ECS_SECURITY_GROUP`
- `WEB_BUCKET`, `CLOUDFRONT_DISTRIBUTION_ID`, `STAGING_URL`
- domain-restricted `KAKAO_MAP_APP_KEY`, published
  `PRIVACY_DOCUMENT_VERSION` equal to Terraform
  `consent_document_version`/ECS `SERVICE_CONSENT_DOCUMENT_VERSION`

No long-lived AWS key belongs in GitHub. The deploy role trust is limited to
the repository and the protected `staging` environment through OIDC. Terraform
apply/bootstrap uses a separate reviewed administrative role; the deploy role
cannot mutate VPC, RDS, WAF, IAM, or secret values.
The deployment fails before task registration when the rendered Django consent
version differs from `VITE_PRIVACY_DOCUMENT_VERSION`.
