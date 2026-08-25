output "instance_name" {
  value = module.gce_platform.instance_name
}

output "instance_zone" {
  value = module.gce_platform.instance_zone
}

output "external_ip" {
  value = module.gce_platform.external_ip
}

output "runtime_service_account" {
  value = module.gce_platform.runtime_service_account
}

output "model_artifact_bucket" {
  value = module.gce_platform.model_artifact_bucket
}
