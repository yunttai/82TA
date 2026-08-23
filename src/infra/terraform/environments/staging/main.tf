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
  routing_api_base_url                        = var.routing_api_base_url
  routing_api_allowed_hosts                   = var.routing_api_allowed_hosts
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
