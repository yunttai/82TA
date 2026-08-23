# Blank GCE server deployment

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
the VM and allow inbound TCP 80/443 in the GCE firewall. Those cloud resources
and GitHub secret values cannot be inferred by the repository.

The workflow runs automatically for `main`, tags matching `v*.*.*`, and
`feature/realtime-multimodal-e2e`; it can also be started manually.

## Database and Redis

Service keeps the locally used SQLite/no-Redis setup, so `DATABASE_URL`,
`SERVICE_MIGRATION_DATABASE_URL`, and `SERVICE_REDIS_URL` remain commented.
Service persists its database at `/opt/82ta/service-data/service-api.sqlite3`.

Routing does use PostGIS and Redis locally, so this Compose file starts both and
the bootstrap generates `ROUTING_DB_PASSWORD`. The separate Routing migration
role variables remain commented because the locally tested Docker path runs
migrations with the same Routing database user before Gunicorn starts.
