variable "project_id" {
  description = "Google Cloud project that owns the required GCE deployment."
  type        = string
}

variable "name" {
  description = "Stable resource prefix."
  type        = string
  default     = "ta82"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}[a-z0-9]$", var.name))
    error_message = "name must be a valid lowercase Google Cloud resource prefix."
  }
}

variable "environment" {
  type    = string
  default = "staging"
  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "environment must be development, staging, or production."
  }
}

variable "region" {
  type    = string
  default = "asia-northeast3"
}

variable "zone" {
  type    = string
  default = "asia-northeast3-a"
}

variable "network_cidr" {
  type    = string
  default = "10.82.0.0/24"
}

variable "machine_type" {
  type    = string
  default = "e2-standard-4"
}

variable "source_image" {
  description = "Reviewed GCE image or image-family URI."
  type        = string
  default     = "projects/debian-cloud/global/images/family/debian-12"
}

variable "boot_disk_size_gb" {
  type    = number
  default = 80
  validation {
    condition     = var.boot_disk_size_gb >= 30
    error_message = "boot_disk_size_gb must be at least 30 GiB."
  }
}

variable "ssh_source_ranges" {
  description = "Explicit CIDRs allowed to reach SSH. Supply fixed deploy-runner or bastion ranges; no implicit public range is added."
  type        = list(string)
  validation {
    condition     = length(var.ssh_source_ranges) > 0
    error_message = "At least one reviewed SSH source range is required for the current SSH deployment workflow."
  }
}

variable "model_artifact_bucket_name" {
  description = "Globally unique Cloud Storage bucket for immutable Routing data/model artifacts."
  type        = string
}

variable "storage_location" {
  type    = string
  default = "ASIA-NORTHEAST3"
}

variable "deletion_protection" {
  type    = bool
  default = false
}

variable "labels" {
  type    = map(string)
  default = {}
}
