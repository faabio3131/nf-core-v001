#!/usr/bin/env bash
# Validate both host-db worker overrides against the actual Contabo SERVICE naming.
# Synthetic fixture only: never starts containers, touches host DB, or opens secrets.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"
trap 'rm -rf -- "$T"' EXIT

mkdir -p "$T/src" "$T/bling"
printf 'POSTGRES_PASSWORD=synthetic-ci-only\n' > "$T/.env"
printf 'NFCORE_WORKER_GSM_MODE=multi-tenant-production-sa-v1\n' > "$T/.env.worker"
printf 'NFCORE_WORKER_CONNECTOR=bling-multi\n' > "$T/.env.bling.worker"
printf 'synthetic-placeholder\n' > "$T/identity.json"
cat > "$T/docker-compose.yml" <<'YAML'
name: nfcore
services:
  db:
    image: postgres:16-alpine
    container_name: nfcore-db
    networks: [internal]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U nfcore -d nfcore"]
  nfcore-api:
    image: busybox:1.36
    depends_on:
      db:
        condition: service_healthy
    networks: [internal]
  nfcore-portal:
    image: busybox:1.36
    networks: [internal]
networks:
  internal: {}
YAML

export NFCORE_WORKER_IDENTITY_HOST_PATH="$T/identity.json"
export NFCORE_BLING_SECRETS_HOST_DIR="$T/bling"
base=(docker compose --project-directory "$T" --env-file "$T/.env" -f "$T/docker-compose.yml")

for worker in gsm bling; do
  if [[ "$worker" == gsm ]]; then
    original="$HERE/compose.worker.opt-in.yml"
    override="$HERE/compose.worker.host-db.override.yml"
    profile="worker-authorized"
    service=nfcore-worker
  else
    original="$HERE/compose.bling.worker.opt-in.yml"
    override="$HERE/compose.bling.worker.host-db.override.yml"
    profile="bling-worker-authorized"
    service=nfcore-bling-worker
  fi

  # The original overlay alone MUST fail against the host's 'db' service.
  if "${base[@]}" -f "$original" --profile "$profile" config -q >/dev/null 2>&1; then
    echo "NO_GO: original $worker overlay unexpectedly accepts db-only host" >&2
    exit 1
  fi

  # The host overlay fixes the dependency and preserves the approved GSM restart policy.
  # Bling remains opt-in with restart=no until its own operational gates pass.
  files=("${base[@]}" -f "$original" -f "$override")
  if "${files[@]}" config --services | grep -Fxq "$service"; then
    echo "NO_GO: $worker enabled without profile" >&2
    exit 1
  fi
  "${files[@]}" --profile "$profile" config --format json > "$T/$worker.json"
  python3 - "$T/$worker.json" "$service" "$profile" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
service_name, profile = sys.argv[2:]
services = config["services"]
assert set(services) == {"db", "nfcore-api", "nfcore-portal", service_name}, services.keys()
db = services["db"]
worker = services[service_name]
assert db["container_name"] == "nfcore-db"
assert set(db["networks"]) == {"internal"}
assert worker["profiles"] == [profile]
assert set(worker["depends_on"]) == {"db"}
assert worker["depends_on"]["db"]["condition"] == "service_healthy"
assert set(worker["networks"]) == {"internal"}
assert worker["user"] == "10001:10001"
assert worker["read_only"] is True
assert worker["restart"] == ("unless-stopped" if service_name == "nfcore-worker" else "no")
assert "ALL" in worker["cap_drop"]
assert "no-new-privileges:true" in worker["security_opt"]
assert "ports" not in worker
assert "nfcore-db:5432" in worker["environment"]["DATABASE_URL"]
mounts = worker["volumes"]
assert mounts and all(m["read_only"] is True for m in mounts)
assert all(m.get("bind", {}).get("create_host_path") is False for m in mounts)
print("HOST_DB_OVERRIDE_OK", service_name)
PY
done
echo "HOST_DB_WORKERS_CONFIG_TEST_PASS: no containers started"
