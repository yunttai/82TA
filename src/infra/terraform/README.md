# Terraform Layout

```text
modules/
  network
  ecs-service
  rds
  redis
  s3
  iam
  observability
environments/
  dev
  staging
  prod
```

환경 state와 account를 분리하고 secret 값을 state에 평문 저장하지 않는다.
