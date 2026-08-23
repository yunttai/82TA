# Service Product infrastructure

This directory contains staging-capable deployment artifacts for the React PWA
and Django Service API. It preserves the public Service/private Routing boundary
and contains no Bus Intelligence, provider, model, candidate, or ranking logic.

- `docker/`: non-root multi-stage Service/Web images and local Stub Compose
- `terraform/`: private S3 + CloudFront OAC, WAF, ALB/ECS, Service RDS/Redis,
  KMS/secrets, logs, autoscaling, ECR, and environment-scoped OIDC deployment
- `ci/github-actions/`: inert PR and staging deployment workflow templates
- `aws/STAGING_RUNBOOK.md`: bootstrap, migration, rollback, restore, and gaps
- `scripts/validate_infra.py`: local structural, Terraform-format, and Compose
  validation

```bash
python3 src/infra/scripts/validate_infra.py
```

Actual apply/deploy requires an AWS account, domain/certificates, secret values,
private Routing endpoint when HTTP mode is selected, and protected GitHub
Environment configuration. No real credential is stored here.
