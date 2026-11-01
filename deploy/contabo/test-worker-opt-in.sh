#!/usr/bin/env bash
# Prova estática: nunca inicia container, não toca banco, cron ou credenciais reais.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
cp "$HERE/compose.prod.yml" "$HERE/compose.worker.opt-in.yml" "$T/"
mkdir -p "$T/src"
printf '%s\n' 'POSTGRES_PASSWORD=synthetic-only' > "$T/.env"
printf '%s\n' 'NFCORE_WORKER_GSM_MODE=scoped-production-sa-v1' > "$T/.env.worker"
printf '%s\n' 'not-a-real-key' > "$T/identity.json"
export POSTGRES_PASSWORD=synthetic-only
export NFCORE_WORKER_IDENTITY_HOST_PATH="$T/identity.json"

base=(docker compose -f "$T/compose.prod.yml")
with_worker=(docker compose -f "$T/compose.prod.yml" -f "$T/compose.worker.opt-in.yml")
if "${base[@]}" config --services | grep -qx nfcore-worker; then
  echo "ERROR: Worker included in default production compose"; exit 1
fi
if "${with_worker[@]}" config --services | grep -qx nfcore-worker; then
  echo "ERROR: Worker starts without explicit profile"; exit 1
fi
if ! "${with_worker[@]}" --profile worker-authorized config --services | grep -qx nfcore-worker; then
  echo "ERROR: Worker absent from opted-in profile"; exit 1
fi
"${with_worker[@]}" --profile worker-authorized config --format json > "$T/config.json"
python3 - "$T/config.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    cfg = json.load(stream)
worker = cfg["services"]["nfcore-worker"]
assert worker["profiles"] == ["worker-authorized"]
assert worker["read_only"] is True
assert worker["user"] == "10001:10001"
assert worker["restart"] == "no"
assert worker["cap_drop"] == ["ALL"]
assert "no-new-privileges:true" in worker["security_opt"]
assert "ports" not in worker
assert set(worker["networks"]) == {"internal"}
assert set(worker["depends_on"]) == {"nfcore-db"}
assert worker["environment"]["NFCORE_ENVIRONMENT"] == "production"
assert worker["environment"]["NFCORE_SECRET_BACKEND"] == "external"
assert worker["environment"]["NFCORE_WORKER_GSM_CREDENTIAL_FILE"] == "/run/nfcore/worker-identity.json"
assert not worker["environment"].get("GOOGLE_APPLICATION_CREDENTIALS")
mounts = worker["volumes"]
assert len(mounts) == 1
mount = mounts[0]
assert mount["type"] == "bind"
assert mount["read_only"] is True
assert mount["target"] == "/run/nfcore/worker-identity.json"
assert mount.get("bind", {}).get("create_host_path", False) is False
print("OK: worker opt-in isolado, sem porta e sem montagem implicita")
PY

rm "$T/.env.worker"
if "${with_worker[@]}" --profile worker-authorized config -q >/dev/null 2>&1; then
  echo "ERROR: missing worker env must fail"; exit 1
fi
printf '%s\n' 'NFCORE_WORKER_GSM_MODE=scoped-production-sa-v1' > "$T/.env.worker"
if env -u NFCORE_WORKER_IDENTITY_HOST_PATH "${with_worker[@]}" --profile worker-authorized config -q >/dev/null 2>&1; then
  echo "ERROR: missing identity mount must fail"; exit 1
fi
echo "OK: falta de env ou identity falha fechada; nenhum Worker ativado"
