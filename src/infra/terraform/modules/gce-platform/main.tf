locals {
  resource_name = "${var.name}-${var.environment}"
  labels = merge(
    {
      application = var.name
      environment = var.environment
      managed_by  = "terraform"
    },
    var.labels,
  )
}

resource "google_project_service" "required" {
  for_each = toset([
    "compute.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "storage.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_compute_network" "platform" {
  project                 = var.project_id
  name                    = local.resource_name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.required]
}

resource "google_compute_subnetwork" "platform" {
  project                  = var.project_id
  name                     = local.resource_name
  region                   = var.region
  network                  = google_compute_network.platform.id
  ip_cidr_range            = var.network_cidr
  private_ip_google_access = true
}

resource "google_compute_firewall" "web" {
  project = var.project_id
  name    = "${local.resource_name}-web"
  network = google_compute_network.platform.name

  direction     = "INGRESS"
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["${local.resource_name}-web"]

  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
}

resource "google_compute_firewall" "ssh" {
  project = var.project_id
  name    = "${local.resource_name}-ssh"
  network = google_compute_network.platform.name

  direction     = "INGRESS"
  source_ranges = var.ssh_source_ranges
  target_tags   = ["${local.resource_name}-ssh"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_address" "platform" {
  project = var.project_id
  name    = local.resource_name
  region  = var.region
}

resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "svc-${var.name}-${substr(var.environment, 0, 10)}"
  display_name = "${local.resource_name} GCE runtime"
}

resource "google_project_iam_member" "runtime_observability" {
  for_each = toset([
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket" "model_artifacts" {
  project                     = var.project_id
  name                        = var.model_artifact_bucket_name
  location                    = var.storage_location
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.labels

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      num_newer_versions = 10
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket_iam_member" "runtime_model_reader" {
  bucket = google_storage_bucket.model_artifacts.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_compute_instance" "platform" {
  project      = var.project_id
  name         = local.resource_name
  zone         = var.zone
  machine_type = var.machine_type
  tags         = ["${local.resource_name}-web", "${local.resource_name}-ssh"]
  labels       = local.labels

  allow_stopping_for_update = true
  deletion_protection       = var.deletion_protection

  boot_disk {
    auto_delete = true
    initialize_params {
      image = var.source_image
      size  = var.boot_disk_size_gb
      type  = "pd-balanced"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.platform.id
    access_config {
      nat_ip = google_compute_address.platform.address
    }
  }

  metadata = {
    block-project-ssh-keys = "TRUE"
    enable-oslogin         = "TRUE"
    serial-port-enable     = "FALSE"
  }

  service_account {
    email  = google_service_account.runtime.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE"
    preemptible         = false
    provisioning_model  = "STANDARD"
  }

  depends_on = [
    google_project_iam_member.runtime_observability,
    google_storage_bucket_iam_member.runtime_model_reader,
  ]
}
