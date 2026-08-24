#!/usr/bin/env bash
set -Eeuo pipefail

remote_dir=/opt/82ta
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
refresh_script="$script_dir/refresh-provider-evidence.sh"
deploy_user=${SUDO_USER:-}

if [[ $EUID -ne 0 ]]; then
  echo "bootstrap-host.sh must run through sudo" >&2
  exit 2
fi
if [[ -z $deploy_user || $deploy_user == root ]] \
  || ! getent passwd "$deploy_user" >/dev/null; then
  echo "a non-root sudo deploy user is required" >&2
  exit 2
fi
if [[ ! -s $refresh_script ]]; then
  echo "refresh-provider-evidence.sh must be uploaded beside bootstrap-host.sh" >&2
  exit 2
fi
if ! command -v apt-get >/dev/null; then
  echo "blank-server deployment supports Debian or Ubuntu" >&2
  exit 2
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install --yes --no-install-recommends ca-certificates curl openssl

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  . /etc/os-release
  case "${ID:-}" in
    debian|ubuntu) ;;
    *) echo "blank-server deployment supports Debian or Ubuntu" >&2; exit 2 ;;
  esac
  if [[ -z ${VERSION_CODENAME:-} ]]; then
    echo "VERSION_CODENAME is missing from /etc/os-release" >&2
    exit 2
  fi

  install -m 0755 -d /etc/apt/keyrings
  curl --fail --silent --show-error --location \
    "https://download.docker.com/linux/$ID/gpg" \
    --output /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/$ID
Suites: $VERSION_CODENAME
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  apt-get update
  apt-get install --yes --no-install-recommends \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

docker compose version >/dev/null
systemctl enable --now docker

# GCE network firewall rules do not override an active host firewall. Keep an
# existing UFW policy enabled, but explicitly expose the two public web ports.
if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then
  ufw allow 80/tcp
  ufw allow 443/tcp
fi

install -d -o "$deploy_user" -g "$deploy_user" -m 0750 "$remote_dir"
install -d -o "$deploy_user" -g "$deploy_user" -m 0750 \
  "$remote_dir/nginx" \
  "$remote_dir/certbot/config" \
  "$remote_dir/certbot/www" \
  "$remote_dir/certbot/logs"
install -d -o 10001 -g 10001 -m 0700 "$remote_dir/service-data"
if [[ ! -e $remote_dir/service-data/service-api.sqlite3 ]]; then
  install -o 10001 -g 10001 -m 0600 /dev/null \
    "$remote_dir/service-data/service-api.sqlite3"
elif [[ ! -f $remote_dir/service-data/service-api.sqlite3 ]]; then
  echo "persisted Service SQLite target is not a regular file" >&2
  exit 2
else
  chown 10001:10001 "$remote_dir/service-data/service-api.sqlite3"
  chmod 0600 "$remote_dir/service-data/service-api.sqlite3"
fi
install -d -o 10002 -g 10002 -m 0700 "$remote_dir/.runtime"

env_file="$remote_dir/.env"
if [[ ! -e $env_file ]]; then
  install -o "$deploy_user" -g "$deploy_user" -m 0600 /dev/null "$env_file"
fi
if [[ -L $env_file || ! -f $env_file ]]; then
  echo "runtime environment must be a regular file" >&2
  exit 2
fi

comment_unused_input() {
  local name=$1
  sed -i -E "s/^${name}=/# disabled-not-used: ${name}=/" "$env_file"
}

for name in \
  DATABASE_URL SERVICE_MIGRATION_DATABASE_URL SERVICE_REDIS_URL \
  SERVICE_DATA_RIGHTS_ARTIFACT_DIRECTORY \
  SERVICE_DATA_RIGHTS_ARTIFACT_ENCRYPTION_KEY \
  ROUTING_DB_MIGRATION_USER ROUTING_DB_MIGRATION_PASSWORD \
  ROUTING_PROVIDER_EVIDENCE_JSON ROUTING_PROVIDER_HTTPS_PROXY_URL; do
  comment_unused_input "$name"
done

ensure_secret() {
  local name=$1
  local bytes=$2
  if grep -Eq "^${name}=.{32,}$" "$env_file"; then
    return
  fi
  sed -i -E "/^${name}=/d" "$env_file"
  printf '%s=%s\n' "$name" "$(openssl rand -hex "$bytes")" >> "$env_file"
}

ensure_secret SERVICE_SECRET_KEY 32
ensure_secret SERVICE_REDIS_KEY_DERIVATION_SECRET 32
ensure_secret SERVICE_ROUTING_JWT_SECRET 32
ensure_secret ROUTING_DJANGO_SECRET_KEY 32
ensure_secret ROUTING_DB_PASSWORD 32

ensure_value() {
  local name=$1
  local value=$2
  sed -i -E "/^${name}=/d" "$env_file"
  printf '%s=%s\n' "$name" "$value" >> "$env_file"
}

ensure_value ROUTING_DB_NAME routing
ensure_value ROUTING_DB_USER routing
ensure_value ROUTING_DB_HOST routing-db
ensure_value ROUTING_DB_PORT 5432
ensure_value ROUTING_REDIS_URL redis://routing-redis:6379/0
chown "$deploy_user:$deploy_user" "$env_file"
chmod 0600 "$env_file"

install -o root -g root -m 0755 "$refresh_script" \
  /usr/local/sbin/82ta-refresh-provider-evidence

cat > /usr/local/sbin/82ta-renew-certificate <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/82ta
compose=(
  docker compose
  --env-file .env
  --env-file .provider.env
  --env-file .deploy.env
  -f docker-compose.prod.yml
)
"${compose[@]}" --profile tools run \
  --interactive=false --no-tty --rm \
  certbot renew --webroot -w /var/www/certbot </dev/null
"${compose[@]}" up -d --force-recreate --no-deps nginx
EOF
chmod 0755 /usr/local/sbin/82ta-renew-certificate

cat > /etc/systemd/system/82ta-provider-evidence-refresh.service <<'EOF'
[Unit]
Description=Refresh 82TA Provider evidence
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/82ta-refresh-provider-evidence
EOF

cat > /etc/systemd/system/82ta-provider-evidence-refresh.timer <<'EOF'
[Unit]
Description=Refresh 82TA Provider evidence every three hours

[Timer]
OnBootSec=5min
OnUnitActiveSec=3h
Persistent=true

[Install]
WantedBy=timers.target
EOF

cat > /etc/systemd/system/82ta-certificate-renew.service <<'EOF'
[Unit]
Description=Renew the 82TA Let's Encrypt certificate
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/82ta-renew-certificate
EOF

cat > /etc/systemd/system/82ta-certificate-renew.timer <<'EOF'
[Unit]
Description=Check the 82TA Let's Encrypt certificate daily

[Timer]
OnBootSec=30min
OnUnitActiveSec=1d
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
echo "blank-server bootstrap complete"
