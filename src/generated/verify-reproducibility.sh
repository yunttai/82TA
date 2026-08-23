#!/usr/bin/env bash
set -euo pipefail

generated_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_dir="$(cd "${generated_dir}/../.." && pwd)"
temporary_dir="$(mktemp -d /tmp/82ta-generated-verification.XXXXXX)"
trap 'rm -rf -- "${temporary_dir}"' EXIT

cd "${repository_dir}"

write_manifest() {
  local destination="$1"
  {
    find src/generated/service-client-ts -maxdepth 1 -type f -print
    find src/generated/routing-client-python -maxdepth 1 -type f -print
    find src/generated/routing-client-python/routing_client -type f \
      \( -name '*.py' -o -name 'py.typed' \) -print
  } | sort | while IFS= read -r artifact; do
    sha256sum "${artifact}"
  done >"${destination}"
}

write_manifest "${temporary_dir}/before.sha256"
bash src/generated/generate-clients.sh
write_manifest "${temporary_dir}/after.sha256"

if ! diff -u "${temporary_dir}/before.sha256" "${temporary_dir}/after.sha256"; then
  echo "Generated clients are stale or generation is not deterministic." >&2
  exit 1
fi

echo "GENERATED CLIENT REPRODUCIBILITY OK"
