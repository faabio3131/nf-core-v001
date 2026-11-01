#!/usr/bin/env bash
# Mock-only test of the COG-02 preflight; never connects to production.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/root/src/.git" "$TMP/backups"
touch "$TMP/backups/nfcore-fixture.dump"
printf 'SHA=%040d\n' 9 > "$TMP/root/.deployed"
printf '%s\n' '#!/bin/sh' 'python migration_guard.py --assert-current-production' > "$TMP/root/deploy.sh"

cat > "$TMP/bin/git" <<'SH'
#!/usr/bin/env bash
printf 'git %s\n' "$*" >> "$MOCK_CALLS"
case "$*" in
  *"refs/heads/main") printf '%s\trefs/heads/main\n' "$MOCK_MAIN_SHA" ;;
  *"refs/heads/production")
    printf '%s\trefs/heads/production\n' "$MOCK_PRODUCTION_SHA" ;;
  *) exit 70 ;;
esac
SH
cat > "$TMP/bin/docker" <<'SH'
#!/usr/bin/env bash
printf 'docker %s\n' "$*" >> "$MOCK_CALLS"
case "$1" in
  inspect)
    case "$4" in
      nfcore-db|nfcore-api|nfcore-portal)
        if [[ "$3" == *State.Running* ]]; then
          echo true
        else
          echo sha256:synthetic
        fi ;;
      *) exit 70 ;;
    esac ;;
  exec) printf '%s\n' "$MOCK_INSTALLED" ;;
  *) exit 70 ;;
esac
SH
chmod +x "$TMP/bin/git" "$TMP/bin/docker"
export PATH="$TMP/bin:$PATH"
export NFCORE_ROOT="$TMP/root" NFCORE_BACKUP_DIR="$TMP/backups"
export MOCK_CALLS="$TMP/calls"
export MOCK_MAIN_SHA MOCK_PRODUCTION_SHA MOCK_INSTALLED NFCORE_COG02_TARGET_MAIN_SHA
MOCK_MAIN_SHA="$(printf '%040d' 1)"
MOCK_PRODUCTION_SHA="$(printf '%040d' 2)"
export NFCORE_COG02_TARGET_MAIN_SHA="$MOCK_MAIN_SHA"

assert_run() {
  local label="$1" expected_rc="$2" expected_text="$3" actual_rc
  : > "$MOCK_CALLS"
  actual_rc=0
  bash "$HERE/preflight-cog02.sh" >"$TMP/output" 2>&1 || actual_rc=$?
  if [ "$actual_rc" -ne "$expected_rc" ] ||
     ! grep -q "$expected_text" "$TMP/output"; then
    echo "FAIL $label (rc=$actual_rc)" >&2
    cat "$TMP/output" >&2
    exit 1
  fi
  if grep -Eq 'git .* (fetch|checkout|push|reset)\b|docker (compose|run|stop|rm|build)\b|--apply|pg_dump|DROP SCHEMA' "$MOCK_CALLS"; then
    echo "FAIL $label: preflight mutated state" >&2
    cat "$MOCK_CALLS" >&2
    exit 1
  fi
  echo "PASS $label"
}

MOCK_INSTALLED="$(seq -s, 1 18)"
printf '%s\n' "MOUT=\$(\$MG --apply)" >> "$TMP/root/deploy.sh"
assert_run "legacy auto-migration deploy blocked" 42 'automatic migration or database restore'
sed -i '$d' "$TMP/root/deploy.sh"
printf '%s\n' "nf_restore_db synthetic_backup" >> "$TMP/root/deploy.sh"
assert_run "automatic database restore blocked" 42 'automatic migration or database restore'
sed -i '$d' "$TMP/root/deploy.sh"
printf '%s\n' 'NFCORE_SCHEMA_MIGRATION_APPROVED=true' >> "$TMP/root/deploy.sh"
assert_run "hardcoded migration approval blocked" 42 'automatic migration or database restore'
sed -i '$d' "$TMP/root/deploy.sh"
assert_run "legacy migration requires separate approval" 0 'migration19=REQUIRED_SEPARATELY'
MOCK_INSTALLED="$(seq -s, 1 19)"
assert_run "already installed migration does not run DDL" 0 'migration19=ALREADY_PRESENT'
export MOCK_INSTALLED='1,2,4,19'
assert_run "schema drift is blocked" 42 'schema drift'
MOCK_INSTALLED="$(seq -s, 1 18)"
NFCORE_COG02_TARGET_MAIN_SHA="$(printf '%040d' 3)"
assert_run "moving main candidate is blocked" 42 'frozen target differs'
unset NFCORE_COG02_TARGET_MAIN_SHA
assert_run "missing target is blocked" 42 'TARGET_MAIN_SHA not set'
echo "COG-02 preflight mock tests: PASS"
