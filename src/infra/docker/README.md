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
export KAKAO_LOCAL_REST_KEY='<rotated-local-rest-key>'
export VITE_KAKAO_MAP_APP_KEY='<javascript-app-key>'
docker compose -f src/infra/docker/compose.service-product.yml up --build -d
```

Do not put either key in Git. The REST key is injected only into Django; the
browser build receives only the domain-restricted JavaScript key. Kakao
Mobility remains outside the Service Product boundary.

The Web Nginx image is useful for local and container smoke tests. AWS staging
serves the same `dist/` output from private S3 through CloudFront instead.
