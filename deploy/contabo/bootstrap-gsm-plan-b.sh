#!/usr/bin/env bash
# One-time, root-operated NFCore GSM audit bootstrap. Not an SSH command.
# Installs exactly the audited three scripts from a pinned main commit.
# NEVER grants sudo/Docker rights, edits credentials or starts containers.
set -Eeuo pipefail
umask 077
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

usage() {
  printf '%s\n' 'usage: bootstrap-gsm-plan-b.sh --check|--apply <approved-main-sha40>' >&2
  exit 64
}
[[ $# -eq 2 ]] || usage
mode=$1
sha=$2
[[ "$mode" == '--check' || "$mode" == '--apply' ]] || usage
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || usage

readonly REPO=/opt/fm/nfcore/src
readonly AUDIT_DIR=/usr/local/libexec/nfcore-audit
readonly EXPECTED_HOST=vmi3692211
readonly BACKUP_BASE=/var/backups/nfcore-gsm-plan-b

[[ "$(id -u)" == 0 ]] || { echo 'NO_GO_REQUIRE_ROOT'; exit 42; }
[[ "$(hostname -s)" == "$EXPECTED_HOST" ]] || { echo 'NO_GO_UNEXPECTED_HOST'; exit 42; }
[[ -d "$REPO/.git" ]] || { echo 'NO_GO_SOURCE_REPOSITORY_MISSING'; exit 42; }

trusted() {
  local p=$1
  [[ -e "$p" && ! -L "$p" && "$(stat -c %u -- "$p")" == 0 ]] || return 1
  [[ -z "$(find "$p" -maxdepth 0 -perm /022 -print -quit 2>/dev/null)" ]]
}
for p in / /usr /usr/local /usr/local/libexec "$AUDIT_DIR"; do
  trusted "$p" || { echo 'NO_GO_UNTRUSTED_AUDIT_DIRECTORY'; exit 42; }
done
[[ -d "$AUDIT_DIR" ]] || { echo 'NO_GO_AUDIT_DIRECTORY_MISSING'; exit 42; }
for p in "$AUDIT_DIR/bling-operational-host-audit.sh" "$AUDIT_DIR/ssh-gate.sh" "$AUDIT_DIR/root-audit.sh"; do
  trusted "$p" || { echo 'NO_GO_UNTRUSTED_EXISTING_GATE'; exit 42; }
  [[ -f "$p" ]] || { echo 'NO_GO_EXISTING_GATE_NOT_FILE'; exit 42; }
done
command -v visudo >/dev/null || { echo 'NO_GO_VISUDO_UNAVAILABLE'; exit 42; }
visudo -c >/dev/null || { echo 'NO_GO_SUDOERS_INVALID'; exit 42; }

# Source checkout must already have the reviewed main ref, fetched separately by unprivileged operator.
# No network, hooks or Git fetch are invoked as root; checkout and application stay unchanged.
current_main=$(git -c safe.directory="$REPO" -C "$REPO" rev-parse --verify refs/remotes/origin/main)
[[ "$current_main" == "$sha" ]] || { echo 'NO_GO_UNAPPROVED_MAIN_SHA'; exit 42; }

stage=$(mktemp -d /tmp/nfcore-gsm-bootstrap.XXXXXXXX)
chmod 0700 "$stage"
backup_dir=''
changed=()
cleanup() {
  local rc=$?
  trap - EXIT
  if [[ "$rc" -ne 0 && "${#changed[@]}" -gt 0 ]]; then
    for ((i=${#changed[@]}-1; i>=0; i--)); do
      local name=${changed[i]}
      if [[ -f "$backup_dir/$name" ]]; then
        cp -p -- "$backup_dir/$name" "$AUDIT_DIR/$name" || true
      else
        rm -f -- "$AUDIT_DIR/$name" || true
      fi
    done
    echo 'NO_GO_INSTALL_REVERTED' >&2
  fi
  rm -rf -- "$stage"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

names=(worker-readonly-preflight.py root-audit.sh ssh-gate.sh)
sources=(deploy/contabo/worker-readonly-preflight.py deploy/contabo/root-host-audit.sh deploy/contabo/host-audit-command.sh)
for i in "${!names[@]}"; do
  git -c safe.directory="$REPO" -C "$REPO" show "$sha:${sources[i]}" > "$stage/${names[i]}"
done
bash -n "$stage/root-audit.sh"
bash -n "$stage/ssh-gate.sh"
python3 -I -c 'import ast,sys; ast.parse(open(sys.argv[1], encoding="utf-8").read())' "$stage/worker-readonly-preflight.py"
for name in "${names[@]}"; do
  printf 'REVIEWED_' 
  sha256sum -- "$stage/$name"
done
if [[ "$mode" == '--check' ]]; then
  echo 'CHECK_ONLY_NO_HOST_MUTATION'
  exit 0
fi

# Persist previous reviewed gate files for explicit rollback.
for p in /var /var/backups; do
  trusted "$p" || { echo 'NO_GO_UNTRUSTED_BACKUP_PARENT'; exit 42; }
done
if [[ -e "$BACKUP_BASE" ]]; then
  trusted "$BACKUP_BASE" || { echo 'NO_GO_UNTRUSTED_BACKUP_DIRECTORY'; exit 42; }
else
  install -d -o root -g root -m 0700 "$BACKUP_BASE"
fi
backup_dir="$BACKUP_BASE/$sha-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -o root -g root -m 0700 "$backup_dir"
for name in "${names[@]}"; do
  dest="$AUDIT_DIR/$name"
  if [[ -e "$dest" || -L "$dest" ]]; then
    trusted "$dest" && [[ -f "$dest" ]] || { echo 'NO_GO_UNTRUSTED_EXISTING_FILE'; exit 42; }
    cp -p -- "$dest" "$backup_dir/$name"
  fi
done
for name in "${names[@]}"; do
  dest="$AUDIT_DIR/$name"
  candidate=$(mktemp "$AUDIT_DIR/.bootstrap.XXXXXXXX")
  install -o root -g root -m 0555 "$stage/$name" "$candidate"
  changed+=("$name")
  mv -fT -- "$candidate" "$dest"
  cmp -s -- "$stage/$name" "$dest" || { echo 'NO_GO_FILE_MISMATCH'; exit 42; }
  trusted "$dest" || { echo 'NO_GO_UNTRUSTED_INSTALLED_FILE'; exit 42; }
done
bash -n "$AUDIT_DIR/root-audit.sh"
bash -n "$AUDIT_DIR/ssh-gate.sh"
visudo -c >/dev/null
echo 'GSM_PLAN_B_GATE_INSTALLED_AUDIT_ONLY'
echo 'NEXT=RUN_PROTECTED_MAIN_GSM_READONLY_WORKFLOW'
echo 'NO_WORKERS_OR_SECRETS_CHANGED'
