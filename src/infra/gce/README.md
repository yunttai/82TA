# Required GCE deployment

GCE is the only supported cloud compute target. The current implementation is a
single blank GCE VM bootstrapped into a Docker Compose host; no alternate-cloud
runbook or parity requirement exists. Terraform provisioning is documented in
`../terraform/README.md`.

`.github/workflows/cd-gce.yml` deploys the application to a new Debian/Ubuntu
VM at the fixed path `/opt/82ta`. No application files, Docker installation, or
runtime `.env` file need to exist on the server first.

The workflow performs the complete sequence:

1. builds and pushes Web, Service API, Routing API, and Provider proxy images;
2. connects with pinned SSH host verification and passwordless `sudo`;
3. installs Docker Engine, Buildx, Compose v2, CA certificates, curl, and OpenSSL;
4. creates `/opt/82ta`, persistent Service SQLite storage, and runtime directories;
5. generates the Service/Django/JWT random secrets on the server;
6. writes all canonical Provider keys from GitHub secrets without committing them;
7. logs the server into Docker Hub and starts HTTP Nginx plus the Provider proxy;
8. issues the Let's Encrypt certificate;
9. starts the locally tested Routing PostGIS and Redis containers;
10. makes the bounded live Provider probes and starts Routing with their generated evidence;
11. migrates both databases, starts the complete stack, and checks HTTPS;
12. installs three-hour Provider-evidence refresh and daily certificate-renewal timers.

The privacy document version is fixed to `privacy-v1` in both the Web build and
Service runtime. The workflow no longer depends on an unset GitHub variable.

## GitHub `gce` environment secrets

All of these are required:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`
- `KAKAO_JS_API_KEY`
- `KAKAO_REST_API_KEY`
- `GBIS_SERVICE_KEY`
- `GITS_API_KEY`
- `TMAP_APP_KEY`
- `ODSAY_API_KEY`
- `SSH_KEY`
- `HOST`
- `HOST_KEY`
- `USER`
- `DOMAIN`
- `LETSENCRYPT_EMAIL`

`HOST_KEY` is the reviewed `known_hosts` line for the VM. `USER` must be able to
run passwordless `sudo`. Before the first run, point the domain's DNS A record at
the VM and allow inbound TCP 80/443 in the GCE firewall. If UFW is already active
on the VM, bootstrap also opens TCP 80/443 in that host firewall. Those cloud
resources and GitHub secret values cannot be inferred by the repository.

The workflow runs automatically for `main` and tags matching `v*.*.*`; it can
also be started manually.

The current SSH path requires the deploy runner or bastion CIDR to be explicitly
allowed by the GCE firewall and the reviewed host key to match `HOST_KEY`. GCE OS
Login should own the remote user's key. Do not create a JSON service-account key
for this workflow.

## Database and Redis

Service keeps the locally used SQLite/no-Redis setup, so `DATABASE_URL`,
`SERVICE_MIGRATION_DATABASE_URL`, and `SERVICE_REDIS_URL` remain commented.
Service persists its database at `/opt/82ta/service-data/service-api.sqlite3`.
After starting the stack, CD reads Django settings inside the running Service
container and requires `COORDINATION_BACKEND=local`. This prevents an accidental
configuration mismatch; it does not install Service Redis on GCE.

Routing does use PostGIS and Redis locally, so this Compose file starts both and
the bootstrap generates `ROUTING_DB_PASSWORD`. The separate Routing migration
role variables remain commented because the locally tested Docker path runs
migrations with the same Routing database user before Gunicorn starts.

## Readiness and rollback

The filename `docker-compose.prod.yml` is retained for deployment compatibility;
its Service development mode, SQLite, internal HTTP and Routing development
provenance are not a production claim. Before staging/production promotion, record
the database/TLS/backup/restore/alert/cost evidence listed in
`../../docs/shared/GCE_DEPLOYMENT.md`.

Rollback on GCE means redeploying the previous reviewed image tag/digest and
Compose revision on the same VM. Back up state before schema changes and prove a
restore into an isolated GCE environment; switching clouds is not a rollback path.
