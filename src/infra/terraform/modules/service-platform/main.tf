data "aws_region" "current" {}
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

locals {
  common_tags = merge(var.tags, {
    Application = "82ta-service-product"
    Environment = var.github_environment
    ManagedBy   = "terraform"
  })
  az_count           = length(var.availability_zones)
  use_custom_domain  = length(var.domain_names) > 0
  create_github_role = var.github_repository != "" && var.github_oidc_provider_arn != ""
  service_secret_arns = concat(
    [
      aws_secretsmanager_secret.django.arn,
      aws_secretsmanager_secret.kakao_local.arn,
      aws_secretsmanager_secret.data_rights_artifact_key.arn,
    ],
    var.routing_gateway_mode == "http" ? [aws_secretsmanager_secret.routing_token.arn] : []
  )
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.common_tags, { Name = "${var.name}-vpc" })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.common_tags, { Name = "${var.name}-igw" })
}

resource "aws_subnet" "public" {
  count                   = local.az_count
  vpc_id                  = aws_vpc.this.id
  availability_zone       = var.availability_zones[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  map_public_ip_on_launch = false
  tags                    = merge(local.common_tags, { Name = "${var.name}-public-${count.index + 1}", Tier = "public" })
}

resource "aws_subnet" "app" {
  count             = local.az_count
  vpc_id            = aws_vpc.this.id
  availability_zone = var.availability_zones[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, 32 + count.index)
  tags              = merge(local.common_tags, { Name = "${var.name}-app-${count.index + 1}", Tier = "private-app" })
}

resource "aws_subnet" "data" {
  count             = local.az_count
  vpc_id            = aws_vpc.this.id
  availability_zone = var.availability_zones[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, 64 + count.index)
  tags              = merge(local.common_tags, { Name = "${var.name}-data-${count.index + 1}", Tier = "private-data" })
}

# One NAT gateway is intentional for staging cost control. Production should use
# one per AZ or an approved egress proxy before changing the environment gate.
resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = merge(local.common_tags, { Name = "${var.name}-nat-eip" })
}

resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  depends_on    = [aws_internet_gateway.this]
  tags          = merge(local.common_tags, { Name = "${var.name}-nat" })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
  tags = merge(local.common_tags, { Name = "${var.name}-public" })
}

resource "aws_route_table_association" "public" {
  count          = local.az_count
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "app" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this.id
  }
  tags = merge(local.common_tags, { Name = "${var.name}-app" })
}

resource "aws_route_table_association" "app" {
  count          = local.az_count
  subnet_id      = aws_subnet.app[count.index].id
  route_table_id = aws_route_table.app.id
}

resource "aws_route_table" "data" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.common_tags, { Name = "${var.name}-data" })
}

resource "aws_route_table_association" "data" {
  count          = local.az_count
  subnet_id      = aws_subnet.data[count.index].id
  route_table_id = aws_route_table.data.id
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.name}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.app.id, aws_route_table.data.id]
  tags              = local.common_tags
}

resource "aws_kms_key" "platform" {
  description             = "${var.name} Service Product data, secret, and log encryption"
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
      },
      {
        Sid       = "CloudFrontWebAssetDecryption"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = ["kms:Decrypt", "kms:DescribeKey"]
        Resource  = "*"
        Condition = {
          StringEquals = { "AWS:SourceAccount" = data.aws_caller_identity.current.account_id }
          ArnLike      = { "AWS:SourceArn" = "arn:${data.aws_partition.current.partition}:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/*" }
        }
      }
    ]
  })
  tags = local.common_tags
}

resource "aws_kms_alias" "platform" {
  name          = "alias/${var.name}-service-product"
  target_key_id = aws_kms_key.platform.key_id
}

resource "aws_kms_key" "waf_logs" {
  provider                = aws.us_east_1
  description             = "${var.name} CloudFront WAF logs"
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
        Principal = { Service = "logs.us-east-1.amazonaws.com" }
        Action    = ["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
        Resource  = "*"
        Condition = {
          ArnLike = { "kms:EncryptionContext:aws:logs:arn" = "arn:${data.aws_partition.current.partition}:logs:us-east-1:${data.aws_caller_identity.current.account_id}:log-group:aws-waf-logs-*" }
        }
      }
    ]
  })
  tags = local.common_tags
}

resource "aws_ecr_repository" "service" {
  name                 = "${var.name}/service-api"
  image_tag_mutability = "IMMUTABLE"
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.platform.arn
  }
  image_scanning_configuration { scan_on_push = true }
  tags = local.common_tags
}

resource "aws_ecr_lifecycle_policy" "service" {
  repository = aws_ecr_repository.service.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Retain the newest 30 immutable images for rollback"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 30
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_s3_bucket" "web" {
  bucket_prefix = "${var.name}-web-"
  force_destroy = false
  tags          = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "web" {
  bucket = aws_s3_bucket.web.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.platform.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 30 }
  }
}

resource "aws_security_group" "alb" {
  name_prefix = "${var.name}-alb-"
  description = "CloudFront origin-facing traffic only"
  vpc_id      = aws_vpc.this.id
  tags        = local.common_tags
}

resource "aws_vpc_security_group_ingress_rule" "alb_cloudfront" {
  security_group_id = aws_security_group.alb.id
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  description       = "CloudFront origin-facing managed prefix list"
}

resource "aws_vpc_security_group_egress_rule" "alb_service" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.service.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}

resource "aws_security_group" "service" {
  name_prefix = "${var.name}-service-"
  description = "Private Service API tasks"
  vpc_id      = aws_vpc.this.id
  tags        = local.common_tags
}

resource "aws_vpc_security_group_ingress_rule" "service_alb" {
  security_group_id            = aws_security_group.service.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "service_https" {
  security_group_id = aws_security_group.service.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  description       = "Kakao Local, AWS APIs, and private Routing TLS endpoint"
}

resource "aws_vpc_security_group_egress_rule" "service_database" {
  security_group_id            = aws_security_group.service.id
  referenced_security_group_id = aws_security_group.database.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "service_redis" {
  security_group_id            = aws_security_group.service.id
  referenced_security_group_id = aws_security_group.redis.id
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
}

resource "aws_lb" "service" {
  name                       = substr(replace("${var.name}-service", "_", "-"), 0, 32)
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = aws_subnet.public[*].id
  enable_deletion_protection = var.deletion_protection
  drop_invalid_header_fields = true
  # ALB request logs include the query string, including reverse-geocode
  # coordinates. Use redacted WAF logs and application path/status metrics.
  tags = local.common_tags
}

resource "aws_lb_target_group" "service" {
  name_prefix          = "82svc-"
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.this.id
  deregistration_delay = 30
  health_check {
    enabled             = true
    path                = "/infra/healthz"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
  tags = local.common_tags
}

resource "aws_lb_listener" "service" {
  load_balancer_arn = aws_lb.service.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.alb_certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.service.arn
  }
}

resource "aws_route53_record" "alb_origin" {
  zone_id = var.route53_zone_id
  name    = var.alb_origin_domain_name
  type    = "A"
  alias {
    name                   = aws_lb.service.dns_name
    zone_id                = aws_lb.service.zone_id
    evaluate_target_health = true
  }
}

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "${var.name}-web"
  description                       = "SigV4 access to private Service Product web assets"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_function" "spa" {
  name    = replace("${var.name}-spa", "_", "-")
  runtime = "cloudfront-js-2.0"
  comment = "Route extensionless non-API paths to the React shell"
  publish = true
  code    = <<-JS
    function handler(event) {
      var request = event.request;
      if (!request.uri.startsWith('/api/') && !request.uri.includes('.')) {
        request.uri = '/index.html';
      }
      return request;
    }
  JS
}

resource "aws_cloudfront_response_headers_policy" "security" {
  name = replace("${var.name}-security", "_", "-")
  security_headers_config {
    content_security_policy {
      content_security_policy = var.csp
      override                = true
    }
    content_type_options { override = true }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = true
      override                   = true
    }
  }
  custom_headers_config {
    items {
      header   = "Permissions-Policy"
      value    = "geolocation=(self), camera=(), microphone=()"
      override = true
    }
  }
}

resource "aws_wafv2_web_acl" "this" {
  provider    = aws.us_east_1
  name        = "${var.name}-edge"
  description = "Managed baseline and Denial-of-Wallet rate control"
  scope       = "CLOUDFRONT"
  default_action {
    allow {}
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${replace(var.name, "-", "_")}_edge"
    sampled_requests_enabled   = false
  }
  rule {
    name     = "aws-common"
    priority = 10
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aws_common"
      sampled_requests_enabled   = false
    }
  }
  rule {
    name     = "ip-rate-limit"
    priority = 20
    action {
      block {}
    }
    statement {
      rate_based_statement {
        aggregate_key_type = "IP"
        limit              = var.web_acl_rate_limit
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "ip_rate_limit"
      sampled_requests_enabled   = false
    }
  }
  rule {
    name     = "place-ip-rate-limit"
    priority = 30
    action {
      block {}
    }
    statement {
      rate_based_statement {
        aggregate_key_type = "IP"
        limit              = var.place_rate_limit
        scope_down_statement {
          byte_match_statement {
            positional_constraint = "STARTS_WITH"
            search_string         = "/api/v1/places/"
            field_to_match {
              uri_path {}
            }
            text_transformation {
              priority = 0
              type     = "NONE"
            }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "place_ip_rate_limit"
      sampled_requests_enabled   = false
    }
  }
  rule {
    name     = "guest-session-ip-rate-limit"
    priority = 40
    action {
      block {}
    }
    statement {
      rate_based_statement {
        aggregate_key_type = "IP"
        limit              = var.guest_session_rate_limit
        scope_down_statement {
          byte_match_statement {
            positional_constraint = "STARTS_WITH"
            search_string         = "/api/v1/guest-sessions"
            field_to_match {
              uri_path {}
            }
            text_transformation {
              priority = 0
              type     = "NONE"
            }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "guest_session_ip_rate_limit"
      sampled_requests_enabled   = false
    }
  }
  rule {
    name     = "route-search-ip-rate-limit"
    priority = 50
    action {
      block {}
    }
    statement {
      rate_based_statement {
        aggregate_key_type = "IP"
        limit              = var.route_search_rate_limit
        scope_down_statement {
          byte_match_statement {
            positional_constraint = "STARTS_WITH"
            search_string         = "/api/v1/route-searches"
            field_to_match {
              uri_path {}
            }
            text_transformation {
              priority = 0
              type     = "NONE"
            }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "route_search_ip_rate_limit"
      sampled_requests_enabled   = false
    }
  }
  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "waf" {
  provider          = aws.us_east_1
  name              = "aws-waf-logs-${var.name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.waf_logs.arn
  tags              = local.common_tags
}

resource "aws_wafv2_web_acl_logging_configuration" "this" {
  provider                = aws.us_east_1
  resource_arn            = aws_wafv2_web_acl.this.arn
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]
  redacted_fields {
    single_header { name = "authorization" }
  }
  redacted_fields {
    single_header { name = "cookie" }
  }
  redacted_fields {
    single_header { name = "x-guest-token" }
  }
  redacted_fields {
    single_header { name = "x-csrftoken" }
  }
  redacted_fields {
    query_string {}
  }
}

resource "aws_cloudfront_distribution" "web" {
  enabled             = true
  is_ipv6_enabled     = true
  aliases             = var.domain_names
  default_root_object = "index.html"
  price_class         = "PriceClass_200"
  web_acl_id          = aws_wafv2_web_acl.this.arn
  http_version        = "http2and3"
  origin {
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_id                = "web-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }
  origin {
    domain_name = var.alb_origin_domain_name
    origin_id   = "service-alb"
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }
  default_cache_behavior {
    target_origin_id           = "web-s3"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD", "OPTIONS"]
    compress                   = true
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6"
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa.arn
    }
  }
  ordered_cache_behavior {
    path_pattern               = "/api/*"
    target_origin_id           = "service-alb"
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods             = ["GET", "HEAD", "OPTIONS"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_except_host.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }
  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate {
    cloudfront_default_certificate = !local.use_custom_domain
    acm_certificate_arn            = local.use_custom_domain ? var.cloudfront_certificate_arn : null
    ssl_support_method             = local.use_custom_domain ? "sni-only" : null
    minimum_protocol_version       = local.use_custom_domain ? "TLSv1.2_2021" : "TLSv1"
  }
  depends_on = [aws_lb_listener.service]
  tags       = local.common_tags

  lifecycle {
    precondition {
      condition     = !local.use_custom_domain || var.cloudfront_certificate_arn != ""
      error_message = "cloudfront_certificate_arn is required when domain_names is non-empty."
    }
    precondition {
      condition     = var.alb_certificate_arn != "" && var.alb_origin_domain_name != "" && var.route53_zone_id != ""
      error_message = "A regional ALB certificate, matching origin DNS name, and Route 53 zone are required; plaintext CloudFront-to-ALB is forbidden."
    }
    precondition {
      condition = var.routing_gateway_mode != "http" || (
        startswith(var.routing_api_base_url, "https://") && length(var.routing_api_allowed_hosts) > 0
      )
      error_message = "HTTP Routing mode requires an https:// private base URL and exact allowed host list."
    }
  }
}

resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontReadOnly"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.web.arn}/*"
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.web.arn } }
    }]
  })
}

resource "aws_security_group" "database" {
  name_prefix = "${var.name}-db-"
  description = "Service DB accepts only Service API tasks"
  vpc_id      = aws_vpc.this.id
  tags        = local.common_tags
}

resource "aws_vpc_security_group_ingress_rule" "database_service" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.service.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_db_subnet_group" "service" {
  name       = "${var.name}-service"
  subnet_ids = aws_subnet.data[*].id
  tags       = local.common_tags
}

resource "aws_db_instance" "service" {
  identifier                      = "${var.name}-service"
  engine                          = "postgres"
  engine_version                  = var.postgres_engine_version
  instance_class                  = var.rds_instance_class
  allocated_storage               = 30
  max_allocated_storage           = 100
  storage_type                    = "gp3"
  storage_encrypted               = true
  kms_key_id                      = aws_kms_key.platform.arn
  db_name                         = "service"
  username                        = "service_admin"
  manage_master_user_password     = true
  master_user_secret_kms_key_id   = aws_kms_key.platform.key_id
  db_subnet_group_name            = aws_db_subnet_group.service.name
  vpc_security_group_ids          = [aws_security_group.database.id]
  publicly_accessible             = false
  multi_az                        = var.rds_multi_az
  backup_retention_period         = 7
  backup_window                   = "18:00-19:00"
  maintenance_window              = "sun:19:00-sun:20:00"
  auto_minor_version_upgrade      = true
  deletion_protection             = var.deletion_protection
  skip_final_snapshot             = false
  final_snapshot_identifier       = "${var.name}-service-final"
  performance_insights_enabled    = true
  performance_insights_kms_key_id = aws_kms_key.platform.arn
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
  tags = merge(local.common_tags, {
    DataOwner       = "service-product"
    PostGISRequired = "true"
  })
}

resource "aws_security_group" "redis" {
  name_prefix = "${var.name}-redis-"
  description = "Service Redis accepts only Service API tasks"
  vpc_id      = aws_vpc.this.id
  tags        = local.common_tags
}

resource "aws_vpc_security_group_ingress_rule" "redis_service" {
  security_group_id            = aws_security_group.redis.id
  referenced_security_group_id = aws_security_group.service.id
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
}

resource "aws_elasticache_subnet_group" "service" {
  name       = "${var.name}-service"
  subnet_ids = aws_subnet.data[*].id
}

resource "aws_elasticache_replication_group" "service" {
  replication_group_id       = "${var.name}-service"
  description                = "Service rate-limit and idempotency cache"
  node_type                  = var.redis_node_type
  port                       = 6379
  engine                     = "redis"
  engine_version             = "7.1"
  num_cache_clusters         = 2
  automatic_failover_enabled = true
  multi_az_enabled           = true
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  kms_key_id                 = aws_kms_key.platform.arn
  subnet_group_name          = aws_elasticache_subnet_group.service.name
  security_group_ids         = [aws_security_group.redis.id]
  snapshot_retention_limit   = 3
  apply_immediately          = false
  tags                       = local.common_tags
}

resource "aws_secretsmanager_secret" "django" {
  name                    = "${var.name}/service/django-secret-key"
  kms_key_id              = aws_kms_key.platform.arn
  recovery_window_in_days = 30
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret" "kakao_local" {
  name                    = "${var.name}/service/kakao-local-rest-key"
  kms_key_id              = aws_kms_key.platform.arn
  recovery_window_in_days = 30
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret" "routing_token" {
  name                    = "${var.name}/service/routing-token"
  description             = "Shared HS256 signing secret for Service-to-Routing JWT authentication"
  kms_key_id              = aws_kms_key.platform.arn
  recovery_window_in_days = 30
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret" "data_rights_artifact_key" {
  name                    = "${var.name}/service/data-rights-artifact-fernet-key"
  description             = "Fernet key for short-lived Service data export artifacts"
  kms_key_id              = aws_kms_key.platform.arn
  recovery_window_in_days = 30
  tags                    = local.common_tags
}

resource "aws_security_group" "data_rights_efs" {
  name_prefix = "${var.name}-data-rights-efs-"
  description = "Encrypted data-rights export filesystem accepts only Service tasks"
  vpc_id      = aws_vpc.this.id
  tags        = local.common_tags
}

resource "aws_vpc_security_group_ingress_rule" "data_rights_efs_service" {
  security_group_id            = aws_security_group.data_rights_efs.id
  referenced_security_group_id = aws_security_group.service.id
  from_port                    = 2049
  to_port                      = 2049
  ip_protocol                  = "tcp"
}

resource "aws_efs_file_system" "data_rights" {
  creation_token   = "${var.name}-data-rights"
  encrypted        = true
  kms_key_id       = aws_kms_key.platform.arn
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"

  lifecycle_policy {
    transition_to_ia = "AFTER_7_DAYS"
  }

  tags = merge(local.common_tags, {
    DataClassification = "restricted-personal-export"
    Retention          = "application-enforced-short-lived"
  })
}

resource "aws_efs_backup_policy" "data_rights" {
  file_system_id = aws_efs_file_system.data_rights.id
  # Export artifacts are reproducible and have a 15-minute application TTL.
  # Backing them up would silently extend the privacy retention window.
  backup_policy { status = "DISABLED" }
}

resource "aws_efs_mount_target" "data_rights" {
  count           = local.az_count
  file_system_id  = aws_efs_file_system.data_rights.id
  subnet_id       = aws_subnet.data[count.index].id
  security_groups = [aws_security_group.data_rights_efs.id]
}

resource "aws_efs_access_point" "data_rights" {
  file_system_id = aws_efs_file_system.data_rights.id

  posix_user {
    uid = 10001
    gid = 10001
  }

  root_directory {
    path = "/exports"
    creation_info {
      owner_uid   = 10001
      owner_gid   = 10001
      permissions = "0700"
    }
  }

  tags = local.common_tags
}

resource "aws_efs_file_system_policy" "data_rights" {
  file_system_id = aws_efs_file_system.data_rights.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyUnencryptedTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "elasticfilesystem:Client*"
        Resource  = aws_efs_file_system.data_rights.arn
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        Sid       = "AllowServiceTaskAccessPoint"
        Effect    = "Allow"
        Principal = { AWS = aws_iam_role.service_task.arn }
        Action    = ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite"]
        Resource  = aws_efs_file_system.data_rights.arn
        Condition = {
          StringEquals = { "elasticfilesystem:AccessPointArn" = aws_efs_access_point.data_rights.arn }
        }
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "service" {
  name              = "/ecs/${var.name}/service-api"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.platform.arn
  tags              = local.common_tags
}

resource "aws_iam_role" "ecs_execution" {
  name = "${var.name}-ecs-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name = "read-service-startup-secrets"
  role = aws_iam_role.ecs_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = concat(local.service_secret_arns, [aws_db_instance.service.master_user_secret[0].secret_arn])
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = [aws_kms_key.platform.arn]
      }
    ]
  })
}

resource "aws_iam_role" "service_task" {
  name = "${var.name}-service-task"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy" "service_task_data_rights_efs" {
  name = "data-rights-artifact-filesystem"
  role = aws_iam_role.service_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite"]
      Resource = aws_efs_file_system.data_rights.arn
      Condition = {
        StringEquals = { "elasticfilesystem:AccessPointArn" = aws_efs_access_point.data_rights.arn }
      }
    }]
  })
}

resource "aws_ecs_cluster" "this" {
  name = var.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = local.common_tags
}

resource "aws_ecs_task_definition" "service" {
  family                   = "${var.name}-service-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.service_cpu)
  memory                   = tostring(var.service_memory)
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.service_task.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  container_definitions = jsonencode([{
    name                   = "service-api"
    image                  = var.service_image
    essential              = true
    readonlyRootFilesystem = true
    user                   = "10001:10001"
    portMappings = [{
      containerPort = 8000
      hostPort      = 8000
      protocol      = "tcp"
      name          = "http"
    }]
    environment = [
      { name = "SERVICE_ENVIRONMENT", value = "production" },
      { name = "SERVICE_DEBUG", value = "false" },
      { name = "SERVICE_CONSENT_DOCUMENT_VERSION", value = var.consent_document_version },
      { name = "SERVICE_ALLOWED_HOSTS", value = join(",", concat(var.domain_names, [aws_cloudfront_distribution.web.domain_name, var.alb_origin_domain_name, aws_lb.service.dns_name])) },
      { name = "SERVICE_CSRF_TRUSTED_ORIGINS", value = join(",", concat(["https://${aws_cloudfront_distribution.web.domain_name}"], [for domain in var.domain_names : "https://${domain}"])) },
      { name = "SERVICE_ROUTING_GATEWAY", value = var.routing_gateway_mode },
      { name = "SERVICE_ROUTING_API_BASE_URL", value = var.routing_api_base_url },
      { name = "SERVICE_ROUTING_API_ALLOWED_HOSTS", value = join(",", var.routing_api_allowed_hosts) },
      { name = "SERVICE_ROUTING_VERIFY_SSL", value = "true" },
      { name = "SERVICE_ROUTING_JWT_ISSUER", value = "service-api" },
      { name = "SERVICE_ROUTING_JWT_AUDIENCE", value = "routing-api" },
      { name = "SERVICE_ROUTING_JWT_TTL_SECONDS", value = "60" },
      { name = "SERVICE_PUBLIC_ROUTE_SEARCH_BUDGET_MILLISECONDS", value = "7000" },
      { name = "SERVICE_ROUTING_DEADLINE_MILLISECONDS", value = "6500" },
      { name = "SERVICE_TRUST_PROXY_HEADERS", value = "true" },
      # Django resolves X-Forwarded-For from the nearest untrusted hop. Trust
      # exactly the ALB subnet nodes and AWS-managed CloudFront origin-facing
      # ranges so the reverse walk skips ALB+CloudFront and selects the viewer
      # address CloudFront appended. Viewer-supplied values remain to its left
      # and cannot override that boundary.
      { name = "SERVICE_TRUSTED_PROXY_IPS", value = join(",", concat(aws_subnet.public[*].cidr_block, sort([for entry in data.aws_ec2_managed_prefix_list.cloudfront.entries : entry.cidr]))) },
      { name = "SERVICE_RATE_LIMIT_PER_MINUTE", value = tostring(var.service_rate_limit_per_minute) },
      { name = "SERVICE_GUEST_SESSION_RATE_LIMIT_PER_MINUTE", value = tostring(var.service_guest_session_rate_limit_per_minute) },
      { name = "SERVICE_PLACE_RATE_LIMIT_PER_MINUTE", value = tostring(var.service_place_rate_limit_per_minute) },
      { name = "SERVICE_DATABASE_HOST", value = aws_db_instance.service.address },
      { name = "SERVICE_DATABASE_PORT", value = tostring(aws_db_instance.service.port) },
      { name = "SERVICE_DATABASE_NAME", value = aws_db_instance.service.db_name },
      { name = "SERVICE_DATABASE_USER", value = aws_db_instance.service.username },
      { name = "SERVICE_REDIS_URL", value = "rediss://${aws_elasticache_replication_group.service.primary_endpoint_address}:6379/0" },
      { name = "SERVICE_REDIS_KEY_PREFIX", value = var.redis_key_prefix },
      { name = "SERVICE_REDIS_SOCKET_TIMEOUT_SECONDS", value = tostring(var.redis_socket_timeout_seconds) },
      { name = "SERVICE_RATE_LIMIT_CACHE_TTL_SECONDS", value = tostring(var.rate_limit_cache_ttl_seconds) },
      { name = "SERVICE_IDEMPOTENCY_CACHE_TTL_SECONDS", value = tostring(var.idempotency_cache_ttl_seconds) },
      { name = "SERVICE_IDEMPOTENCY_LEASE_SECONDS", value = tostring(var.idempotency_lease_seconds) },
      { name = "SERVICE_DATA_RIGHTS_ARTIFACT_BACKEND", value = "encrypted-filesystem" },
      { name = "SERVICE_DATA_RIGHTS_ARTIFACT_DIRECTORY", value = "/var/lib/service-data-rights" },
      { name = "SERVICE_DATA_RIGHTS_EXPORT_TTL_SECONDS", value = "900" }
    ]
    secrets = concat(
      [
        { name = "SERVICE_SECRET_KEY", valueFrom = aws_secretsmanager_secret.django.arn },
        { name = "KAKAO_REST_API_KEY", valueFrom = aws_secretsmanager_secret.kakao_local.arn },
        { name = "SERVICE_DATABASE_PASSWORD", valueFrom = "${aws_db_instance.service.master_user_secret[0].secret_arn}:password::" },
        { name = "SERVICE_DATA_RIGHTS_ARTIFACT_ENCRYPTION_KEY", valueFrom = aws_secretsmanager_secret.data_rights_artifact_key.arn }
      ],
      var.routing_gateway_mode == "http" ? [{ name = "SERVICE_ROUTING_JWT_SECRET", valueFrom = aws_secretsmanager_secret.routing_token.arn }] : []
    )
    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/infra/healthz', timeout=2).read()\" || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }
    linuxParameters = { initProcessEnabled = true }
    mountPoints = [
      {
        sourceVolume  = "tmp"
        containerPath = "/tmp"
        readOnly      = false
      },
      {
        sourceVolume  = "data-rights-artifacts"
        containerPath = "/var/lib/service-data-rights"
        readOnly      = false
      }
    ]
    volumesFrom = []
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.service.name
        awslogs-region        = data.aws_region.current.name
        awslogs-stream-prefix = "service"
      }
    }
  }])
  volume { name = "tmp" }
  volume {
    name = "data-rights-artifacts"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.data_rights.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.data_rights.id
        iam             = "ENABLED"
      }
    }
  }
  lifecycle {
    precondition {
      condition     = var.idempotency_cache_ttl_seconds > var.idempotency_lease_seconds
      error_message = "idempotency_cache_ttl_seconds must exceed idempotency_lease_seconds."
    }
  }
  tags = local.common_tags
}

resource "aws_ecs_service" "service" {
  name                               = "service-api"
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.service.arn
  desired_count                      = var.service_desired_count
  launch_type                        = "FARGATE"
  platform_version                   = "LATEST"
  health_check_grace_period_seconds  = 60
  enable_execute_command             = false
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    assign_public_ip = false
    subnets          = aws_subnet.app[*].id
    security_groups  = [aws_security_group.service.id]
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.service.arn
    container_name   = "service-api"
    container_port   = 8000
  }
  depends_on = [aws_lb_listener.service]
  tags       = local.common_tags
}

resource "aws_sqs_queue" "data_rights_dead_letter" {
  name                      = "${var.name}-data-rights-dead-letter"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
  tags                      = local.common_tags
}

resource "aws_cloudwatch_event_rule" "process_data_rights_jobs" {
  name                = "${var.name}-process-data-rights-jobs"
  description         = "Process bounded Service export and deletion jobs every five minutes"
  schedule_expression = "rate(5 minutes)"
  state               = "ENABLED"
  tags                = local.common_tags
}

resource "aws_cloudwatch_event_rule" "purge_service_data" {
  name                = "${var.name}-purge-service-data"
  description         = "Apply Service retention and artifact expiry every hour"
  schedule_expression = "rate(1 hour)"
  state               = "ENABLED"
  tags                = local.common_tags
}

resource "aws_iam_role" "data_rights_scheduler" {
  name = "${var.name}-data-rights-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy" "data_rights_scheduler" {
  name = "run-bounded-service-lifecycle-tasks"
  role = aws_iam_role.data_rights_scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = aws_ecs_task_definition.service.arn
        Condition = {
          ArnEquals = { "ecs:cluster" = aws_ecs_cluster.this.arn }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.ecs_execution.arn, aws_iam_role.service_task.arn]
        Condition = {
          StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.data_rights_dead_letter.arn
      }
    ]
  })
}

resource "aws_sqs_queue_policy" "data_rights_dead_letter" {
  queue_url = aws_sqs_queue.data_rights_dead_letter.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.data_rights_dead_letter.arn
      Condition = {
        ArnEquals = {
          "aws:SourceArn" = [
            aws_cloudwatch_event_rule.process_data_rights_jobs.arn,
            aws_cloudwatch_event_rule.purge_service_data.arn,
          ]
        }
      }
    }]
  })
}

resource "aws_cloudwatch_event_target" "process_data_rights_jobs" {
  rule     = aws_cloudwatch_event_rule.process_data_rights_jobs.name
  arn      = aws_ecs_cluster.this.arn
  role_arn = aws_iam_role.data_rights_scheduler.arn
  input = jsonencode({
    containerOverrides = [{
      name    = "service-api"
      command = ["python", "manage.py", "process_data_rights_jobs", "--limit", "100"]
    }]
  })

  ecs_target {
    task_definition_arn     = aws_ecs_task_definition.service.arn
    launch_type             = "FARGATE"
    platform_version        = "LATEST"
    task_count              = 1
    enable_execute_command  = false
    enable_ecs_managed_tags = true
    network_configuration {
      assign_public_ip = false
      subnets          = aws_subnet.app[*].id
      security_groups  = [aws_security_group.service.id]
    }
  }

  dead_letter_config { arn = aws_sqs_queue.data_rights_dead_letter.arn }
  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 3
  }
}

resource "aws_cloudwatch_event_target" "purge_service_data" {
  rule     = aws_cloudwatch_event_rule.purge_service_data.name
  arn      = aws_ecs_cluster.this.arn
  role_arn = aws_iam_role.data_rights_scheduler.arn
  input = jsonencode({
    containerOverrides = [{
      name    = "service-api"
      command = ["python", "manage.py", "purge_service_data"]
    }]
  })

  ecs_target {
    task_definition_arn     = aws_ecs_task_definition.service.arn
    launch_type             = "FARGATE"
    platform_version        = "LATEST"
    task_count              = 1
    enable_execute_command  = false
    enable_ecs_managed_tags = true
    network_configuration {
      assign_public_ip = false
      subnets          = aws_subnet.app[*].id
      security_groups  = [aws_security_group.service.id]
    }
  }

  dead_letter_config { arn = aws_sqs_queue.data_rights_dead_letter.arn }
  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 3
  }
}

resource "aws_cloudwatch_metric_alarm" "data_rights_scheduler_failures" {
  alarm_name          = "${var.name}-data-rights-scheduler-failures"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alarm_sns_topic_arn]
  ok_actions          = [var.alarm_sns_topic_arn]
  dimensions = {
    QueueName = aws_sqs_queue.data_rights_dead_letter.name
  }
  tags = local.common_tags
}

resource "aws_appautoscaling_target" "service" {
  max_capacity       = 8
  min_capacity       = var.service_desired_count == 0 ? 0 : 2
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.service.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "service_cpu" {
  name               = "${var.name}-service-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.service.resource_id
  scalable_dimension = aws_appautoscaling_target.service.scalable_dimension
  service_namespace  = aws_appautoscaling_target.service.service_namespace
  target_tracking_scaling_policy_configuration {
    target_value       = 60
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
    predefined_metric_specification { predefined_metric_type = "ECSServiceAverageCPUUtilization" }
  }
}

resource "aws_cloudwatch_metric_alarm" "service_5xx" {
  alarm_name          = "${var.name}-service-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alarm_sns_topic_arn]
  ok_actions          = [var.alarm_sns_topic_arn]
  dimensions = {
    LoadBalancer = aws_lb.service.arn_suffix
    TargetGroup  = aws_lb_target_group.service.arn_suffix
  }
  tags = local.common_tags
}

resource "aws_budgets_budget" "staging" {
  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 80
    threshold_type            = "PERCENTAGE"
    notification_type         = "FORECASTED"
    subscriber_sns_topic_arns = [var.alarm_sns_topic_arn]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 100
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [var.alarm_sns_topic_arn]
  }

  tags = local.common_tags
}

resource "aws_iam_role" "github_deploy" {
  count = local.create_github_role ? 1 : 0
  name  = "${var.name}-github-deploy"
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
  tags = local.common_tags
}

resource "aws_iam_role_policy" "github_deploy" {
  count = local.create_github_role ? 1 : 0
  name  = "immutable-service-product-deploy"
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
        Resource = aws_ecr_repository.service.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:DeleteObject", "s3:GetObject", "s3:ListBucket", "s3:PutObject"]
        Resource = [aws_s3_bucket.web.arn, "${aws_s3_bucket.web.arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["cloudfront:CreateInvalidation"]
        Resource = aws_cloudfront_distribution.web.arn
      },
      {
        Effect   = "Allow"
        Action   = ["ecs:DescribeServices", "ecs:DescribeTaskDefinition", "ecs:DescribeTasks", "ecs:RegisterTaskDefinition", "ecs:RunTask", "ecs:UpdateService"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"]
        Resource = aws_kms_key.platform.arn
      },
      {
        Effect    = "Allow"
        Action    = ["iam:PassRole"]
        Resource  = [aws_iam_role.ecs_execution.arn, aws_iam_role.service_task.arn]
        Condition = { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } }
      }
    ]
  })
}
