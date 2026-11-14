#!/usr/bin/env bash
# NFCore: sudoers-pinned zero-argument privilege boundary for read-only audit.
# Approved installation path: /usr/local/libexec/nfcore-audit/root-audit.sh
# Do NOT add the SSH account to the docker group or grant unrestricted sudo.
set -Eeuo pipefail
umask 077

readonly ROOT_AUDIT_DIR=/usr/local/libexec/nfcore-audit
readonly BLING_AUDIT_SCRIPT=$ROOT_AUDIT_DIR/bling-operational-host-audit.sh
readonly GSM_AUDIT_SCRIPT=$ROOT_AUDIT_DIR/worker-readonly-preflight.py
readonly A1_AUDIT_SCRIPT=$ROOT_AUDIT_DIR/audit-a1-vault-readonly.py
ROOT_AUDIT_SCRIPT=''

# Reject symlinks, non-owner-controlled files and writable ancestors.
# Callers may supply an expected owner for pure, unprivileged CI tests only.
trust_path() {
  local path=$1 expected_owner=$2
  [[ -e "$path" && ! -L "$path" ]] || return 1
  [[ "$(stat -c '%u' -- "$path")" == "$expected_owner" ]] || return 1
  [[ -z "$(find "$path" -maxdepth 0 -perm /022 -print -quit 2>/dev/null)" ]] || return 1
}

check_trusted_audit_chain() {
  local path
  for path in \
    / /usr /usr/local /usr/local/libexec "$ROOT_AUDIT_DIR" \
    "$ROOT_AUDIT_DIR/ssh-gate.sh" \
    "$ROOT_AUDIT_DIR/root-audit.sh" \
    "$ROOT_AUDIT_SCRIPT"; do
    if ! trust_path "$path" 0; then
      printf '%s\n' 'NO_GO_UNTRUSTED_AUDIT_PATH' >&2
      return 1
    fi
  done
  [[ -d "$ROOT_AUDIT_DIR" && -f "$ROOT_AUDIT_SCRIPT" ]] || return 1
}

# The only privileged input is a short, newline-terminated pair of hashes.
# -n 106 caps untrusted first-line data; a trailing extra line is forbidden.
parse_root_audit_request() {
  local payload='' trailing=''
  # Bling legacy pair = 105 characters; GSM tagged pair = 109, A1 tagged = 108.
  IFS= read -r -n 110 -t 3 payload || return 1
  if IFS= read -r -n 1 -t 1 trailing || [[ -n "$trailing" ]]; then
    return 1
  fi
  local request_pattern='^((gsm|a1) )?([0-9a-f]{40}) ([0-9a-f]{64})$'
  if [[ "$payload" =~ $request_pattern ]]; then
    ROOT_AUDIT_KIND="bling"
    [[ -n "${BASH_REMATCH[2]}" ]] && ROOT_AUDIT_KIND="${BASH_REMATCH[2]}"
    ROOT_AUDIT_SHA="${BASH_REMATCH[3]}"
    ROOT_AUDIT_DIGEST="${BASH_REMATCH[4]}"
    return 0
  fi
  return 1
}

main() {
  [[ "$(id -u)" == 0 ]] || { echo 'NO_GO_ROOT_AUDIT_PRIVILEGE' >&2; exit 42; }
  if ! parse_root_audit_request; then
    echo 'NO_GO_ROOT_AUDIT_REQUEST' >&2
    exit 42
  fi
  # Select only a fixed root-owned audit program, never a caller path.
  if [[ "$ROOT_AUDIT_KIND" == "gsm" ]]; then
    ROOT_AUDIT_SCRIPT=$GSM_AUDIT_SCRIPT
  elif [[ "$ROOT_AUDIT_KIND" == "a1" ]]; then
    ROOT_AUDIT_SCRIPT=$A1_AUDIT_SCRIPT
  else
    ROOT_AUDIT_SCRIPT=$BLING_AUDIT_SCRIPT
  fi
  check_trusted_audit_chain || exit 42
  local calculated_digest
  calculated_digest=$(sha256sum "$ROOT_AUDIT_SCRIPT")
  calculated_digest="${calculated_digest%% *}"
  [[ "$calculated_digest" == "$ROOT_AUDIT_DIGEST" ]] || {
    echo 'NO_GO_AUDIT_SCRIPT_DIGEST' >&2
    exit 42
  }

  # Never eval a caller's command or run code from /opt/fm/nfcore/src.
  # Docker inspection is permitted only inside this fixed, root-owned script.
  if [[ "$ROOT_AUDIT_KIND" == "gsm" ]]; then
    exec /usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C HOME=/nonexistent \
      /usr/bin/python3 -I "$ROOT_AUDIT_SCRIPT" \
        --expected-production-sha "$ROOT_AUDIT_SHA" </dev/null
  fi
  if [[ "$ROOT_AUDIT_KIND" == "a1" ]]; then
    exec /usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C HOME=/nonexistent \
      /usr/bin/python3 -I "$ROOT_AUDIT_SCRIPT" \
        --expected-production-sha "$ROOT_AUDIT_SHA" </dev/null
  fi
  exec /usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C HOME=/nonexistent \
    /bin/bash "$ROOT_AUDIT_SCRIPT" "$ROOT_AUDIT_SHA" </dev/null
}

# Sourcing is strictly for local parser and permission unit tests.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
