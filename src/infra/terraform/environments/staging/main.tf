module "gce_platform" {
  source = "../../modules/gce-platform"

  project_id                 = var.project_id
  name                       = "ta82"
  environment                = "staging"
  region                     = var.region
  zone                       = var.zone
  machine_type               = var.machine_type
  ssh_source_ranges          = var.ssh_source_ranges
  model_artifact_bucket_name = var.model_artifact_bucket_name
  deletion_protection        = var.deletion_protection
  labels = {
    owner       = "platform"
    cost_center = "82ta-staging"
  }
}
