#!/usr/bin/env bash
# Validate sanitized, authenticated SSH audit statuses independently of Bling.
# This script NEVER connects to a host, reads secrets or modifies the server.
set -euo pipefail

if [[ "$#" -ne 3 || ! -f "$1" || ! "$2" =~ ^[0-9]+$ || ! "$3" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'NO_GO_HOST_CLASSIFIER_ARGUMENTS'
  exit 42
fi
status=$1
ssh_rc=$2
expected_sha=$3

required=(
  "EXPECTED_SHA=${expected_sha:0:12}"
  'DEPLOY_SHA_EXACT=PASS'
  'DEPLOY_FAILED_SHA=CLEAR'
  'DEPLOY_LOG_SUCCESS=PASS'
  'RECENT_BACKUP_INTEGRITY=PASS'
  'CONTAINER_nfcore-db=PASS'
  'CONTAINER_nfcore-api=PASS'
  'CONTAINER_nfcore-portal=PASS'
  'API_READY=PASS'
  'PORTAL_READY=PASS'
  'SCHEMA_PRODUCTION_GUARD=PASS'
)
for proof in "${required[@]}"; do
  grep -Fxq "$proof" "$status" || { echo 'NO_GO_HOST_BASELINE_INCOMPLETE'; exit 1; }
done
# Any blocked host control is a hard fail even if the output also carries a
# superficially acceptable RESULT. The fixed root-owned script is authoritative.
if grep -Eq '=BLOCKED$' "$status"; then
  echo 'NO_GO_HOST_CONTROL_BLOCKED'
  exit 1
fi
if grep -Fxq 'RESULT=HOST_GATES_PASS_EXTERNAL_STILL_UNVERIFIED' "$status"; then
  [[ "$ssh_rc" -eq 0 ]] || { echo 'NO_GO_HOST_AUDIT_EXIT_MISMATCH'; exit 1; }
elif grep -Fxq 'RESULT=CODE_READY_BUT_BLING_NOT_ACTIVE' "$status"; then
  [[ "$ssh_rc" -eq 1 ]] || { echo 'NO_GO_BLING_EXIT_MISMATCH'; exit 1; }
else
  echo 'NO_GO_HOST_AUDIT_FAILED_OR_INCOMPLETE'
  exit 1
fi
echo 'SSH_CHANNEL_AND_NFCORE_HOST_BASELINE_PASS'
