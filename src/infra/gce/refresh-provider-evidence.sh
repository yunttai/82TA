#!/usr/bin/env bash
set -Eeuo pipefail

remote_dir=/opt/82ta
cd "$remote_dir"

for required in .env .provider.env .deploy.env docker-compose.prod.yml; do
  if [[ ! -s $required ]]; then
    echo "required deployment input is missing: $required" >&2
    exit 2
  fi
done

base=(
  docker compose
  --env-file .env
  --env-file .provider.env
  --env-file .deploy.env
  -f docker-compose.prod.yml
)

"${base[@]}" up -d --wait --wait-timeout 120 \
  routing-egress-proxy routing-db routing-redis
"${base[@]}" --profile tools run \
  --interactive=false --no-tty --rm provider-evidence </dev/null

evidence_file=.runtime/provider-evidence.env
if [[ ! -s $evidence_file ]] \
  || ! grep -q '^ROUTING_PROVIDER_EVIDENCE_JSON={' "$evidence_file"; then
  echo "Provider evidence generation did not produce a valid environment file" >&2
  exit 1
fi

runtime=(
  docker compose
  --env-file .env
  --env-file .provider.env
  --env-file .deploy.env
  --env-file "$evidence_file"
  -f docker-compose.prod.yml
)
"${runtime[@]}" up -d --force-recreate routing-api

for _ in $(seq 1 36); do
  container_id=$("${runtime[@]}" ps -q routing-api)
  if [[ -n $container_id ]] \
    && [[ $(docker inspect --format '{{.State.Health.Status}}' "$container_id") == healthy ]]; then
    echo "Provider evidence refreshed and Routing is healthy"
    exit 0
  fi
  sleep 5
done

echo "Routing did not become healthy after Provider evidence refresh" >&2
exit 1
