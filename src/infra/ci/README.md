# CI/CD

The sole active cloud deployment is `.github/workflows/cd-gce.yml`. It builds the
four container images, bootstraps a blank GCE VM, installs the reviewed Compose and
Nginx files, probes Providers, starts dependencies in order, issues HTTPS and
verifies public health endpoints.

`github-actions/pr-service-product.yml` remains an inert PR-validation template.
There is no alternate-cloud deployment template and no separate cloud bootstrap
workflow. Routing database bootstrap and migrations follow the current GCE Compose
entrypoint; a future managed-database path must add its own reviewed, GCE-scoped
least-privilege workflow when it is actually implemented.

The protected GitHub `gce` environment supplies only the secrets documented in
`src/infra/gce/README.md`. Host identity is pinned with `HOST_KEY`, the private key
is never written to the repository, and the remote user must have only the sudo
permissions required by the bootstrap/deploy scripts.
