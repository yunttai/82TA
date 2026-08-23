# syntax=docker/dockerfile:1.7
FROM python:3.12.11-slim-bookworm AS builder

ARG UV_VERSION=0.8.13
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN python -m venv /opt/service-venv \
    && /opt/service-venv/bin/pip install --no-cache-dir "uv==${UV_VERSION}"

WORKDIR /build
COPY generated/routing-client-python/ generated/routing-client-python/
COPY services/service-api/ services/service-api/
RUN cd services/service-api \
    && /opt/service-venv/bin/uv sync --frozen --no-dev \
    && /opt/service-venv/bin/uv pip install --python .venv/bin/python \
      "gunicorn==23.0.0"

FROM python:3.12.11-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/src/services/service-api/.venv/bin:$PATH \
    SERVICE_ENVIRONMENT=production \
    SERVICE_DEBUG=false \
    PORT=8000

RUN groupadd --system --gid 10001 service \
    && useradd --system --uid 10001 --gid service --home-dir /nonexistent --shell /usr/sbin/nologin service

WORKDIR /app/src/services/service-api
COPY --from=builder --chown=service:service /build/services/service-api/ /app/src/services/service-api/
COPY --chown=service:service contracts/ /app/src/contracts/
COPY --chown=service:service infra/docker/service-api/service_wsgi.py /app/src/services/service-api/service_wsgi.py
COPY --chown=service:service infra/docker/service-api/runtime_entrypoint.py /opt/service/runtime_entrypoint.py

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/infra/healthz', timeout=2).read()"]

ENTRYPOINT ["python", "/opt/service/runtime_entrypoint.py"]
CMD ["python", "-m", "gunicorn", "service_wsgi:application", "--bind=0.0.0.0:8000", "--workers=2", "--threads=4", "--timeout=10", "--graceful-timeout=10", "--access-logfile", "/dev/null", "--error-logfile=-"]
