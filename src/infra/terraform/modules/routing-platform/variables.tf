variable "name" { type = string }
variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "vpc_cidr" { type = string }
variable "availability_zones" { type = list(string) }
variable "data_subnet_ids" { type = list(string) }
variable "public_route_table_id" { type = string }
variable "service_security_group_id" { type = string }
variable "provider_firewall_endpoint_ids" {
  description = "AZ to externally governed AWS Network Firewall endpoint. Dedicated Routing subnet default routes use only these endpoints."
  type        = map(string)
}
variable "ecs_cluster" { type = string }
variable "shared_jwt_secret_arn" { type = string }
variable "shared_kms_key_arn" { type = string }
variable "routing_image" { type = string }
variable "routing_desired_count" {
  type    = number
  default = 0
  validation {
    condition     = var.routing_desired_count >= 0 && var.routing_desired_count <= 20
    error_message = "routing_desired_count must be between 0 and 20."
  }
}
variable "routing_private_hostname" {
  type = string
  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9.-]{1,251}[A-Za-z0-9]$", var.routing_private_hostname))
    error_message = "routing_private_hostname must be an explicit private DNS hostname."
  }
}
variable "routing_private_zone_id" { type = string }
variable "routing_certificate_arn" {
  type = string
  validation {
    condition     = startswith(var.routing_certificate_arn, "arn:")
    error_message = "routing_certificate_arn must be a regional ACM certificate ARN."
  }
}
variable "production_dependencies_factory" {
  description = "Reviewed zero-argument factory as dotted.module:callable. Empty is fail-closed unavailable/all-false."
  type        = string
  default     = ""
  validation {
    condition = var.production_dependencies_factory == "" || can(regex(
      "^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$",
      var.production_dependencies_factory
    ))
    error_message = "production_dependencies_factory must be empty or dotted.module:callable."
  }
}
variable "provider_config_factory" {
  description = "Reviewed ProviderConfig factory."
  type        = string
  default     = "provider_core.production:build_kakao_baseline_config"
  validation {
    condition = can(regex(
      "^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$",
      var.provider_config_factory
    ))
    error_message = "provider_config_factory must be dotted.module:callable."
  }
}
variable "provider_evidence_json" {
  description = "Non-secret, reviewed Provider runtime evidence JSON. Empty object activates no capability."
  type        = string
  default     = "{}"
  validation {
    condition     = can(jsondecode(var.provider_evidence_json))
    error_message = "provider_evidence_json must be valid JSON."
  }
}
variable "routing_build_version" { type = string }
variable "cpu" {
  type    = number
  default = 2048
}
variable "memory" {
  type    = number
  default = 4096
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
variable "redis_node_type" {
  type    = string
  default = "cache.t4g.micro"
}
variable "deletion_protection" {
  type    = bool
  default = false
}
variable "log_retention_days" {
  type    = number
  default = 30
}
variable "alarm_sns_topic_arn" { type = string }
variable "github_repository" {
  type    = string
  default = ""
}
variable "github_environment" {
  type    = string
  default = "staging"
}
variable "github_database_environment" {
  description = "Separately protected GitHub Environment allowed to run Routing DB bootstrap and migration tasks."
  type        = string
  default     = ""
}
variable "github_oidc_provider_arn" {
  type    = string
  default = ""
}
variable "provider_daily_cost_alarm_usd" {
  description = "Daily aggregate Provider spend alarm threshold from the Routing custom metric."
  type        = number
  default     = 20
  validation {
    condition     = var.provider_daily_cost_alarm_usd > 0
    error_message = "provider_daily_cost_alarm_usd must be positive."
  }
}
variable "tags" {
  type    = map(string)
  default = {}
}
