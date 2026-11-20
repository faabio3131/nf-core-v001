#!/usr/bin/env bash
# CI only: exact legacy source -> v21 -> candidate v23 -> isolated v21 recovery.
# No host production database, credentials, volumes, ports, or fiscal traffic.
set -Eeuo pipefail
umask 077
[[ "${GITHUB_ACTIONS:-}" == true && "${CI:-}" == true ]] || {
  echo 'NO_GO: this rehearsal is restricted to disposable GitHub CI' >&2
  exit 42
}
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LEGACY_SHA=ea4bdd3bcb9b61e6522081a14e5cc9ad1ced9599
git -C "$ROOT" cat-file -e "$LEGACY_SHA^{commit}"
TMP="$(mktemp -d)"
SUFFIX="$(python -c 'import secrets; print(secrets.token_hex(8))')"
NET="nfcore-cutover-ci-$SUFFIX"
DB="nfcore-cutover-db-$SUFFIX"
OLD_API="nfcore-api:cutover-$SUFFIX"
OLD_WORKER="nfcore-worker:cutover-$SUFFIX"
DB_CID=''
NET_ID=''
cleanup() {
  if [[ -n "$DB_CID" ]]; then docker rm -fv "$DB_CID" >/dev/null 2>&1 || true; fi
  if [[ -n "$NET_ID" ]]; then docker network rm "$NET_ID" >/dev/null 2>&1 || true; fi
  docker image rm "$OLD_API" "$OLD_WORKER" >/dev/null 2>&1 || true
  rm -rf -- "$TMP"
}
trap cleanup EXIT
mkdir "$TMP/legacy"
# Only tracked source is extracted with normal source-file modes. Keep the
# enclosing temp directory and all dumps, logs and generated data private.
git -C "$ROOT" -c tar.umask=0022 archive "$LEGACY_SHA" | (
  umask 022
  tar --no-same-permissions -x -C "$TMP/legacy"
)
docker build -f "$TMP/legacy/Dockerfile.api" -t "$OLD_API" "$TMP/legacy"
docker build -f "$TMP/legacy/Dockerfile.worker" -t "$OLD_WORKER" "$TMP/legacy"
docker image inspect nfcore-api:test nfcore-worker:test >/dev/null
# Verify source readability as the actual non-root runtime user before any DB.
for api_image in "$OLD_API" nfcore-api:test; do
  docker run --rm --network none "$api_image" python -c '
import os
from pathlib import Path
assert os.getuid() == 10001, "unexpected runtime UID"
assert os.getgid() == 10001, "unexpected runtime GID"
p = Path("/app/scripts/ci/migration_guard.py")
compile(p.read_bytes(), str(p), "exec")
print("NONROOT_MIGRATION_GUARD_READABLE")
'
done
NET_ID="$(docker network create --internal "$NET")"
[[ "$(docker network inspect --format '{{.Internal}}' "$NET_ID")" == true ]]
PW="$(python -c 'import secrets; print(secrets.token_hex(24))')"
DB_CID="$(docker run -d --pull=never --name "$DB" --network "$NET" \
  --network-alias db --memory 768m --cpus 2 --pids-limit 128 \
  -e POSTGRES_USER=nfcore -e POSTGRES_PASSWORD="$PW" \
  -e POSTGRES_DB=nfcore_cutover_test postgres:16-alpine)"
for _ in $(seq 1 40); do
  if docker exec "$DB_CID" pg_isready -h 127.0.0.1 -U nfcore -d nfcore_cutover_test >/dev/null; then break; fi
  sleep 1
done
docker exec "$DB_CID" pg_isready -h 127.0.0.1 -U nfcore -d nfcore_cutover_test >/dev/null
SRC_DB=nfcore_cutover_test
RESTORE_DB=nfcore_cutover_rollback_test
dsn() { printf 'postgresql://nfcore:%s@db:5432/%s' "$PW" "$1"; }
sql() {
  docker exec "$DB_CID" psql -X -v ON_ERROR_STOP=1 -U nfcore -d "$1" -Atq -c "$2"
}
ledger() { sql "$1" "SELECT string_agg(version::text, ',' ORDER BY version) FROM fm_schema_migrations"; }
guard() {
  local image="$1" database="$2" profile="$3" bling="$4" action="$5"
  local -a approvals=()
  if [[ "$action" == --apply ]]; then
    approvals=(-e NFCORE_SCHEMA_MIGRATION_APPROVED=true)
    if [[ "$profile" == production ]]; then
      approvals+=(-e NFCORE_PRODUCTION_APPROVAL=PRODUCTION_APPROVED)
    fi
  fi
  docker run --rm --network "$NET" \
    -e DATABASE_URL="$(dsn "$database")" -e NFCORE_ENVIRONMENT="$profile" \
    -e NFCORE_BLING_INSTALLATIONS_ENABLED="$bling" "${approvals[@]}" \
    "$image" python scripts/ci/migration_guard.py "$action"
}
probe() {
  local api="$1" worker="$2" database="$3"
  local -a envs=(
    -e DATABASE_URL="$(dsn "$database")"
    -e NFCORE_ENVIRONMENT=staging
    -e NFCORE_PERSISTENCE_BACKEND=postgres
    -e NFCORE_SECRET_BACKEND=external
    -e NFCORE_REQUIRE_HTTPS=true
  )
  docker run --rm --network "$NET" "${envs[@]}" "$api" python -c '
from kordena_fiscal.runtime.api import RuntimeApi
from kordena_fiscal.runtime.config import RuntimeSettings
runtime = RuntimeApi(RuntimeSettings.from_environ())
try:
    assert runtime.ready() == (True, "ready"), "runtime not ready"
finally:
    runtime.close()
print("API_SCHEMA_READINESS_PASS")
'
  docker run --rm --network "$NET" "${envs[@]}" -e NFCORE_WORKER_ONESHOT=true "$worker"
  echo 'WORKER_ONESHOT_PASS'
}
# Use exact historical migration authority, not a fabricated version ledger.
guard "$OLD_API" "$SRC_DB" staging true --apply
[[ "$(ledger "$SRC_DB")" == "$(seq -s, 1 21)" ]]
guard "$OLD_API" "$SRC_DB" production true --assert-current-production
probe "$OLD_API" "$OLD_WORKER" "$SRC_DB"
sql "$SRC_DB" "CREATE TABLE cutover_rehearsal_sentinel (id integer PRIMARY KEY, value text NOT NULL)"
sql "$SRC_DB" "INSERT INTO cutover_rehearsal_sentinel VALUES (1, 'preserve-v21')"
TABLES="SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
sql "$SRC_DB" "$TABLES" | LC_ALL=C sort > "$TMP/before-tables"
# Reuse the canonical backup/restore scripts entirely inside the disposable PG.
docker cp "$ROOT/scripts/postgres_backup.sh" "$DB_CID:/tmp/nfcore-cutover-backup.sh"
docker cp "$ROOT/scripts/postgres_restore.sh" "$DB_CID:/tmp/nfcore-cutover-restore.sh"
docker exec -e DATABASE_URL="postgresql://nfcore:$PW@127.0.0.1:5432/$SRC_DB" \
  "$DB_CID" sh /tmp/nfcore-cutover-backup.sh /tmp/cutover-v21.dump
guard nfcore-api:test "$SRC_DB" production false --plan-production-bling
guard nfcore-api:test "$SRC_DB" production false --apply
[[ "$(ledger "$SRC_DB")" == "$(seq -s, 1 23)" ]]
guard nfcore-api:test "$SRC_DB" production false --assert-current-production
# Repeat the same approved synthetic apply: migrations must be idempotent.
guard nfcore-api:test "$SRC_DB" production false --apply
[[ "$(ledger "$SRC_DB")" == "$(seq -s, 1 23)" ]]
[[ "$(sql "$SRC_DB" "SELECT value FROM cutover_rehearsal_sentinel WHERE id=1")" == preserve-v21 ]]
sql "$SRC_DB" "$TABLES" | LC_ALL=C sort > "$TMP/after-tables"
[[ -z "$(LC_ALL=C comm -23 "$TMP/before-tables" "$TMP/after-tables")" ]]
probe nfcore-api:test nfcore-worker:test "$SRC_DB"
echo 'UPGRADE_V21_V23_PASS'
# A simple old-image rollback is prohibited once the schema changes.
if guard "$OLD_API" "$SRC_DB" production true --assert-current-production >"$TMP/old-guard.log" 2>&1; then
  echo 'NO_GO: old guard unexpectedly accepted v23' >&2
  exit 42
fi
grep -Fq 'production schema has pending/drifted fiscal migrations' "$TMP/old-guard.log"
echo 'OLD_IMAGE_ON_V23_REJECTED'
# Recovery before reopening writes is tested in a DIFFERENT database.
sql postgres "CREATE DATABASE $RESTORE_DB"
docker exec -e DATABASE_URL="postgresql://nfcore:$PW@127.0.0.1:5432/$RESTORE_DB" \
  "$DB_CID" sh /tmp/nfcore-cutover-restore.sh /tmp/cutover-v21.dump
[[ "$(ledger "$RESTORE_DB")" == "$(seq -s, 1 21)" ]]
[[ "$(sql "$RESTORE_DB" "SELECT value FROM cutover_rehearsal_sentinel WHERE id=1")" == preserve-v21 ]]
sql "$RESTORE_DB" "$TABLES" | LC_ALL=C sort > "$TMP/restored-tables"
cmp "$TMP/before-tables" "$TMP/restored-tables"
guard "$OLD_API" "$RESTORE_DB" production true --assert-current-production
probe "$OLD_API" "$OLD_WORKER" "$RESTORE_DB"
# Recovery never overwrites the upgraded database.
[[ "$(ledger "$SRC_DB")" == "$(seq -s, 1 23)" ]]
echo 'PRE_CUTOVER_RECOVERY_V21_PASS'
echo "LEGACY_SHA=$LEGACY_SHA"
echo "CANDIDATE_SHA=$(git -C "$ROOT" rev-parse HEAD)"
echo 'REHEARSAL_PASS_NO_PRODUCTION_ACCESS_NO_EXTERNAL_FISCAL_IO'
