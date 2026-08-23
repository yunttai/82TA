# Service and Routing infrastructure

This directory contains staging-capable deployment artifacts for the React PWA,
Django Service API, and independently runnable private Routing API. It preserves
the public Service/private Routing boundary and contains no provider, model,
candidate, or ranking business logic.

- `docker/`: non-root multi-stage images, local Stub Compose, and a separate
  Service-to-Routing HTTP E2E Compose topology
- `terraform/`: private S3 + CloudFront OAC, WAF, ALB/ECS, Service RDS/Redis,
  KMS/secrets, logs, autoscaling, ECR, and environment-scoped OIDC deployment
- `ci/github-actions/`: inert PR and staging deployment workflow templates
- `aws/STAGING_RUNBOOK.md`: Service bootstrap, migration, rollback, and restore
- `aws/ROUTING_STAGING_RUNBOOK.md`: private Routing bootstrap and live evidence gates
- `scripts/validate_infra.py`: local structural, Terraform-format, and Compose
  validation

```bash
python3 src/infra/scripts/validate_infra.py
```

Actual apply/deploy requires an AWS account, domain/certificates, secret values,
private Routing endpoint when HTTP mode is selected, and protected GitHub
Environment configuration. No real credential is stored here.
