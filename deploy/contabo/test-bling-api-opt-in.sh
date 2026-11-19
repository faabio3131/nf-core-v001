#!/usr/bin/env bash
# Config-only acceptance: no network, no server, no secrets, no containers started.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
cp "$HERE/compose.prod.yml" "$T/docker-compose.yml"
mkdir -p "$T/src" "$T/host-blind" "$T/host-policies"
printf 'POSTGRES_PASSWORD=synthetic-ci-only\n' > "$T/.env"
printf 'NFCORE_BLING_CLIENT_ID=synthetic-ci-app\nNFCORE_BLING_APPROVED_SCOPES=synthetic\n' > "$T/.env.bling.api"
export POSTGRES_PASSWORD=synthetic-ci-only
export NFCORE_BLING_SECRETS_HOST_DIR="$T/host-blind"
export NFCORE_BLING_POLICIES_HOST_DIR="$T/host-policies"
(cd "$T" && docker compose config --format json) > "$T/base.json"
python3 - "$T/base.json" <<'PY'
import json, sys
config=json.load(open(sys.argv[1], encoding="utf-8"))
api=config["services"]["nfcore-api"]
assert api["environment"].get("NFCORE_BLING_INSTALLATIONS_ENABLED") != "true"
vault_mounts = api.get("volumes", [])
assert len(vault_mounts) == 1, "base must have only canonical A1 Vault"
vault = vault_mounts[0]
assert vault["type"] == "bind" and vault["source"] == "/var/lib/nfcore/vault"
assert vault["target"] == "/var/lib/nfcore/vault"
assert vault.get("read_only", False) is False
assert vault.get("bind", {}).get("create_host_path", False) is False
assert "nfcore-bling-worker" not in config["services"]
PY
cp "$HERE/compose.bling.api.opt-in.yml" "$T/docker-compose.override.yml"
(cd "$T" && docker compose config --format json) > "$T/optin.json"
python3 - "$T/optin.json" <<'PY'
import json, sys
config=json.load(open(sys.argv[1], encoding="utf-8"))
api=config["services"]["nfcore-api"]
assert api["environment"]["NFCORE_BLING_INSTALLATIONS_ENABLED"] == "true"
assert api["environment"]["NFCORE_BLING_CLIENT_ID"] == "synthetic-ci-app"
assert api["environment"]["NFCORE_BLING_APPROVED_SCOPES"] == "synthetic"
assert api["environment"]["NFCORE_BLING_CLIENT_SECRET_FILE"] == "/run/nfcore/bling/client-secret"
assert api["environment"]["NFCORE_BLING_TOKEN_MASTER_KEY_FILE"] == "/run/nfcore/bling/master-key"
assert api["environment"]["NFCORE_BLING_FISCAL_POLICY_ROOT"] == "/run/nfcore/bling-policies"
assert len(api["volumes"]) == 3
mounts={mount["target"]: mount for mount in api["volumes"]}
assert set(mounts) == {"/var/lib/nfcore/vault", "/run/nfcore/bling", "/run/nfcore/bling-policies"}
vault=mounts.pop("/var/lib/nfcore/vault")
assert vault["type"] == "bind" and vault["source"] == "/var/lib/nfcore/vault"
assert vault.get("read_only", False) is False
assert vault.get("bind", {}).get("create_host_path", False) is False
for mount in mounts.values():
    assert mount["type"] == "bind" and mount["read_only"] is True
    assert mount.get("bind",{}).get("create_host_path") is False
assert "proxy-net" in api["networks"] and "internal" in api["networks"]
assert set(config["services"]) == {"nfcore-api", "nfcore-db", "nfcore-portal"}
PY
rm "$T/.env.bling.api"
if (cd "$T" && docker compose config -q) >/dev/null 2>&1; then
  echo "FAIL: missing Bling API configuration was silently accepted"; exit 1
fi
cp "$HERE/.env.bling.api.example" "$T/.env.bling.api"
if (cd "$T" && env -u NFCORE_BLING_SECRETS_HOST_DIR docker compose config -q) >/dev/null 2>&1; then
  echo "FAIL: missing secret mount was silently accepted"; exit 1
fi
if (cd "$T" && env -u NFCORE_BLING_POLICIES_HOST_DIR docker compose config -q) >/dev/null 2>&1; then
  echo "FAIL: missing fiscal policy root was silently accepted"; exit 1
fi
echo "PASS: Bling API compose opt-in is persistent, isolated and fail-closed"
