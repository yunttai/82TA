# AWS target and current Service staging slice

- CloudFront + S3: React assets
- WAF + Public ALB: Service API
- ECS Fargate: Service, Routing, Collectors, Model Jobs
- Internal ALB: Service→Routing
- RDS PostgreSQL: separate Service/Routing DBs, PostGIS on Routing
- ElastiCache Redis
- S3 data/model/replay
- ECR
- Secrets Manager + KMS
- EventBridge + SQS/DLQ
- CloudWatch + OpenTelemetry

최소 2 AZ, private app/data subnet, DB public access off, OIDC-based CI role, Terraform environment separation.

The implemented `service-platform` staging module covers only CloudFront/S3,
public Service ALB/ECS, Service RDS/Redis, WAF, secrets, logs, scaling, its
encrypted Service data-rights artifact EFS and scheduled lifecycle tasks, and
its deploy role. It deliberately leaves the internal Routing ALB/tasks and all
Routing workers/data/model infrastructure to the Routing workstream. The Service task
can select canonical Stub/Replay until an independently deployed private HTTPS
Routing endpoint and token are supplied.

Operational bootstrap, one-off migrations, rollback, and the exact external
inputs are in [STAGING_RUNBOOK.md](STAGING_RUNBOOK.md).
