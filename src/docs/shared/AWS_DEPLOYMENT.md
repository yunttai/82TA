# AWS Deployment Plan

## 구성

- React assets: S3 + CloudFront
- Public API: ALB + ECS Fargate Service API
- Private Routing: Internal ALB + ECS Fargate Routing API
- Workers: EventBridge + SQS + ECS Tasks/AWS Batch
- Databases: RDS PostgreSQL, Routing에 PostGIS
- Cache: ElastiCache Redis
- Raw/normalized/features/models/replay: S3
- Secrets: Secrets Manager + KMS
- Images: ECR
- Observability: CloudWatch + OpenTelemetry
- IaC: Terraform under `src/infra`

## 네트워크

- 2개 이상 AZ
- ECS·RDS·Redis private subnet
- Routing public ingress 없음
- Service security group만 Routing ingress
- DB public access 비활성
- Provider outbound는 NAT 또는 egress proxy
- S3/ECR/CloudWatch/Secrets VPC endpoint 검토

## 배포

- PR: lint, unit, contract, migration, security, build, SBOM, replay
- main: ECR push, dev deploy, integration, staging
- production: release tag·승인, rolling 또는 blue/green
- 실패 시 previous task definition·model version rollback

## 비용 통제

- 검색당 Provider call 수·비용
- cache hit와 quota burn rate
- daily/monthly budget alarm
- cost anomaly detection
- feature별 cost-to-value
- multi-destination fallback의 호출 폭발 감지
