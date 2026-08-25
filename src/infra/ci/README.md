# CI/CD

The sole active cloud deployment is `.github/workflows/cd-gce.yml`. It builds the
four container images, bootstraps a blank GCE VM, installs the reviewed Compose and
Nginx files, probes Providers, starts dependencies in order, issues HTTPS and
verifies public health endpoints. It also verifies from the running Service
container that the current single-node GCE topology still selects local
coordination. This is an honest configuration check, not a GCE Redis deployment.

`.github/workflows/pr-service-product.yml` is the active pull-request workflow.
Its mirrored source template is `github-actions/pr-service-product.yml`; infra
tests require the two files to remain byte-for-byte identical. The infrastructure
job builds the local Service Product Compose stack, connects to the real
`redis:7.4-alpine` container, and proves cross-process rate-limit and idempotency
state sharing before removing containers and the disposable CI volume. The
Routing recommendation gateway in that local stack remains a Stub; only Service
coordination is asserted to use real Redis.

There is no alternate-cloud deployment template and no separate cloud bootstrap
workflow. Routing database bootstrap and migrations follow the current GCE Compose
entrypoint; a future managed-database path must add its own reviewed, GCE-scoped
least-privilege workflow when it is actually implemented.

The protected GitHub `gce` environment supplies only the secrets documented in
`src/infra/gce/README.md`. Host identity is pinned with `HOST_KEY`, the private key
is never written to the repository, and the remote user must have only the sudo
permissions required by the bootstrap/deploy scripts.
