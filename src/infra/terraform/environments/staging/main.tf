module "service_product" {
  source = "../../modules/service-platform"
  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }

  name                                        = "82ta-staging"
  availability_zones                          = var.availability_zones
  service_image                               = var.service_image
  service_desired_count                       = var.service_desired_count
  consent_document_version                    = var.consent_document_version
  domain_names                                = var.domain_names
  cloudfront_certificate_arn                  = var.cloudfront_certificate_arn
  alb_certificate_arn                         = var.alb_certificate_arn
  alb_origin_domain_name                      = var.alb_origin_domain_name
  route53_zone_id                             = var.route53_zone_id
  routing_gateway_mode                        = var.routing_gateway_mode
  routing_api_base_url                        = var.routing_enabled && var.routing_gateway_mode == "http" ? "https://${var.routing_private_hostname}" : var.routing_api_base_url
  routing_api_allowed_hosts                   = var.routing_enabled && var.routing_gateway_mode == "http" ? [var.routing_private_hostname] : var.routing_api_allowed_hosts
  service_rate_limit_per_minute               = var.service_rate_limit_per_minute
  service_guest_session_rate_limit_per_minute = var.service_guest_session_rate_limit_per_minute
  service_place_rate_limit_per_minute         = var.service_place_rate_limit_per_minute
  redis_key_prefix                            = var.redis_key_prefix
  redis_socket_timeout_seconds                = var.redis_socket_timeout_seconds
  rate_limit_cache_ttl_seconds                = var.rate_limit_cache_ttl_seconds
  idempotency_cache_ttl_seconds               = var.idempotency_cache_ttl_seconds
  idempotency_lease_seconds                   = var.idempotency_lease_seconds
  github_repository                           = var.github_repository
  github_oidc_provider_arn                    = var.github_oidc_provider_arn
  github_environment                          = "staging"
  alarm_sns_topic_arn                         = var.alarm_sns_topic_arn
  rds_multi_az                                = false
  deletion_protection                         = false

  tags = {
    CostCenter = "82ta-staging"
    Owner      = "service-product"
  }
}

check "service_routing_deployment_coherence" {
  assert {
    condition = var.service_desired_count == 0 || (
      var.routing_enabled &&
      var.routing_gateway_mode == "http" &&
      var.routing_desired_count > 0
    )
    error_message = "A running production Service requires an enabled/running private Routing stack and HTTP gateway mode."
  }
}

module "routing_intelligence" {
  count  = var.routing_enabled ? 1 : 0
  source = "../../modules/routing-platform"

  name                            = "82ta-staging"
  environment                     = "staging"
  vpc_id                          = module.service_product.vpc_id
  vpc_cidr                        = module.service_product.vpc_cidr
  availability_zones              = var.availability_zones
  data_subnet_ids                 = module.service_product.data_subnet_ids
  public_route_table_id           = module.service_product.public_route_table_id
  service_security_group_id       = module.service_product.service_security_group_id
  provider_firewall_endpoint_ids  = var.routing_provider_firewall_endpoint_ids
  ecs_cluster                     = module.service_product.ecs_cluster
  shared_jwt_secret_arn           = module.service_product.routing_auth_secret_arn
  shared_kms_key_arn              = module.service_product.platform_kms_key_arn
  routing_image                   = var.routing_image
  routing_desired_count           = var.routing_desired_count
  routing_private_hostname        = var.routing_private_hostname
  routing_private_zone_id         = var.routing_private_zone_id
  routing_certificate_arn         = var.routing_certificate_arn
  production_dependencies_factory = var.routing_production_dependencies_factory
  provider_config_factory         = var.routing_provider_config_factory
  provider_evidence_json          = var.routing_provider_evidence_json
  routing_build_version           = var.routing_build_version
  alarm_sns_topic_arn             = var.alarm_sns_topic_arn
  github_repository               = var.github_repository
  github_oidc_provider_arn        = var.github_oidc_provider_arn
  github_environment              = "staging"
  github_database_environment     = "staging-routing-database"
  rds_multi_az                    = false
  deletion_protection             = false

  tags = {
    CostCenter = "82ta-staging"
    Owner      = "routing-intelligence"
  }
}
