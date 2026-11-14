#!/usr/bin/env bash
# Run without SSH, secrets, Contabo credentials, Docker or external network.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=deploy/contabo/host-audit-command.sh
source "$here/host-audit-command.sh"
sha=61015a837be8b2e5e3b0f1cdb5fb14c5c875fb91
digest=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef

parse_audit_request "nfcore-audit $sha $digest"
[[ "$AUDIT_PRODUCTION_SHA" == "$sha" && "$AUDIT_SCRIPT_SHA256" == "$digest" ]]
[[ "$AUDIT_KIND" == "bling" ]]
parse_audit_request "nfcore-gsm-audit $sha $digest"
[[ "$AUDIT_PRODUCTION_SHA" == "$sha" && "$AUDIT_SCRIPT_SHA256" == "$digest" ]]
[[ "$AUDIT_KIND" == "gsm" ]]
parse_audit_request "nfcore-a1-audit $sha $digest"
[[ "$AUDIT_PRODUCTION_SHA" == "$sha" && "$AUDIT_SCRIPT_SHA256" == "$digest" ]]
[[ "$AUDIT_KIND" == "a1" ]]

for invalid in \
    "" \
    "id" \
    "nfcore-audit $sha" \
    "nfcore-audit $sha $digest extra" \
    "nfcore-audit $sha $digest;id" \
    "nfcore-audit ${sha^^} $digest" \
    "nfcore-audit $sha ${digest:0:63}" \
    "nfcore-audit $sha $digest\nwhoami"; do
  if parse_audit_request "$invalid"; then
    printf 'FAIL: accepted invalid SSH audit command\n' >&2
    exit 1
  fi
done

# The GSM verb is a separate allowlisted mode, never an arbitrary command.
for invalid in \
    "nfcore-gsm-audit $sha" \
    "nfcore-gsm-audit $sha $digest extra" \
    "nfcore-gsm-audit $sha $digest;id" \
    "nfcore-other-audit $sha $digest" \
    "nfcore-a1-audit $sha" \
    "nfcore-a1-audit $sha $digest;id" \
    "nfcore-a1-audit $sha $digest extra"; do
  if parse_audit_request "$invalid"; then
    echo 'FAIL: accepted invalid GSM audit command' >&2
    exit 1
  fi
done

# The entrypoint must fail closed on untrusted commands without probing host.
if SSH_ORIGINAL_COMMAND='cat /etc/shadow' bash "$here/host-audit-command.sh" >/dev/null 2>&1; then
  echo 'FAIL: accepted arbitrary command' >&2
  exit 1
fi
if SSH_ORIGINAL_COMMAND="nfcore-audit $sha $digest; id" \
   bash "$here/host-audit-command.sh" >/dev/null 2>&1; then
  echo 'FAIL: accepted shell injection' >&2
  exit 1
fi
# Never unlock audit SSH on unprotected workflow branches or pull_request.
workflow="$here/../../.github/workflows/contabo-readonly-host-audit.yml"
grep -Fq "github.ref_protected == true" "$workflow"
grep -Fq "github.ref == 'refs/heads/main'" "$workflow"
gsm_workflow="$here/../../.github/workflows/contabo-gsm-readonly-host-audit.yml"
grep -Fq "github.ref_protected == true" "$gsm_workflow"
grep -Fq "github.ref == 'refs/heads/main'" "$gsm_workflow"
grep -Fq 'nfcore-gsm-audit $REQUESTED_SHA $script_digest' "$gsm_workflow"
grep -Fq 'worker-readonly-preflight.py' "$gsm_workflow"
a1_workflow="$here/../../.github/workflows/contabo-a1-readonly-host-audit.yml"
grep -Fq "github.ref_protected == true" "$a1_workflow"
grep -Fq "github.ref == 'refs/heads/main'" "$a1_workflow"
grep -Fq 'nfcore-a1-audit $REQUESTED_SHA $digest' "$a1_workflow"
grep -Fq 'audit-a1-vault-readonly.py' "$a1_workflow"
grep -Fq 'environment: nfcore-contabo-audit' "$a1_workflow"
if grep -Eq '^[[:space:]]+pull_request:' "$a1_workflow"; then
  echo 'FAIL: A1 SSH audit must not execute on pull_request' >&2
  exit 1
fi
if grep -Eq '^[[:space:]]+pull_request:' "$gsm_workflow"; then
  echo 'FAIL: GSM SSH audit must never execute on pull_request' >&2
  exit 1
fi
if grep -Eq '^[[:space:]]+pull_request:' "$workflow"; then
  echo 'FAIL: SSH audit must never execute on pull_request' >&2
  exit 1
fi
echo 'PASS: forced SSH audit entry rejects arbitrary commands and unprotected branches'
