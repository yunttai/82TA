data "aws_region" "current" {}
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  tags = merge(var.tags, {
    Application = "82ta-routing-intelligence"
    Environment = var.environment
    ManagedBy   = "terraform"
  })
  provider_secret_names = toset([
    "KAKAO_REST_API_KEY",
    "GBIS_SERVICE_KEY",
    "GITS_API_KEY",
    "TMAP_APP_KEY",
    "ODSAY_API_KEY",
  ])
  az_count                      = length(var.availability_zones)
  create_github_role            = var.github_repository != "" && var.github_oidc_provider_arn != ""
  create_github_database_role   = local.create_github_role && var.github_database_environment != ""
  ecs_cluster_arn               = "arn:${data.aws_partition.current.partition}:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:cluster/${var.ecs_cluster}"
  routing_service_arn           = "arn:${data.aws_partition.current.partition}:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:service/${var.ecs_cluster}/${var.name}-routing-api"
  routing_task_arn              = "arn:${data.aws_partition.current.partition}:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:task/${var.ecs_cluster}/*"
  routing_task_definition_arn   = "arn:${data.aws_partition.current.partition}:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:task-definition/${var.name}-routing-api:*"
  bootstrap_task_definition_arn = "arn:${data.aws_partition.current.partition}:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:task-definition/${var.name}-routing-database-bootstrap:*"
  migration_task_definition_arn = "arn:${data.aws_partition.current.partition}:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:task-definition/${var.name}-routing-migration:*"
}

resource "aws_subnet" "routing" {
  count             = local.az_count
  vpc_id            = var.vpc_id
  availability_zone = var.availability_zones[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, 96 + count.index)
  tags              = merge(local.tags, { Name = "${var.name}-routing-${count.index + 1}", Tier = "private-routing" })

  lifecycle {
    precondition {
      condition     = toset(keys(var.provider_firewall_endpoint_ids)) == toset(var.availability_zones)
      error_message = "provider_firewall_endpoint_ids must contain exactly one audited Network Firewall endpoint for every availability zone."
    }
  }
}

resource "aws_route_table" "routing" {
  count  = local.az_count
  vpc_id = var.vpc_id
  route {
    cidr_block      = "0.0.0.0/0"
    vpc_endpoint_id = var.provider_firewall_endpoint_ids[var.availability_zones[count.index]]
  }
  tags = merge(local.tags, { Name = "${var.name}-routing-${count.index + 1}" })
}

resource "aws_route_table_association" "routing" {
  count          = local.az_count
  subnet_id      = aws_subnet.routing[count.index].id
  route_table_id = aws_route_table.routing[count.index].id
}

resource "aws_route" "routing_return_through_firewall" {
  count                  = local.az_count
  route_table_id         = var.public_route_table_id
  destination_cidr_block = aws_subnet.routing[count.index].cidr_block
  vpc_endpoint_id        = var.provider_firewall_endpoint_ids[var.availability_zones[count.index]]
}

resource "aws_kms_key" "routing" {
  description             = "${var.name} Routing data, secrets, cache, and logs"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountAdministration"
        Effect    = "Allow"
        Principal = { AWS = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "CloudWatchLogsEncryption"
        Effect    = "Allow"
        Principal = { Service = "logs.${data.aws_region.current.name}.amazonaws.com" }
        Action    = ["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
        Resource  = "*"
        Condition = {
          ArnLike = { "kms:EncryptionContext:aws:logs:arn" = "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:*" }
        }
      }
    ]
  })
  tags = local.tags
}

resource "aws_kms_alias" "routing" {
  name          = "alias/${var.name}-routing"
  target_key_id = aws_kms_key.routing.key_id
}

resource "aws_ecr_repository" "routing" {
  name                 = "${var.name}/routing-api"
  image_tag_mutability = "IMMUTABLE"
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.routing.arn
  }
  image_scanning_configuration { scan_on_push = true }
  tags = local.tags
}

resource "aws_ecr_lifecycle_policy" "routing" {
  repository = aws_ecr_repository.routing.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Retain newest 30 immutable Routing images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 30
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_security_group" "alb" {
  name_prefix = "${var.name}-routing-alb-"
  description = "Internal Routing ALB; Service tasks are the only caller"
  vpc_id      = var.vpc_id
  tags        = local.tags
}

resource "aws_vpc_security_group_ingress_rule" "alb_service" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = var.service_security_group_id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
  description                  = "Service API to private Routing HTTPS"
}

resource "aws_security_group" "task" {
  name_prefix = "${var.name}-routing-task-"
  description = "Private Routing API tasks"
  vpc_id      = var.vpc_id
  tags        = local.tags
}

resource "aws_vpc_security_group_ingress_rule" "task_alb" {
  security_group_id            = aws_security_group.task.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "alb_task" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.task.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "task_provider_https" {
  security_group_id = aws_security_group.task.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  description       = "Provider HTTPS; dedicated Routing route tables force traffic through audited Network Firewall endpoints"
}

resource "aws_vpc_security_group_egress_rule" "task_dns_udp" {
  security_group_id = aws_security_group.task.id
  cidr_ipv4         = var.vpc_cidr
  from_port         = 53
  to_port           = 53
  ip_protocol       = "udp"
  description       = "VPC DNS resolution"
}

resource "aws_vpc_security_group_egress_rule" "task_dns_tcp" {
  security_group_id = aws_security_group.task.id
  cidr_ipv4         = var.vpc_cidr
  from_port         = 53
  to_port           = 53
  ip_protocol       = "tcp"
  description       = "VPC DNS fallback"
}

resource "aws_security_group" "endpoints" {
  name_prefix = "${var.name}-routing-endpoints-"
  description = "AWS control-plane VPC endpoints for private Routing tasks"
  vpc_id      = var.vpc_id
  tags        = local.tags
}

resource "aws_vpc_security_group_ingress_rule" "endpoints_task" {
  security_group_id            = aws_security_group.endpoints.id
  referenced_security_group_id = aws_security_group.task.id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "task_endpoints" {
  security_group_id            = aws_security_group.task.id
  referenced_security_group_id = aws_security_group.endpoints.id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
  description                  = "ECR, logs, Secrets Manager, KMS, and STS interface endpoints"
}

resource "aws_vpc_endpoint" "routing_control_plane" {
  for_each = toset([
    "ecr.api",
    "ecr.dkr",
    "logs",
    "secretsmanager",
    "kms",
    "sts",
  ])
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.routing[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
  tags                = merge(local.tags, { Name = "${var.name}-routing-${replace(each.key, ".", "-")}" })
}

resource "aws_security_group" "database" {
  name_prefix = "${var.name}-routing-db-"
  description = "Routing-owned PostgreSQL/PostGIS"
  vpc_id      = var.vpc_id
  tags        = local.tags
}

resource "aws_vpc_security_group_ingress_rule" "database_task" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.task.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "task_database" {
  security_group_id            = aws_security_group.task.id
  referenced_security_group_id = aws_security_group.database.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_db_subnet_group" "routing" {
  name       = "${var.name}-routing"
  subnet_ids = var.data_subnet_ids
  tags       = local.tags
}

resource "aws_db_instance" "routing" {
  identifier                   = "${var.name}-routing"
  engine                       = "postgres"
  engine_version               = var.postgres_engine_version
  instance_class               = var.rds_instance_class
  allocated_storage            = 40
  max_allocated_storage        = 200
  storage_type                 = "gp3"
  storage_encrypted            = true
  kms_key_id                   = aws_kms_key.routing.arn
  db_name                      = "routing"
  username                     = "routing_admin"
  manage_master_user_password  = true
  db_subnet_group_name         = aws_db_subnet_group.routing.name
  vpc_security_group_ids       = [aws_security_group.database.id]
  publicly_accessible          = false
  multi_az                     = var.rds_multi_az
  backup_retention_period      = 7
  deletion_protection          = var.deletion_protection
  skip_final_snapshot          = false
  final_snapshot_identifier    = "${var.name}-routing-final"
  copy_tags_to_snapshot        = true
  performance_insights_enabled = true
  tags                         = local.tags
}

resource "aws_security_group" "redis" {
  name_prefix = "${var.name}-routing-redis-"
  description = "Routing-owned encrypted Redis"
  vpc_id      = var.vpc_id
  tags        = local.tags
}

resource "aws_vpc_security_group_ingress_rule" "redis_task" {
  security_group_id            = aws_security_group.redis.id
  referenced_security_group_id = aws_security_group.task.id
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "task_redis" {
  security_group_id            = aws_security_group.task.id
  referenced_security_group_id = aws_security_group.redis.id
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
}

resource "aws_elasticache_subnet_group" "routing" {
  name       = "${var.name}-routing"
  subnet_ids = var.data_subnet_ids
}

resource "aws_elasticache_replication_group" "routing" {
  replication_group_id       = "${var.name}-routing"
  description                = "Routing cache and coordination"
  node_type                  = var.redis_node_type
  port                       = 6379
  parameter_group_name       = "default.redis7"
  engine_version             = "7.1"
  num_cache_clusters         = 1
  subnet_group_name          = aws_elasticache_subnet_group.routing.name
  security_group_ids         = [aws_security_group.redis.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  kms_key_id                 = aws_kms_key.routing.arn
  snapshot_retention_limit   = 1
  apply_immediately          = true
  tags                       = local.tags
}

resource "aws_secretsmanager_secret" "django" {
  name_prefix = "${var.name}/routing/django-"
  kms_key_id  = aws_kms_key.routing.arn
  tags        = local.tags
}

resource "aws_secretsmanager_secret" "migration_django" {
  name_prefix = "${var.name}/routing/migration-django-"
  kms_key_id  = aws_kms_key.routing.arn
  tags        = local.tags
}

resource "aws_secretsmanager_secret" "migration_jwt" {
  name_prefix = "${var.name}/routing/migration-jwt-"
  kms_key_id  = aws_kms_key.routing.arn
  tags        = local.tags
}

resource "aws_secretsmanager_secret" "database_password" {
  name_prefix = "${var.name}/routing/database-app-password-"
  kms_key_id  = aws_kms_key.routing.arn
  tags        = local.tags
}

resource "aws_secretsmanager_secret" "database_migration_password" {
  name_prefix = "${var.name}/routing/database-migration-password-"
  kms_key_id  = aws_kms_key.routing.arn
  tags        = local.tags
}

resource "aws_secretsmanager_secret" "provider" {
  for_each    = local.provider_secret_names
  name_prefix = "${var.name}/routing/${lower(each.key)}-"
  kms_key_id  = aws_kms_key.routing.arn
  tags        = local.tags
}

resource "aws_lb" "routing" {
  name                       = substr(replace("${var.name}-routing", "_", "-"), 0, 32)
  internal                   = true
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = aws_subnet.routing[*].id
  enable_deletion_protection = var.deletion_protection
  drop_invalid_header_fields = true
  tags                       = local.tags
}

resource "aws_lb_target_group" "routing" {
  name_prefix          = "82rte-"
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = var.vpc_id
  deregistration_delay = 15
  health_check {
    enabled             = true
    path                = "/v1/health/live"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
  tags = local.tags
}

resource "aws_lb_listener" "routing" {
  load_balancer_arn = aws_lb.routing.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.routing_certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.routing.arn
  }
}

resource "aws_route53_record" "routing" {
  zone_id = var.routing_private_zone_id
  name    = var.routing_private_hostname
  type    = "A"
  alias {
    name                   = aws_lb.routing.dns_name
    zone_id                = aws_lb.routing.zone_id
    evaluate_target_health = true
  }
}

resource "aws_cloudwatch_log_group" "routing" {
  name              = "/ecs/${var.name}/routing-api"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.routing.arn
  tags              = local.tags
}

resource "aws_iam_role" "execution" {
  name_prefix = "${var.name}-routing-exec-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "routing-runtime-secrets"
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = concat(
          [
            aws_secretsmanager_secret.django.arn,
            aws_secretsmanager_secret.database_password.arn,
            var.shared_jwt_secret_arn,
          ],
          [for secret in aws_secretsmanager_secret.provider : secret.arn]
        )
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = [aws_kms_key.routing.arn, var.shared_kms_key_arn]
      }
    ]
  })
}

resource "aws_iam_role" "migration_execution" {
  name_prefix = "${var.name}-routing-migration-exec-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "migration_execution" {
  role       = aws_iam_role.migration_execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "migration_execution_secrets" {
  name = "routing-migration-secrets"
  role = aws_iam_role.migration_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.migration_django.arn,
          aws_secretsmanager_secret.migration_jwt.arn,
          aws_secretsmanager_secret.database_migration_password.arn,
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = [aws_kms_key.routing.arn]
      }
    ]
  })
}

resource "aws_iam_role" "database_bootstrap_execution" {
  name_prefix = "${var.name}-routing-bootstrap-exec-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "database_bootstrap_execution" {
  role       = aws_iam_role.database_bootstrap_execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "database_bootstrap_execution_secrets" {
  name = "routing-database-bootstrap-secrets"
  role = aws_iam_role.database_bootstrap_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_db_instance.routing.master_user_secret[0].secret_arn,
          aws_secretsmanager_secret.database_password.arn,
          aws_secretsmanager_secret.database_migration_password.arn,
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = [aws_kms_key.routing.arn]
      }
    ]
  })
}

resource "aws_iam_role" "task" {
  name_prefix = "${var.name}-routing-task-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy" "task_metrics" {
  name = "routing-custom-metrics-only"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["cloudwatch:PutMetricData"]
      Resource = "*"
      Condition = {
        StringEquals = { "cloudwatch:namespace" = "82TA/Routing" }
      }
    }]
  })
}

resource "aws_ecs_task_definition" "routing" {
  family                   = "${var.name}-routing-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.cpu)
  memory                   = tostring(var.memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name                   = "routing-api"
    image                  = var.routing_image
    essential              = true
    user                   = "10002:10002"
    readonlyRootFilesystem = true
    portMappings           = [{ containerPort = 8000, hostPort = 8000, protocol = "tcp" }]
    environment = [
      { name = "ROUTING_RUNTIME_ENVIRONMENT", value = upper(var.environment) },
      { name = "ROUTING_PRIVATE_OPENAPI_PATH", value = "/app/src/contracts/openapi/routing-private.v1.yaml" },
      { name = "ROUTING_ALLOWED_HOSTS", value = var.routing_private_hostname },
      { name = "ROUTING_SECURE_SSL_REDIRECT", value = "true" },
      { name = "ROUTING_TRUST_X_FORWARDED_PROTO", value = "true" },
      { name = "ROUTING_SERVICE_JWT_ISSUER", value = "service-api" },
      { name = "ROUTING_SERVICE_JWT_AUDIENCE", value = "routing-api" },
      { name = "ROUTING_DB_NAME", value = "routing" },
      { name = "ROUTING_DB_USER", value = "routing_app" },
      { name = "ROUTING_DB_HOST", value = aws_db_instance.routing.address },
      { name = "ROUTING_DB_PORT", value = "5432" },
      { name = "ROUTING_DB_SSLMODE", value = "verify-full" },
      { name = "ROUTING_REDIS_URL", value = "rediss://${aws_elasticache_replication_group.routing.primary_endpoint_address}:6379/0" },
      { name = "ROUTING_BUILD_VERSION", value = var.routing_build_version },
      { name = "ROUTING_METRICS_NAMESPACE", value = "82TA/Routing" },
      { name = "ROUTING_METRICS_ENVIRONMENT", value = var.environment },
      { name = "ROUTING_PRODUCTION_DEPENDENCIES_FACTORY", value = var.production_dependencies_factory },
      { name = "ROUTING_PROVIDER_CONFIG_FACTORY", value = var.provider_config_factory },
      { name = "ROUTING_PROVIDER_EVIDENCE_JSON", value = var.provider_evidence_json },
      { name = "ROUTING_ALLOW_FIXTURE_BACKEND", value = "false" },
    ]
    secrets = concat(
      [
        { name = "ROUTING_DJANGO_SECRET_KEY", valueFrom = aws_secretsmanager_secret.django.arn },
        { name = "ROUTING_DB_PASSWORD", valueFrom = aws_secretsmanager_secret.database_password.arn },
        { name = "ROUTING_SERVICE_JWT_SECRET", valueFrom = var.shared_jwt_secret_arn },
      ],
      [for name, secret in aws_secretsmanager_secret.provider : { name = name, valueFrom = secret.arn }]
    )
    command = [
      "python", "-m", "gunicorn", "routing_deployment.wsgi:application",
      "--bind=0.0.0.0:8000", "--workers=2", "--threads=4", "--timeout=10",
      "--graceful-timeout=10", "--access-logfile", "/dev/null", "--error-logfile=-"
    ]
    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health/live', timeout=2).read()\" || exit 1"]
      interval    = 30
      timeout     = 3
      retries     = 3
      startPeriod = 30
    }
    linuxParameters = { initProcessEnabled = true }
    mountPoints     = [{ sourceVolume = "tmp", containerPath = "/tmp", readOnly = false }]
    volumesFrom     = []
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.routing.name
        awslogs-region        = data.aws_region.current.name
        awslogs-stream-prefix = "routing-api"
      }
    }
  }])

  volume { name = "tmp" }
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  tags = local.tags
}

resource "aws_ecs_task_definition" "database_bootstrap" {
  family                   = "${var.name}-routing-database-bootstrap"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.database_bootstrap_execution.arn

  container_definitions = jsonencode([{
    name                   = "routing-database-bootstrap"
    image                  = var.routing_image
    essential              = true
    user                   = "10002:10002"
    readonlyRootFilesystem = true
    environment = [
      { name = "ROUTING_TASK_MODE", value = "database-bootstrap" },
      { name = "ROUTING_DB_ADMIN_NAME", value = "routing" },
      { name = "ROUTING_DB_ADMIN_HOST", value = aws_db_instance.routing.address },
      { name = "ROUTING_DB_ADMIN_PORT", value = "5432" },
      { name = "ROUTING_DB_ADMIN_SSLMODE", value = "verify-full" },
      { name = "ROUTING_DB_APP_USER", value = "routing_app" },
      { name = "ROUTING_DB_MIGRATION_USER", value = "routing_migrator" },
      { name = "ROUTING_DB_BOOTSTRAP_ACTION", value = "prepare" },
    ]
    secrets = [
      {
        name      = "ROUTING_DB_ADMIN_USER"
        valueFrom = "${aws_db_instance.routing.master_user_secret[0].secret_arn}:username::"
      },
      {
        name      = "ROUTING_DB_ADMIN_PASSWORD"
        valueFrom = "${aws_db_instance.routing.master_user_secret[0].secret_arn}:password::"
      },
      {
        name      = "ROUTING_DB_APP_PASSWORD"
        valueFrom = aws_secretsmanager_secret.database_password.arn
      },
      {
        name      = "ROUTING_DB_MIGRATION_PASSWORD"
        valueFrom = aws_secretsmanager_secret.database_migration_password.arn
      },
    ]
    command         = ["python", "/opt/routing/database_bootstrap.py"]
    mountPoints     = [{ sourceVolume = "tmp", containerPath = "/tmp", readOnly = false }]
    volumesFrom     = []
    linuxParameters = { initProcessEnabled = true }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.routing.name
        awslogs-region        = data.aws_region.current.name
        awslogs-stream-prefix = "routing-database-bootstrap"
      }
    }
  }])

  volume { name = "tmp" }
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  tags = local.tags
}

resource "aws_ecs_task_definition" "migration" {
  family                   = "${var.name}-routing-migration"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.migration_execution.arn

  container_definitions = jsonencode([{
    name                   = "routing-migration"
    image                  = var.routing_image
    essential              = true
    user                   = "10002:10002"
    readonlyRootFilesystem = true
    environment = [
      { name = "ROUTING_TASK_MODE", value = "migration" },
      { name = "ROUTING_RUNTIME_ENVIRONMENT", value = upper(var.environment) },
      { name = "ROUTING_ALLOWED_HOSTS", value = var.routing_private_hostname },
      { name = "ROUTING_SECURE_SSL_REDIRECT", value = "true" },
      { name = "ROUTING_TRUST_X_FORWARDED_PROTO", value = "true" },
      { name = "ROUTING_SERVICE_JWT_ISSUER", value = "service-api" },
      { name = "ROUTING_SERVICE_JWT_AUDIENCE", value = "routing-api" },
      { name = "ROUTING_DB_NAME", value = "routing" },
      { name = "ROUTING_DB_USER", value = "routing_migrator" },
      { name = "ROUTING_DB_HOST", value = aws_db_instance.routing.address },
      { name = "ROUTING_DB_PORT", value = "5432" },
      { name = "ROUTING_DB_SSLMODE", value = "verify-full" },
      { name = "ROUTING_ALLOW_FIXTURE_BACKEND", value = "false" },
    ]
    secrets = [
      { name = "ROUTING_DJANGO_SECRET_KEY", valueFrom = aws_secretsmanager_secret.migration_django.arn },
      { name = "ROUTING_DB_PASSWORD", valueFrom = aws_secretsmanager_secret.database_migration_password.arn },
      { name = "ROUTING_SERVICE_JWT_SECRET", valueFrom = aws_secretsmanager_secret.migration_jwt.arn },
    ]
    command         = ["python", "manage.py", "migrate", "--noinput"]
    mountPoints     = [{ sourceVolume = "tmp", containerPath = "/tmp", readOnly = false }]
    volumesFrom     = []
    linuxParameters = { initProcessEnabled = true }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.routing.name
        awslogs-region        = data.aws_region.current.name
        awslogs-stream-prefix = "routing-migration"
      }
    }
  }])

  volume { name = "tmp" }
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  tags = local.tags
}

resource "aws_ecs_service" "routing" {
  name                               = "${var.name}-routing-api"
  cluster                            = var.ecs_cluster
  task_definition                    = aws_ecs_task_definition.routing.arn
  desired_count                      = var.routing_desired_count
  launch_type                        = "FARGATE"
  health_check_grace_period_seconds  = 60
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  enable_execute_command             = false
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = aws_subnet.routing[*].id
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.routing.arn
    container_name   = "routing-api"
    container_port   = 8000
  }
  depends_on = [aws_lb_listener.routing]
  tags       = local.tags
}

resource "aws_cloudwatch_metric_alarm" "routing_5xx" {
  alarm_name          = "${var.name}-routing-target-5xx"
  actions_enabled     = var.routing_desired_count > 0
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  dimensions          = { LoadBalancer = aws_lb.routing.arn_suffix }
  alarm_actions       = [var.alarm_sns_topic_arn]
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "routing_p95_deadline" {
  alarm_name          = "${var.name}-routing-p95-over-6-5s"
  actions_enabled     = var.routing_desired_count > 0
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  extended_statistic  = "p95"
  threshold           = 6.5
  treat_missing_data  = "breaching"
  dimensions          = { LoadBalancer = aws_lb.routing.arn_suffix }
  alarm_actions       = [var.alarm_sns_topic_arn]
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "routing_deadline_exhausted" {
  alarm_name          = "${var.name}-routing-deadline-exhausted"
  actions_enabled     = var.routing_desired_count > 0
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "DeadlineExceededCount"
  namespace           = "82TA/Routing"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "breaching"
  dimensions          = { Environment = var.environment }
  alarm_actions       = [var.alarm_sns_topic_arn]
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "routing_provider_429" {
  alarm_name          = "${var.name}-routing-provider-429"
  actions_enabled     = var.routing_desired_count > 0
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ProviderRateLimitedCount"
  namespace           = "82TA/Routing"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "breaching"
  dimensions          = { Environment = var.environment }
  alarm_actions       = [var.alarm_sns_topic_arn]
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "routing_partial_rate" {
  alarm_name          = "${var.name}-routing-partial-rate"
  actions_enabled     = var.routing_desired_count > 0
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "PartialResponseRate"
  namespace           = "82TA/Routing"
  period              = 300
  statistic           = "Average"
  threshold           = 0.20
  treat_missing_data  = "breaching"
  dimensions          = { Environment = var.environment }
  alarm_actions       = [var.alarm_sns_topic_arn]
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "routing_provider_quota" {
  alarm_name          = "${var.name}-routing-provider-quota"
  actions_enabled     = var.routing_desired_count > 0
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ProviderQuotaUtilization"
  namespace           = "82TA/Routing"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0.80
  treat_missing_data  = "breaching"
  dimensions          = { Environment = var.environment }
  alarm_actions       = [var.alarm_sns_topic_arn]
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "routing_provider_daily_cost" {
  alarm_name          = "${var.name}-routing-provider-daily-cost"
  actions_enabled     = var.routing_desired_count > 0
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ProviderCostUsd"
  namespace           = "82TA/Routing"
  period              = 86400
  statistic           = "Sum"
  threshold           = var.provider_daily_cost_alarm_usd
  treat_missing_data  = "breaching"
  dimensions          = { Environment = var.environment }
  alarm_actions       = [var.alarm_sns_topic_arn]
  tags                = local.tags
}

resource "aws_iam_role" "github_deploy" {
  count       = local.create_github_role ? 1 : 0
  name_prefix = "${var.name}-routing-github-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = var.github_oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike   = { "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:environment:${var.github_environment}" }
      }
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy" "github_deploy" {
  count = local.create_github_role ? 1 : 0
  name  = "immutable-routing-deploy"
  role  = aws_iam_role.github_deploy[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ecr:BatchCheckLayerAvailability", "ecr:CompleteLayerUpload", "ecr:GetDownloadUrlForLayer", "ecr:InitiateLayerUpload", "ecr:PutImage", "ecr:UploadLayerPart"]
        Resource = aws_ecr_repository.routing.arn
      },
      {
        Effect   = "Allow"
        Action   = ["ecs:DescribeTaskDefinition"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ecs:DescribeServices"]
        Resource = local.routing_service_arn
      },
      {
        Effect   = "Allow"
        Action   = ["ecs:UpdateService"]
        Resource = local.routing_service_arn
        Condition = {
          ArnEquals                   = { "ecs:cluster" = local.ecs_cluster_arn }
          ArnLike                     = { "ecs:task-definition" = local.routing_task_definition_arn }
          "ForAllValues:StringEquals" = { "ecs:subnet" = aws_subnet.routing[*].id }
          StringEquals = {
            "ecs:auto-assign-public-ip"  = "DISABLED"
            "ecs:enable-execute-command" = "false"
          }
          Null = { "ecs:subnet" = "false" }
        }
      }
    ]
  })
}

resource "aws_iam_role" "github_database_bootstrap" {
  count       = local.create_github_database_role ? 1 : 0
  name_prefix = "${var.name}-routing-database-github-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = var.github_oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike   = { "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:environment:${var.github_database_environment}" }
      }
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy" "github_database_bootstrap" {
  count = local.create_github_database_role ? 1 : 0
  name  = "routing-database-bootstrap"
  role  = aws_iam_role.github_database_bootstrap[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # ECS does not support resource-level authorization for this read action.
        Effect   = "Allow"
        Action   = ["ecs:DescribeTaskDefinition"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = ["ecs:RunTask"]
        Resource = [
          local.bootstrap_task_definition_arn,
          local.migration_task_definition_arn,
        ]
        Condition = {
          ArnEquals                   = { "ecs:cluster" = local.ecs_cluster_arn }
          "ForAllValues:StringEquals" = { "ecs:subnet" = aws_subnet.routing[*].id }
          StringEquals = {
            "ecs:auto-assign-public-ip"  = "DISABLED"
            "ecs:enable-execute-command" = "false"
          }
          Null = { "ecs:subnet" = "false" }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["ecs:DescribeTasks"]
        Resource = local.routing_task_arn
      },
      {
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = [
          aws_iam_role.database_bootstrap_execution.arn,
          aws_iam_role.migration_execution.arn,
        ]
        Condition = { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } }
      }
    ]
  })
}
