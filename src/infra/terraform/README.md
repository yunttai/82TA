# GCE Terraform deployment

`modules/gce-platform` provisions the cloud resources used by the implemented
blank-GCE-host deployment:

- custom VPC/subnet and static regional external IP;
- inbound 80/443 and explicitly supplied SSH source CIDRs;
- Shielded GCE VM with OS Login and a dedicated runtime service account;
- logging/monitoring writer roles only;
- private, uniform-access, versioned Cloud Storage bucket for Routing model/data
  artifacts, with runtime read-only access;
- no service-account key, application secret value or database credential.

Terraform intentionally leaves a blank VM. The active CD workflow uploads
`gce/bootstrap-host.sh` together with its companion refresh script, runs it through
the reviewed non-root OS Login user's `sudo`, then uploads Compose/Nginx and deploys
images. Terraform does not embed application scripts or secrets in instance metadata
and does not pretend that current Compose development flags or Service SQLite are
production-ready.

Bootstrap a versioned GCS bucket for state outside this stack, then run:

```bash
cd src/infra/terraform/environments/staging
cp backend.hcl.example backend.hcl
cp terraform.tfvars.example terraform.tfvars
terraform init -backend-config=backend.hcl
terraform plan
```

Use Application Default Credentials or workload identity. Never place a JSON
service-account key, provider key, SSH private key, Terraform credential or secret
value in `*.tfvars`, backend configuration, startup metadata or state.

Production promotion is an environment decision, not a new cloud target. Enable
deletion protection, restricted deployment ingress, backups/restores, alerting,
cost budgets and the required managed or replicated data services before claiming
production readiness. The exact Google managed-service topology may evolve without
changing the mandatory GCE compute-platform decision.
