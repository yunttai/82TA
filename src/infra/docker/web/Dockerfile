# syntax=docker/dockerfile:1.7
FROM node:22.22.2-alpine3.23 AS builder

ARG VITE_KAKAO_MAP_APP_KEY=""
ARG VITE_PRIVACY_DOCUMENT_VERSION=""
ENV VITE_KAKAO_MAP_APP_KEY=$VITE_KAKAO_MAP_APP_KEY \
    VITE_PRIVACY_DOCUMENT_VERSION=$VITE_PRIVACY_DOCUMENT_VERSION

WORKDIR /build
COPY generated/service-client-ts/ generated/service-client-ts/
COPY contracts/openapi/examples/ contracts/openapi/examples/
COPY apps/web/package.json apps/web/package-lock.json apps/web/
RUN cd apps/web && npm ci --ignore-scripts
COPY apps/web/ apps/web/
RUN cd apps/web && npm run build

FROM nginxinc/nginx-unprivileged:1.27.5-alpine3.21 AS runtime

COPY --from=builder /build/apps/web/dist/ /usr/share/nginx/html/
COPY infra/docker/web/default.conf.template /etc/nginx/templates/default.conf.template

USER 101:101
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["wget", "--quiet", "--tries=1", "--spider", "http://127.0.0.1:8080/healthz"]
