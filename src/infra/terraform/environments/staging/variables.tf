variable "aws_region" {
  type    = string
  default = "ap-northeast-2"
}

variable "availability_zones" {
  type    = list(string)
  default = ["ap-northeast-2a", "ap-northeast-2c"]
}

variable "service_image" {
  description = "Initial immutable Service image URI. CI registers later revisions by digest."
  type        = string
}

variable "service_desired_count" {
  description = "Keep zero for the first apply; set to two after secret values and migration readiness are verified."
  type        = number
  default     = 0
}

variable "routing_enabled" {
  description = "Create the private Routing stack. Keep false until image, secrets, DB role, certificate, and provider evidence are ready."
  type        = bool
  default     = false
}

variable "routing_image" {
  description = "Immutable Routing image URI by digest. Required when routing_enabled=true."
  type        = string
  default     = ""
  validation {
    condition     = !var.routing_enabled || can(regex("@sha256:[0-9a-f]{64}$", var.routing_image))
    error_message = "routing_image must use an immutable sha256 digest when Routing is enabled."
  }
}

variable "routing_desired_count" {
  description = "Keep zero through secret/DB migration/readiness gates; use at least two for staging SLO evidence."
  type        = number
  default     = 0
}

variable "routing_private_hostname" {
  description = "Private Route 53 name covered by the internal ALB certificate."
  type        = string
  default     = "routing.staging.internal"
}

variable "routing_private_zone_id" {
  description = "Private Route 53 hosted zone associated with the platform VPC."
  type        = string
  default     = ""
}

variable "routing_certificate_arn" {
  description = "Regional ACM/private-CA certificate for routing_private_hostname."
  type        = string
  default     = ""
}

variable "routing_production_dependencies_factory" {
  description = "Reviewed dependency factory; empty keeps readiness unavailable/all-false."
  type        = string
  default     = "routing_deployment.baseline:build_dependencies"
}

variable "routing_provider_config_factory" {
  type    = string
  default = "provider_core.production:build_kakao_baseline_config"
}

variable "routing_provider_evidence_json" {
  description = "Approved non-secret evidence document. Keep {} until schema/key/terms/production approval is current."
  type        = string
  default     = "{}"
}

variable "routing_provider_firewall_endpoint_ids" {
  description = "Map each availability zone to an audited AWS Network Firewall VPC endpoint ID."
  type        = map(string)
  default     = {}
}

variable "routing_build_version" {
  type    = string
  default = "routing-api-foundation-0.1.0"
}

variable "consent_document_version" {
  description = "Published policy version shared by the Django task and Vite build."
  type        = string
}

variable "domain_names" {
  type    = list(string)
  default = []
}

variable "cloudfront_certificate_arn" {
  type    = string
  default = ""
}

variable "alb_certificate_arn" {
  type    = string
  default = ""
}

variable "alb_origin_domain_name" {
  type    = string
  default = ""
}

variable "route53_zone_id" {
  type    = string
  default = ""
}

variable "routing_gateway_mode" {
  type    = string
  default = "stub"
}

variable "routing_api_base_url" {
  type    = string
  default = ""
}

variable "routing_api_allowed_hosts" {
  type    = list(string)
  default = []
}

variable "service_rate_limit_per_minute" {
  type    = number
  default = 60
}

variable "service_guest_session_rate_limit_per_minute" {
  type    = number
  default = 10
}

variable "service_place_rate_limit_per_minute" {
  type    = number
  default = 60
}

variable "redis_key_prefix" {
  type    = string
  default = "82ta:service:1.1"
}

variable "redis_socket_timeout_seconds" {
  type    = number
  default = 0.25
}

variable "rate_limit_cache_ttl_seconds" {
  type    = number
  default = 120
}

variable "idempotency_cache_ttl_seconds" {
  type    = number
  default = 600
}

variable "idempotency_lease_seconds" {
  type    = number
  default = 15
}

variable "github_repository" {
  type    = string
  default = ""
}

variable "github_oidc_provider_arn" {
  type    = string
  default = ""
}

variable "alarm_sns_topic_arn" {
  description = "Encrypted on-call SNS topic for CloudWatch and AWS Budget alarms."
  type        = string
}
