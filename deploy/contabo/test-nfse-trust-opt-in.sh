#!/usr/bin/env bash
# Static configuration gate: no containers, host credentials or fiscal I/O.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
cp "$HERE/compose.prod.yml" "$HERE/compose.nfse-policy.api.yml" "$HERE/compose.nfse-trust.api.yml" "$T/"
mkdir -p "$T/src" "$T/policies" "$T/trust"
printf 'POSTGRES_PASSWORD=synthetic-ci-only\n' > "$T/.env"
export POSTGRES_PASSWORD=synthetic-ci-only
export NFCORE_NFSE_POLICIES_HOST_DIR="$T/policies"
export NFCORE_NFSE_TRUST_HOST_DIR="$T/trust"
printf -v NFCORE_NFSE_RECEIPT_ROOT_SHA256 '%064d' 1
printf -v NFCORE_NFSE_RECEIPT_SIGNER_SHA256 '%064d' 2
printf -v NFCORE_NFSE_EVENT_SIGNER_SHA256 '%064d' 3
export NFCORE_NFSE_RECEIPT_ROOT_SHA256 NFCORE_NFSE_RECEIPT_SIGNER_SHA256 NFCORE_NFSE_EVENT_SIGNER_SHA256
base=(docker compose -f "$T/compose.prod.yml")
full=(docker compose -f "$T/compose.prod.yml" -f "$T/compose.nfse-policy.api.yml" -f "$T/compose.nfse-trust.api.yml")
"${base[@]}" config --format json > "$T/base.json"
"${full[@]}" config --format json > "$T/full.json"
python3 - "$T/base.json" "$T/full.json" <<'PY'
import json
import sys
from pathlib import Path

base, full = [json.loads(Path(name).read_text()) for name in sys.argv[1:]]
assert set(base["services"]) == set(full["services"]) == {
    "nfcore-db", "nfcore-api", "nfcore-portal"
}
original = base["services"]["nfcore-api"]
api = full["services"]["nfcore-api"]
assert "NFCORE_NFSE_EVENT_SIGNER_SHA256" not in original["environment"]
assert api["networks"] == original["networks"]
assert api["image"] == original["image"]
env = api["environment"]
assert env["NFCORE_NFSE_RECEIPT_CA_BUNDLE"] == "/run/nfcore/sefin-trust/ca-bundle.pem"
assert env["NFCORE_NFSE_RECEIPT_CRL_BUNDLE"] == "/run/nfcore/sefin-trust/crl-bundle.pem"
assert env["NFCORE_NFSE_RECEIPT_SIGNER_BUNDLE"] == "/run/nfcore/sefin-trust/invoice-signers.pem"
assert env["NFCORE_NFSE_EVENT_SIGNER_BUNDLE"] == "/run/nfcore/sefin-trust/event-signers.pem"
assert env["NFCORE_NFSE_FISCAL_POLICY_ROOT"] == "/run/nfcore/nfse-policies"
assert len({env[k] for k in (
    "NFCORE_NFSE_RECEIPT_ROOT_SHA256",
    "NFCORE_NFSE_RECEIPT_SIGNER_SHA256",
    "NFCORE_NFSE_EVENT_SIGNER_SHA256",
)}) == 3
mounts = {m["target"]: m for m in api["volumes"]}
assert set(mounts) == {
    "/var/lib/nfcore/vault", "/run/nfcore/nfse-policies", "/run/nfcore/sefin-trust"
}
assert mounts["/var/lib/nfcore/vault"] == original["volumes"][0]
for target in ("/run/nfcore/nfse-policies", "/run/nfcore/sefin-trust"):
    assert mounts[target]["type"] == "bind"
    assert mounts[target]["read_only"] is True
    assert mounts[target]["bind"]["create_host_path"] is False
PY
for key in NFCORE_NFSE_TRUST_HOST_DIR NFCORE_NFSE_RECEIPT_ROOT_SHA256 NFCORE_NFSE_RECEIPT_SIGNER_SHA256 NFCORE_NFSE_EVENT_SIGNER_SHA256; do
  if env -u "$key" "${full[@]}" config -q >/dev/null 2>&1; then
    echo "FAIL: required trust input missing: $key"
    exit 1
  fi
done
echo 'PASS: canonical API trust overlay opt-in; A1/policy mounts preserved; missing inputs rejected'
