# Service Product containers

Both images use the repository `src/` directory as their build context. The
Service image installs from the locked `uv.lock`, runs as UID 10001, and adds
only the WSGI server and PostgreSQL driver required by the deployment adapter.
The Web image builds the locked npm graph and serves immutable Vite assets from
an unprivileged Nginx process. Browser API traffic remains same-origin.

Run the complete local browser → Django → canonical Stub flow from the
repository root:

```bash
docker compose -f src/infra/docker/compose.service-product.yml up --build
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/api/v1/health
```

Then open `http://127.0.0.1:8080`. Local Compose deliberately uses Stub mode
and a disposable SQLite database; it is not a production topology. Production
migrations are a separate one-off ECS task and are never run by the container
entry point. Images are built from the repository root so generated clients
remain the only API DTO source.

To enable real Kakao Local search without committing credentials, export the
server REST key only in the launching shell. Kakao Maps JS requires the
separate JavaScript app key with `http://127.0.0.1:8080` registered as an
allowed origin:

```bash
export KAKAO_REST_API_KEY='<rotated-rest-api-key>'
export KAKAO_JS_API_KEY='<javascript-app-key>'
docker compose -f src/infra/docker/compose.service-product.yml up --build -d
```

Do not put either key in Git. The REST key is injected only into Django; the
browser build receives only the domain-restricted JavaScript key. Kakao
Mobility remains outside the Service Product boundary.

The Web Nginx image is useful for local and container smoke tests. AWS staging
serves the same `dist/` output from private S3 through CloudFront instead.

## Service to Routing HTTP E2E

`compose.routing-e2e.yml` adds a non-root Routing image, Routing-owned PostGIS
and Redis, and switches only the Service Backend to `HttpRoutingGateway`. The
browser still talks only to Service. Routing publishes no host port.

```bash
docker compose -f src/infra/docker/compose.routing-e2e.yml up --build
curl --fail http://127.0.0.1:8080/api/v1/health
```

The Routing WSGI target is `routing_deployment.wsgi:application`. It invokes the
deployment bootstrap before Django creates the WSGI application. Local
DEVELOPMENT deliberately has no default dependency factory, so it starts in the
unavailable/all-false state without Provider I/O. The production baseline factory
`routing_deployment.baseline:build_dependencies` accepts only STAGING/PRODUCTION;
it must never be forced into local DEVELOPMENT. No fixture backend is enabled.

Compose credentials are explicitly local-only. Real Provider keys, the baseline
factory, and evidence
must come from the launching shell or an external secret store and must never be
written to `.env`, Compose, logs, or the repository.

### Live Provider Docker profile

The optional `compose.routing-live.yml` overlay keeps the runtime environment and
persisted provenance as `dev`, keeps fixtures disabled, and enables the production
dependency assembly only behind the explicit `ROUTING_LOCAL_LIVE_E2E=true` gate.
Routing joins an internal Docker network with no direct internet route. Its only
external path is the non-root CONNECT proxy, which permits TLS tunnels to exactly
`dapi.kakao.com:443` and `apis-navi.kakaomobility.com:443`; the proxy never sees
Provider paths, keys, or response bodies.

Keep Provider values in the ignored
`src/services/routing-api/.env.local`. Start the proxy, spend one bounded probe per
baseline operation, and generate short-lived non-secret evidence:

```powershell
docker compose -f src/infra/docker/compose.routing-e2e.yml -f src/infra/docker/compose.routing-live.yml up -d --build routing-egress-proxy
python src/scripts/prepare_routing_docker_live.py --approve-local-provider-use
docker compose --env-file src/services/routing-api/.env.local --env-file src/services/routing-api/.env.routing-live.generated -f src/infra/docker/compose.routing-e2e.yml -f src/infra/docker/compose.routing-live.yml up -d --build
```

The approval flag authorizes only the bounded local calls represented by the
short-lived evidence. It is not staging/production release approval. Stop and remove
the disposable stack with both Compose files after the session.
