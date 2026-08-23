# AWS Target Architecture

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
