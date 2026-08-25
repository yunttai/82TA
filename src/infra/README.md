# Service and Routing infrastructure

GCE is the required cloud deployment platform. This directory contains the
implemented single-VM deployment and its cloud provisioning support; it does not
maintain a second cloud target or dual-cloud parity.

- `gce/`: blank-host bootstrap, Docker Compose, Nginx and operational notes
- `terraform/`: GCE VM, VPC/subnet, static IP, firewall, runtime service account
  and private/versioned Cloud Storage artifact bucket
- `docker/`: non-root images plus local and Service→Routing E2E Compose topologies
- `ci/github-actions/`: inert PR validation template only
- `.github/workflows/cd-gce.yml`: the sole active cloud deploy workflow
- `scripts/validate_infra.py`: structural, Terraform and Compose validation

The GCE deployment preserves browser → Service → private Routing and keeps the
two database ownership domains separate. The current single-VM Compose settings
include development/demo choices; they are an implementation fact, not a
production-readiness claim.

```bash
python src/infra/scripts/validate_infra.py
```

A cloud apply requires a Google Cloud project, a globally unique Cloud Storage
bucket name, a reviewed SSH source CIDR, domain/DNS, GCE OS Login access and the
GitHub `gce` environment secrets listed in `gce/README.md`. No cloud credential
or secret value is stored in Terraform state or this repository.
