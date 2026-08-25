variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "asia-northeast3"
}

variable "zone" {
  type    = string
  default = "asia-northeast3-a"
}

variable "machine_type" {
  type    = string
  default = "e2-standard-4"
}

variable "ssh_source_ranges" {
  type = list(string)
}

variable "model_artifact_bucket_name" {
  type = string
}

variable "deletion_protection" {
  type    = bool
  default = false
}
