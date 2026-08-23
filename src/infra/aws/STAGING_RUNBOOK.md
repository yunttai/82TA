# Service Product staging runbook

This runbook deploys only the public React/Django bounded context. It does not
create, migrate, or inspect Routing compute, the Routing DB, providers, ranking,
or the Bus Intelligence engine.

## Account prerequisites

The first plan is blocked until an operator supplies:

1. AWS account ID, `ap-northeast-2` deployment role, and an account-wide GitHub
   OIDC provider.
2. An encrypted/versioned Terraform state bucket and lock table created by a
   separate bootstrap stack.
   Also supply an encrypted on-call SNS topic ARN for service and 80% forecast/
   100% actual monthly AWS Budget alarms.
3. A digest-addressed initial Service image. Use `service_desired_count=0` for
   the first infrastructure apply.
4. A dedicated origin DNS name (for example `origin-api.staging.example.com`)
   in a supplied public Route 53 zone plus a matching regional ACM certificate.
   Terraform creates the ALB alias record. HTTPS from
   CloudFront to ALB is mandatory so Django receives a trusted
   `X-Forwarded-Proto=https`; plaintext origin mode is rejected. A custom
   viewer domain is optional, but if used it needs a us-east-1 CloudFront ACM
   certificate. The generated CloudFront viewer domain works without that
   second certificate.
5. Secret values for the Terraform-created Django, Kakao REST, and data-rights
   artifact Fernet-key secret containers. Generate the Fernet key from an
   approved workstation; do not reuse the Django key. HTTP Routing additionally needs a short-lived service token,
   an exact private DNS hostname allowlist, and an HTTPS private Routing URL.
   Never paste secret values into Terraform variables, CLI arguments, GitHub
   variables, tickets, or this repository.
6. A domain-restricted Kakao JavaScript key and a published privacy document
   version. Set that exact value in Terraform `consent_document_version`, ECS
   `SERVICE_CONSENT_DOCUMENT_VERSION`, and the protected GitHub
   `PRIVACY_DOCUMENT_VERSION` used as `VITE_PRIVACY_DOCUMENT_VERSION`; the
   deployment fails closed on mismatch.

Use `aws secretsmanager put-secret-value --secret-id <arn>
--secret-string file://<protected-file>` from an audited workstation, then
delete the protected input file. Terraform intentionally creates no
`aws_secretsmanager_secret_version` and therefore stores no credential value.

## Bootstrap and boundary checks

1. Apply staging with desired count zero.
2. Confirm S3 Block Public Access and CloudFront OAC, RDS `PubliclyAccessible`
   false, ECS `AssignPublicIp` false, and data subnets without a default route.
3. Confirm the public ALB accepts only the AWS CloudFront origin-facing prefix
   list. There is no Routing listener or Routing task in this stack.
4. Confirm WAF query-string redaction, disabled sampled requests, and separate
   edge limits for place, guest-session, and route-search paths.
   Confirm the rendered ECS task uses application/Redis limits of 60 route
   searches, 10 guest-session creations, and 60 place requests per trusted
   client IP per minute unless a reviewed staging override is recorded. The
   Redis URL must use `rediss://` with the private primary endpoint, and
   ElastiCache transit encryption must remain enabled.
5. Confirm `SERVICE_ROUTING_API_ALLOWED_HOSTS` exactly matches the private URL
   hostname before selecting HTTP mode. Stub is the honest default when that
   separately owned service is unavailable.

### Trusted viewer-IP chain

The application quota identity uses the existing append-only
`X-Forwarded-For` chain; there is no browser-controlled replacement header.
CloudFront appends the TCP viewer address and ALB appends the CloudFront edge
address. Terraform renders `SERVICE_TRUSTED_PROXY_IPS` from only:

- the private addresses available to ALB nodes in this stack's public subnet
  CIDRs; and
- the live entries of AWS's
  `com.amazonaws.global.cloudfront.origin-facing` managed prefix list.

Django's nearest-untrusted-hop traversal therefore skips the known ALB and
CloudFront hops and selects the viewer address CloudFront appended. Any
viewer-supplied X-Forwarded-For values remain farther left and are ignored.
Do not replace this with `0.0.0.0/0`, arbitrary public ranges, the entire VPC,
or a header forwarded unchanged from the viewer. The ALB security group must
continue accepting HTTPS only from the same CloudFront-managed origin-facing
prefix list.

Before rollout, send two independent test clients through different
CloudFront edges and confirm safe diagnostics show distinct hashed limiter
subjects and independent quotas. Also send a request with a forged leftmost
X-Forwarded-For value and confirm the selected subject remains the real viewer
address. Record only hashes, status/counts, and edge/ALB metadata—never raw IPs,
coordinates, tokens, or full request lines.

## Database and migration gate

The Service DB contract contains `geography` columns. The approved Service
migration chain must idempotently enable PostGIS and create only Service-owned
tables. The deployment workflow runs the candidate image as a one-off Fargate
task before updating the ECS service:

```text
python manage.py migrate --noinput
```

The task uses the production task definition, RDS-managed password secret,
private subnet/security group, read-only root, and writable ephemeral `/tmp`.
The container builds `DATABASE_URL` only in process memory. A non-zero task
exit stops deployment. Evidence to retain with the release:

- candidate image digest and task-definition ARN
- migration task ARN, stopped reason, container exit code, and safe CloudWatch
  stream reference (never copy SQL values or exact coordinates)
- `showmigrations --plan` before and `showmigrations` after
- `SELECT extversion FROM pg_extension WHERE extname='postgis'` result version,
  recorded without connection strings or credentials
- a pre-migration automated RDS snapshot identifier for non-expand changes

Only backward-compatible expand/contract migrations are eligible for automatic
rollout. A failed or destructive migration is not rolled back by reversing
Django migration blindly: keep the old application task active, assess the
schema, and restore to a new RDS instance from snapshot/PITR if required.

## Deploy and smoke

Set `service_desired_count=2` after secrets and migration readiness are proven,
then activate the protected staging workflow. Its ordering is immutable image
push → candidate task registration → one-off migration → ECS circuit-breaker
rollout → versioned S3 upload → CloudFront invalidation → HTTPS smoke.

Verify at minimum:

- `/` and `/api/v1/health` over HTTPS
- CSRF bootstrap and same-origin POST (no redirect loop)
- CloudFront/ALB Host accepted by Django
- place, guest-session, and route-search WAF throttles in count/test mode before
  enforcing tuned production values
- application 429 behavior across at least two ECS tasks, Redis fail-closed
  behavior, idempotent replay after task switching, and WAF/application limit
  interaction using only safe aggregate metrics
- browser storage/cache contains no guest token, coordinates, places, results,
  history, or account response
- WAF log record query string is redacted and no ALB/Nginx/Gunicorn raw API
  request-line logs exist; application telemetry contains only safe path/status

## Data-rights worker and retention drill

The production task definition mounts a KMS-encrypted EFS access point at
`/var/lib/service-data-rights` with TLS and IAM authorization. Only UID/GID
10001 and the Service task role can write it. EFS automatic backups are
explicitly disabled because a backup would extend the 15-minute privacy
retention window; exports are reproducible. EventBridge runs
`process_data_rights_jobs --limit 100` every five minutes and
`purge_service_data` hourly. Failed schedule delivery is retried three times,
then sent to the encrypted SQS dead-letter queue and alarms the supplied SNS
topic. The artifact remains Fernet-encrypted inside EFS and is expired by the
application's 900-second TTL; neither WAF nor application logs may contain the
artifact or its reference.

Before staging beta, retain evidence for one synthetic account export and
deletion drill:

1. populate the dedicated Fernet secret and start the service;
2. create an export job, observe the EventBridge task exit code 0 and verify an
   encrypted file exists through safe counts/metadata only;
3. verify the owner can retrieve the export and a different account cannot;
4. wait past TTL, run/observe `purge_service_data`, and verify the artifact is
   removed;
5. create a deletion job, observe scheduling then completion, and verify the
   account, sessions, places/history/favorites, jobs, and artifacts are gone;
6. confirm the DLQ is empty and record only job IDs, task ARNs, timestamps,
   counts, and exit codes—never export content, coordinates, tokens, or keys.

If the scheduler alarm fires, disable new export requests at the application
feature gate, inspect safe ECS stopped reasons and DLQ metadata, repair the
worker/store, redrive only after ownership and retention checks, then rerun the
drill. Rotate the Fernet key only with an explicit artifact expiry/migration
plan; changing it immediately makes outstanding exports unreadable.

## Rollback and restore

- ECS: update the service to the previous task-definition ARN; the deployment
  circuit breaker also rolls back failed health checks automatically.
- Web: restore the previous `index.html`, service worker, manifest, and asset
  versions from S3 version history, then invalidate those three mutable paths.
- Database: use PITR to a new instance and deliberately repoint a reviewed task
  definition. Run a restore drill before production and at least quarterly.
- Secrets: rotate in Secrets Manager, force a new deployment, revoke the old
  Routing token, and audit caller/correlation records.

## Production gaps

Staging artifacts are not a production approval. Production still requires a
separate account/state, Multi-AZ RDS, deletion protection, redundant NAT or
approved egress proxy, Route 53 records, both ACM certificates, alert SNS/on-call
routing, AWS Budgets/Cost Anomaly subscriptions, WAF tuning evidence, shared
Redis-backed atomic rate/idempotency implementation, database restore drill,
live data export/deletion drill, iPhone/Android device evidence, load/SLO evidence, and a
private Routing deployment owned by its workstream.
