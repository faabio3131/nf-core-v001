#!/usr/bin/env bash
# Synthetic status classification: do not use SSH, Docker, host or credentials.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
sha=61015a837be8b2e5e3b0f1cdb5fb14c5c875fb91

cat > "$tmp/baseline" <<EOF
EXPECTED_SHA=${sha:0:12}
DEPLOY_SHA_EXACT=PASS
DEPLOY_FAILED_SHA=CLEAR
DEPLOY_LOG_SUCCESS=PASS
RECENT_BACKUP_INTEGRITY=PASS
CONTAINER_nfcore-db=PASS
CONTAINER_nfcore-api=PASS
CONTAINER_nfcore-portal=PASS
API_READY=PASS
PORTAL_READY=PASS
SCHEMA_PRODUCTION_GUARD=PASS
EOF

check() {
  bash "$here/classify-readonly-host-audit.sh" "$1" "$2" "$sha"
}
fail() {
  if check "$1" "$2" > "$tmp/result"; then
    echo 'FAIL: unsafe SSH/status evidence accepted' >&2
    exit 1
  fi
}
cp "$tmp/baseline" "$tmp/ready"
echo 'RESULT=HOST_GATES_PASS_EXTERNAL_STILL_UNVERIFIED' >> "$tmp/ready"
check "$tmp/ready" 0 | grep -Fxq 'SSH_CHANNEL_AND_NFCORE_HOST_BASELINE_PASS'
fail "$tmp/ready" 1

cp "$tmp/baseline" "$tmp/pending"
cat >> "$tmp/pending" <<EOF
BLING_SCHEMA_20_21=PENDING
BLING_WORKER_RUNNING=PENDING
RESULT=CODE_READY_BUT_BLING_NOT_ACTIVE
EOF
check "$tmp/pending" 1 | grep -Fxq 'SSH_CHANNEL_AND_NFCORE_HOST_BASELINE_PASS'
fail "$tmp/pending" 0
fail "$tmp/pending" 255

cp "$tmp/pending" "$tmp/blocked"
echo 'BLING_POLICY_MOUNT=BLOCKED' >> "$tmp/blocked"
fail "$tmp/blocked" 1

cp "$tmp/pending" "$tmp/missing"
sed -i '/^RECENT_BACKUP_INTEGRITY=/d' "$tmp/missing"
fail "$tmp/missing" 1

cp "$tmp/baseline" "$tmp/unknown"
echo 'RESULT=NO_GO_HOST_GATES' >> "$tmp/unknown"
fail "$tmp/unknown" 1

if bash "$here/classify-readonly-host-audit.sh" "$tmp/ready" 0 invalid >/dev/null 2>&1; then
  echo 'FAIL: accepted invalid production SHA' >&2
  exit 1
fi
echo 'PASS: channel PASS independent of Bling; blocked/missing evidence rejects'
