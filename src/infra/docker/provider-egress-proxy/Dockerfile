# syntax=docker/dockerfile:1.7
FROM python:3.12.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PROVIDER_EGRESS_LISTEN_HOST=0.0.0.0 \
    PROVIDER_EGRESS_LISTEN_PORT=3128

COPY infra/docker/provider-egress-proxy/egress_proxy.py /opt/provider-egress/egress_proxy.py

USER 65534:65534
EXPOSE 3128
HEALTHCHECK --interval=5s --timeout=2s --retries=20 \
  CMD ["python", "/opt/provider-egress/egress_proxy.py", "--healthcheck"]

ENTRYPOINT ["python", "/opt/provider-egress/egress_proxy.py"]
