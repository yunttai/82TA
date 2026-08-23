# Terraform deployment

`modules/service-platform` is a coherent Service-only stack: two-AZ VPC,
private app/data subnets, CloudFront OAC and private S3 PWA hosting, WAF,
CloudFront-only public ALB ingress, ECS Fargate, a Service-owned RDS database,
TLS ElastiCache, KMS/Secrets Manager, ECR, logs, alarms, autoscaling, a
KMS-encrypted EFS access point plus EventBridge/SQS lifecycle workers, and an
optional environment-scoped GitHub OIDC deploy role. It creates no Routing
compute or Routing database. HTTP Routing mode accepts only an HTTPS private
URL and an explicit exact-host allowlist.

Initialize staging with a separately bootstrapped encrypted state bucket and
lock table:

```bash
cd src/infra/terraform/environments/staging
cp backend.hcl.example backend.hcl
cp terraform.tfvars.example terraform.tfvars
terraform init -backend-config=backend.hcl
terraform plan
```

Terraform creates secret containers but deliberately creates no secret values.
Before the first ECS task starts, populate the Django secret, Kakao REST key,
and dedicated data-rights artifact Fernet key ARNs from
`application_secret_arns`; populate the Routing token only for HTTP mode. RDS
owns and rotates its master password in Secrets Manager. The
container startup adapter combines that password with non-secret RDS endpoint
fields into `DATABASE_URL` in process memory; neither the password nor URL is
written to Terraform state or disk.

The ECS task uses the backend's production Redis contract directly:
`SERVICE_REDIS_URL=rediss://<private-primary-endpoint>:6379/0`, TLS-enabled
ElastiCache, a bounded key prefix, a 250 ms fail-closed socket timeout, a
120-second rate bucket TTL, a 15-second in-flight idempotency lease, and a
600-second completed-response TTL. Route search, guest-session creation, and
place lookup retain the backend defaults of 60, 10, and 60 requests per trusted
client IP per minute. Terraform validates commercially bounded ranges rather
than permitting the previous effectively-disabled value of one million.

These application limits are independent of the WAF five-minute per-IP limits
(120 route searches, 100 guest sessions, and 300 place requests by default).
The effective ceiling is whichever layer rejects first. WAF protects spend and
origin capacity before Django; Django/Redis supplies atomic cross-task behavior
using the proxy-validated client IP and fails closed with a public 429 when
coordination is unavailable. Tune one layer at a time using safe aggregate 429,
WAF block, latency, and provider-cost metrics; never log tokens, Redis keys,
search inputs, or coordinates.

`SERVICE_TRUSTED_PROXY_IPS` is rendered from the stack's ALB subnet CIDRs plus
the current CIDRs in AWS's CloudFront origin-facing managed prefix list. This
matches Django's reverse X-Forwarded-For traversal: ALB and CloudFront are
skipped, the viewer address appended by CloudFront is selected, and any forged
viewer-supplied values farther left are ignored. No arbitrary public range or
viewer-controlled dedicated IP header is trusted.

The Service DBML uses `geography`, so the Service RDS schema requires PostGIS
even though Bus/Routing data remains in the other bounded context. The approved
Service migration must include idempotent extension creation; Terraform never
edits application tables. See `src/infra/aws/STAGING_RUNBOOK.md` for the
one-off migration gate, rollback, restore, and credential prerequisites.
That runbook also defines the mandatory data export/deletion worker drill.

Staging intentionally uses one NAT gateway and a non-Multi-AZ RDS instance for
cost control while retaining two-AZ subnet placement and two Redis nodes.
Production must use a distinct state/account, Multi-AZ RDS, deletion
protection, redundant egress, budgets, SNS alarm actions, a public Route 53
zone with dedicated ALB origin name and regional ACM certificate, and a
us-east-1 ACM certificate when a custom viewer domain is used.
