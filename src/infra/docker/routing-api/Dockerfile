# syntax=docker/dockerfile:1.7
FROM python:3.12.11-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY packages/provider-core/ packages/provider-core/
COPY packages/bus-intelligence-core/ packages/bus-intelligence-core/
COPY packages/routing-domain/ packages/routing-domain/
COPY services/routing-api/ services/routing-api/

RUN python -m venv /opt/routing-venv \
    && /opt/routing-venv/bin/pip install --no-cache-dir \
      ./packages/provider-core \
      ./packages/bus-intelligence-core \
      ./packages/routing-domain \
      ./services/routing-api \
      "gunicorn==23.0.0"

FROM python:3.12.11-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/routing-venv/bin:$PATH \
    ROUTING_RUNTIME_ENVIRONMENT=PRODUCTION \
    ROUTING_PRIVATE_OPENAPI_PATH=/app/src/contracts/openapi/routing-private.v1.yaml \
    PORT=8000

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates libgdal32 libgeos-c1v5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10002 routing \
    && useradd --system --uid 10002 --gid routing --home-dir /nonexistent --shell /usr/sbin/nologin routing

WORKDIR /app/src/services/routing-api
COPY --from=builder /opt/routing-venv/ /opt/routing-venv/
COPY --from=builder --chown=routing:routing /build/services/routing-api/ /app/src/services/routing-api/
COPY --chown=routing:routing contracts/ /app/src/contracts/
COPY --chown=routing:routing scripts/prepare_routing_docker_live.py /app/src/scripts/prepare_routing_docker_live.py
COPY --chown=routing:routing infra/docker/compose.routing-live.yml /app/src/infra/docker/compose.routing-live.yml
COPY --chown=routing:routing infra/docker/provider-egress-proxy/Dockerfile /app/src/infra/docker/provider-egress-proxy/Dockerfile
COPY --chown=routing:routing infra/docker/provider-egress-proxy/egress_proxy.py /app/src/infra/docker/provider-egress-proxy/egress_proxy.py
COPY --chown=routing:routing infra/docker/routing-api/runtime_entrypoint.py /opt/routing/runtime_entrypoint.py
COPY --chown=routing:routing infra/docker/routing-api/database_bootstrap.py /opt/routing/database_bootstrap.py

USER 10002:10002
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health/live', timeout=2).read()"]

ENTRYPOINT ["python", "/opt/routing/runtime_entrypoint.py"]
CMD ["python", "-m", "gunicorn", "routing_deployment.wsgi:application", "--bind=0.0.0.0:8000", "--workers=2", "--threads=4", "--timeout=10", "--graceful-timeout=10", "--access-logfile", "/dev/null", "--error-logfile=-"]
