variable "name" {
  description = "Short platform name used for resource names."
  type        = string
  default     = "82ta-staging"
}

variable "vpc_cidr" {
  type    = string
  default = "10.82.0.0/16"
}

variable "availability_zones" {
  description = "Exactly two or more AZs; subnet CIDRs are derived by position."
  type        = list(string)

  validation {
    condition     = length(var.availability_zones) >= 2
    error_message = "At least two availability zones are required."
  }
}

variable "service_image" {
  description = "Immutable Service API image URI, preferably addressed by sha256 digest."
  type        = string
}

variable "service_desired_count" {
  type    = number
  default = 2
}

variable "service_cpu" {
  type    = number
  default = 512
}

variable "service_memory" {
  type    = number
  default = 1024
}

variable "consent_document_version" {
  description = "Published current consent/privacy document version; the Web build must use the identical value."
  type        = string

  validation {
    condition     = trimspace(var.consent_document_version) != ""
    error_message = "consent_document_version is required and must match VITE_PRIVACY_DOCUMENT_VERSION."
  }
}

variable "routing_gateway_mode" {
  type    = string
  default = "stub"

  validation {
    condition     = contains(["stub", "replay", "http"], var.routing_gateway_mode)
    error_message = "routing_gateway_mode must be stub, replay, or http."
  }
}

variable "routing_api_base_url" {
  description = "Private Routing URL. Required by policy when routing_gateway_mode=http."
  type        = string
  default     = ""
}

variable "routing_api_allowed_hosts" {
  description = "Exact private Routing hostnames accepted by the Service SSRF guard; no CIDRs or wildcards."
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for host in var.routing_api_allowed_hosts :
      host != "" && !strcontains(host, "*") && !strcontains(host, "/") && !strcontains(host, ":")
    ])
    error_message = "Routing allowed hosts must be exact hostnames without scheme, port, path, or wildcard."
  }
}

variable "guest_session_rate_limit" {
  description = "Five-minute WAF limit for guest-session creation per source IP."
  type        = number
  default     = 100
}

variable "place_rate_limit" {
  description = "Five-minute WAF limit for place lookup per source IP."
  type        = number
  default     = 300
}

variable "route_search_rate_limit" {
  description = "Five-minute WAF limit for route-search traffic per source IP."
  type        = number
  default     = 120
}

variable "service_rate_limit_per_minute" {
  description = "Django/Redis route-search limit per trusted client IP and one-minute window."
  type        = number
  default     = 60

  validation {
    condition     = var.service_rate_limit_per_minute >= 1 && var.service_rate_limit_per_minute <= 600
    error_message = "service_rate_limit_per_minute must be between 1 and 600."
  }
}

variable "service_guest_session_rate_limit_per_minute" {
  description = "Django/Redis guest-session creation limit per trusted client IP and one-minute window."
  type        = number
  default     = 10

  validation {
    condition     = var.service_guest_session_rate_limit_per_minute >= 1 && var.service_guest_session_rate_limit_per_minute <= 120
    error_message = "service_guest_session_rate_limit_per_minute must be between 1 and 120."
  }
}

variable "service_place_rate_limit_per_minute" {
  description = "Django/Redis place lookup limit per trusted client IP and one-minute window."
  type        = number
  default     = 60

  validation {
    condition     = var.service_place_rate_limit_per_minute >= 1 && var.service_place_rate_limit_per_minute <= 1200
    error_message = "service_place_rate_limit_per_minute must be between 1 and 1200."
  }
}

variable "redis_key_prefix" {
  description = "Non-secret namespace for Service coordination keys."
  type        = string
  default     = "82ta:service:1.1"

  validation {
    condition     = can(regex("^[A-Za-z0-9:._-]{1,64}$", var.redis_key_prefix))
    error_message = "redis_key_prefix must be 1-64 safe namespace characters."
  }
}

variable "redis_socket_timeout_seconds" {
  description = "Fail-closed Redis coordination connect/read timeout."
  type        = number
  default     = 0.25

  validation {
    condition     = var.redis_socket_timeout_seconds > 0 && var.redis_socket_timeout_seconds <= 5
    error_message = "redis_socket_timeout_seconds must be greater than 0 and at most 5."
  }
}

variable "rate_limit_cache_ttl_seconds" {
  description = "Redis rate bucket TTL; must cover the one-minute application window."
  type        = number
  default     = 120

  validation {
    condition     = var.rate_limit_cache_ttl_seconds >= 60 && var.rate_limit_cache_ttl_seconds <= 3600
    error_message = "rate_limit_cache_ttl_seconds must be between 60 and 3600."
  }
}

variable "idempotency_cache_ttl_seconds" {
  description = "Completed route-search idempotency response TTL in Redis."
  type        = number
  default     = 600

  validation {
    condition     = var.idempotency_cache_ttl_seconds >= 60 && var.idempotency_cache_ttl_seconds <= 86400
    error_message = "idempotency_cache_ttl_seconds must be between 60 and 86400."
  }
}

variable "idempotency_lease_seconds" {
  description = "In-flight route-search idempotency lease; must exceed the 6.5-second Routing deadline."
  type        = number
  default     = 15

  validation {
    condition     = var.idempotency_lease_seconds >= 7 && var.idempotency_lease_seconds <= 300
    error_message = "idempotency_lease_seconds must be between 7 and 300."
  }
}

variable "domain_names" {
  description = "Optional CloudFront aliases. Keep empty to use the generated distribution domain."
  type        = list(string)
  default     = []
}

variable "cloudfront_certificate_arn" {
  description = "us-east-1 ACM certificate for domain_names."
  type        = string
  default     = ""
}

variable "alb_certificate_arn" {
  description = "Regional ACM certificate matching alb_origin_domain_name. Required."
  type        = string
  default     = ""
}

variable "alb_origin_domain_name" {
  description = "DNS name pointing to the public ALB; its regional ACM certificate is validated by CloudFront."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Public Route 53 zone used to alias alb_origin_domain_name to the ALB."
  type        = string
  default     = ""
}

variable "web_acl_rate_limit" {
  description = "Five-minute request ceiling per source IP at the CloudFront edge."
  type        = number
  default     = 600
}

variable "csp" {
  description = "CloudFront Content-Security-Policy. Update only after testing the domain-restricted Kakao JS key."
  type        = string
  default     = "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; script-src 'self' https://dapi.kakao.com https://t1.daumcdn.net; connect-src 'self' https://dapi.kakao.com; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; worker-src 'self'; manifest-src 'self'"
}

variable "postgres_engine_version" {
  type    = string
  default = "16.4"
}

variable "rds_instance_class" {
  type    = string
  default = "db.t4g.small"
}

variable "rds_multi_az" {
  type    = bool
  default = false
}

variable "deletion_protection" {
  description = "Enable for production; staging keeps deletion possible while retaining final snapshots."
  type        = bool
  default     = false
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "alarm_sns_topic_arn" {
  description = "Pre-existing encrypted on-call SNS topic for service and cost alarms."
  type        = string

  validation {
    condition     = startswith(var.alarm_sns_topic_arn, "arn:")
    error_message = "alarm_sns_topic_arn is required for staging alarm delivery."
  }
}

variable "monthly_budget_usd" {
  description = "Staging monthly cost budget; tune after measured usage."
  type        = number
  default     = 300
}

variable "github_repository" {
  description = "org/repository allowed to assume the optional deploy role."
  type        = string
  default     = ""
}

variable "github_environment" {
  type    = string
  default = "staging"
}

variable "github_oidc_provider_arn" {
  description = "Pre-existing account-wide token.actions.githubusercontent.com OIDC provider ARN."
  type        = string
  default     = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
