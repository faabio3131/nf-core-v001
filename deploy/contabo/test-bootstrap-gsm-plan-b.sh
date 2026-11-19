#!/usr/bin/env bash
# CI contract: bootstrap remains an explicit, offline, narrow root operation.
set -Eeuo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
script="$here/bootstrap-gsm-plan-b.sh"
bash -n "$script"
for bad in '' 'not-a-sha' 'main' '000000'; do
  if bash "$script" --apply "$bad" >/dev/null 2>&1; then
    echo 'FAIL: unpinned administrative bootstrap allowed' >&2
    exit 1
  fi
done
grep -Fq '[[ "$(id -u)" == 0 ]]' "$script"
grep -Fq '[[ "$(hostname -s)" == "$EXPECTED_HOST" ]]' "$script"
grep -Fq '[[ "$current_main" == "$sha" ]]' "$script"
grep -Fq 'GSM_PLAN_B_GATE_INSTALLED_AUDIT_ONLY' "$script"
grep -Fq 'NO_WORKERS_OR_SECRETS_CHANGED' "$script"
grep -Fq 'readonly AUDIT_DIR=/usr/local/libexec/nfcore-audit' "$script"
# Never silently grant broader privileges or touch other SaaS or application runtime.
if grep -Eq 'sudoers\.d|usermod|chmod[[:space:]]+777|docker[[:space:]]+(run|compose|exec)|/opt/fm/iron|git[[:space:]].*checkout|git[[:space:]].*fetch' "$script"; then
  echo 'FAIL: out-of-scope change in administrative bootstrap' >&2
  exit 1
fi
echo 'PASS: Plan B restricted GSM bootstrap contract'
