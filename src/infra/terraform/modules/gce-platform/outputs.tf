output "instance_name" {
  value = google_compute_instance.platform.name
}

output "instance_zone" {
  value = google_compute_instance.platform.zone
}

output "external_ip" {
  value = google_compute_address.platform.address
}

output "network_name" {
  value = google_compute_network.platform.name
}

output "runtime_service_account" {
  value = google_service_account.runtime.email
}

output "model_artifact_bucket" {
  value = google_storage_bucket.model_artifacts.url
}
