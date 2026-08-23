# Private Routing staging runbook

This runbook activates the Terraform-instantiated private Routing stack without
weakening its fail-closed Provider or Service boundary. It does not grant live
Provider approval by itself.

## Topology and startup order

```text
Service task SG -> internal HTTPS ALB -> Routing task SG
                                      -> Routing PostGIS SG
                                      -> Routing Redis SG
Routing-only subnet route table -> audited Network Firewall endpoint -> Provider allowlist
```

Routing has no public IP, public listener, or browser route. The container starts
`routing_deployment.wsgi:application`; dependency assembly and one-shot
registration complete before Django WSGI initialization. A missing dependency
factory is unavailable/all-false. An invalid factory or result stops startup.

## Required external inputs

1. Build and scan the Routing image, retain its SBOM/provenance, and set an
   immutable ECR digest in `routing_image`.
2. Create a private Route 53 name and regional ACM/private-CA certificate for
   `routing_private_hostname`.
3. Supply one separately governed AWS Network Firewall endpoint ID per AZ. The
   module puts Routing tasks in dedicated subnets whose default and return routes
   traverse those endpoints. The firewall policy, logging, NAT-side routes, domain/
   IP allowlist, and evidence artifact are externally owned and must be reviewed
   together. A security-group rule alone is not an egress control.
4. Populate the Terraform-created Secrets Manager containers for the Routing
   Django key, `routing_app` password, migration-only Django/JWT settings,
   `routing_migrator` password, and Provider keys. Populate the shared
   Service-to-Routing JWT secret once and expose the same secret ARN only to the
   online Service and Routing tasks. Terraform creates no secret versions and
   no key appears in state. Migration-only Django/JWT values must satisfy the
   same startup strength checks (Django at least 50 characters; JWT 32-4096
   bytes with no surrounding/control whitespace) but are never valid online
   authentication material.
5. Store the reviewed non-secret Provider evidence JSON outside Git and inject
   its exact value as `ROUTING_PROVIDER_EVIDENCE_JSON`. Its
   `egressAttestation` must identify the enforced proxy/firewall, artifact hash,
   version, issued/expiry times, and `EXTERNAL_PROXY_OR_FIREWALL` enforcement.
   A boolean or the existence of a NAT gateway is not evidence.
   Runtime source validation checks shape, hashes, versions, and validity windows;
   it does not cryptographically prove who authored the document. Authenticity is
   therefore a protected deployment/IAM, artifact-review, and audit-log gate.

## Routing database gate

Terraform creates a private encrypted PostgreSQL instance, an empty application
password secret, a master-scoped bootstrap task definition, and a separate
`routing_app` migration task definition. It never creates a secret version and
never runs either task automatically. After the application-password secret is
populated, run the protected `bootstrap-routing-staging.yml` template or the same
two tasks from an audited operator session. Before setting a Routing desired count
above zero, the gate must:

1. retrieve the RDS-managed `routing_admin` secret and application password
   without printing either;
2. run the idempotent bootstrap task to enable PostGIS in the `routing` database;
3. create/rotate separate `routing_migrator` and `routing_app` login roles;
   only the migrator receives temporary schema-create access;
4. run the separate migration task as `routing_migrator` from the identical
   immutable candidate image over TLS, then rerun bootstrap in `finalize` mode to
   grant runtime table/sequence access to `routing_app` and revoke migrator
   schema-create access and disable migrator login;
5. verify no Service tables/role grants exist in the Routing database and retain
   migration plan/result, PostGIS version, task ARN, exit code, and safe log
   reference.

The application ECS task uses only `routing_app`; only the one-off migration task
receives the migrator password and isolated migration-only Django/JWT settings.
It cannot retrieve the online Django key, shared Service JWT, Provider keys, or
application password. The bootstrap task alone can retrieve the RDS master,
application, and migration DB passwords. A failed
or destructive migration keeps both desired counts zero;
restore to a new RDS instance from snapshot/PITR instead of blindly reversing it.

Run this workflow only through the separately protected
`staging-routing-database` GitHub Environment and its dedicated OIDC role. IAM
allows `RunTask` only for the bootstrap/migration task-definition families, the
named ECS cluster, and Routing private subnets; it allows `PassRole` only for
their isolated execution roles. ECS requires the read-only
`DescribeTaskDefinition` action to use `Resource = "*"`; no task registration
permission is granted.

## Metrics and alarms

The stack provisions ALB target 5xx and P95-over-6.5-second alarms plus fail-closed
custom alarms for deadline exhaustion, Provider 429, PARTIAL rate, quota utilization,
and daily Provider cost. The application/telemetry adapter must publish the exact
`82TA/Routing` metric names and `Environment` dimension. `INSUFFICIENT_DATA` is a
release failure because every custom alarm treats missing data as breaching. Before
activation, verify safe synthetic metric ingestion and SNS delivery; alarm resources
are not evidence that the application emitted a metric or that quota/cost accounting
is correct.

## Activation

1. Apply with both desired counts zero and `routing_enabled=true`.
2. Complete secret, private TLS/DNS, firewall, database bootstrap/migration, metric,
   schema, key/schema/
   terms/quota, and production approval evidence.
3. Start one Routing task. Check `/v1/health/live`, then authenticated
   `/v1/health/ready`, `/v1/capabilities`, and `/v1/version` through the internal
   ALB. Live alone is not readiness.
4. Run a sanitized Service-to-Routing canary and verify the response provenance,
   strict taxi upper budget, deadline, Provider call count, and PARTIAL behavior.
5. Scale Routing to at least two tasks, repeat 10/50/100 load and multi-instance
   idempotency/failure tests, then start Service in HTTP mode.
6. Never set a running production Service to Stub/Replay. Terraform rejects a
   positive Service desired count unless private Routing is enabled, running,
   and selected through HTTP.

## Rollback

- Set Service desired count to zero before Routing if the private dependency is
  unhealthy; never expose Routing publicly as a workaround.
- Roll Routing back to the previous immutable task definition/image and approved
  evidence/model versions, or set its desired count to zero to restore the
  fail-closed boundary.
- Keep Provider evidence expired/absent and the dependency factory unavailable
  during incident isolation. Rotate only the affected secret through Secrets
  Manager; do not copy it into commands, logs, or Terraform variables.
