#!/usr/bin/env bash
set -euo pipefail

# This script is LF-only so Git Bash can execute it on Windows.

generated_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_dir="$(cd "${generated_dir}/../.." && pwd)"
temporary_dir="$(mktemp -d /tmp/82ta-client-generation.XXXXXX)"
trap 'rm -rf -- "${temporary_dir}"' EXIT

cd "${repository_dir}"

if python3 --version >/dev/null 2>&1; then
  python_runtime=python3
elif python --version >/dev/null 2>&1; then
  python_runtime=python
else
  echo "A working Python runtime is required for contract verification." >&2
  exit 1
fi

"${python_runtime}" src/scripts/verify_contract_lock.py

npx --yes @redocly/cli@1.34.2 bundle \
  src/contracts/openapi/service-public.v1.yaml \
  --output "${temporary_dir}/service-public.v1.bundle.yaml"
npx --yes @redocly/cli@1.34.2 bundle \
  src/contracts/openapi/routing-private.v1.yaml \
  --output "${temporary_dir}/routing-private.v1.bundle.yaml"

# openapi-python-client 0.29.0 rejects date-time values in headers. The
# generated API accepts the deadline as the wire-format ISO 8601 string.
sed -i \
  '/name: X-Request-Deadline/,/name: Idempotency-Key/{/format: date-time/d;}' \
  "${temporary_dir}/routing-private.v1.bundle.yaml"

npx --yes openapi-typescript@7.9.1 \
  "${temporary_dir}/service-public.v1.bundle.yaml" \
  --output src/generated/service-client-ts/schema.gen.ts

uvx --from openapi-python-client==0.29.0 openapi-python-client generate \
  --path "${temporary_dir}/routing-private.v1.bundle.yaml" \
  --output-path src/generated/routing-client-python \
  --config src/generated/config/routing-python.json \
  --meta uv \
  --fail-on-warning \
  --overwrite
