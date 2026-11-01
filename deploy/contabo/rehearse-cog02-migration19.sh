#!/usr/bin/env bash
# READ-ONLY ON LIVE NFCORE. Restore latest verified dump into an isolated,
# volatile PostgreSQL container and rehearse canonical additive migration 19.
set -Eeuo pipefail
umask 077
BACKUP="$1"
SOURCE="$2"
case "$BACKUP" in /opt/fm/backups/nfcore-diario/nfcore-*.dump) ;; *) echo "NO_GO backup path" >&2; exit 42 ;; esac
[ -f "$BACKUP" ] && [ -f "$BACKUP.sha256" ] && [ -f "$SOURCE" ] || exit 42
[ ! -L "$BACKUP" ] && [ ! -L "$SOURCE" ] || exit 42
(cd "$(dirname "$BACKUP")" && sha256sum -c "$(basename "$BACKUP").sha256" >/dev/null) ||
  { echo "NO_GO dump checksum" >&2; exit 42; }
command -v docker >/dev/null
command -v python3 >/dev/null
command -v openssl >/dev/null
SCRATCH="$(mktemp -d /tmp/nfcore-cog02-rehearsal.XXXXXXXX)"
C="nfcore-cog02-rehearsal-$(date +%s)-$$"
cleanup() { docker rm -f "$C" >/dev/null 2>&1 || :; rm -rf -- "$SCRATCH"; }
trap cleanup EXIT

# Import exact canonical schema from the pinned main commit: do not create a
# second migration implementation. Only the disposable container receives DDL.
python3 - "$SOURCE" > "$SCRATCH/m19.sql" <<'PY'
import importlib.util
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("cog02_canonical_schema", path)
if spec is None or spec.loader is None:
    raise SystemExit("schema module unavailable")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
ddl = tuple(mod.COGNITIVE_QUOTA_SCHEMA)
if not (
    mod.COGNITIVE_QUOTA_VERSION == 19
    and mod.COGNITIVE_QUOTA_NAME == "cognitive_token_reservations"
    and len(ddl) == 2
    and ddl[0].lstrip().startswith("CREATE TABLE fm_cognitive_token_counters (")
    and ddl[1].lstrip().startswith("CREATE TABLE fm_cognitive_token_reservations (")
):
    raise SystemExit("NO_GO unexpected migration")
for statement in ddl:
    if ";" in statement or any(term in statement.upper() for term in
                               ("DROP ", "TRUNCATE ", "ALTER ", "DELETE ", "UPDATE ")):
        raise SystemExit("NO_GO unsafe migration statement")
print("BEGIN;")
for statement in ddl:
    print(statement + ";")
print("INSERT INTO fm_schema_migrations(version,name,applied_at) VALUES "
      "(19,'cognitive_token_reservations','2026-11-01T00:00:00Z');")
print("COMMIT;")
PY

PASS="$(openssl rand -hex 24)"
docker run --rm -d --pull never --name "$C" --network none \
  --tmpfs /var/lib/postgresql/data:rw,nosuid,size=512m \
  -e POSTGRES_DB=nfcore -e POSTGRES_USER=nfcore \
  -e POSTGRES_PASSWORD="$PASS" postgres:16-alpine >/dev/null
unset PASS
ready=0
for i in $(seq 1 40); do
  if docker exec "$C" pg_isready -q -U nfcore -d nfcore >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 1
done
[ "$ready" = 1 ] || { echo "NO_GO isolated DB startup" >&2; exit 42; }
docker cp "$BACKUP" "$C:/tmp/nfcore.dump" >/dev/null
docker exec "$C" pg_restore -U nfcore -d nfcore \
  --no-owner --no-acl --exit-on-error /tmp/nfcore.dump >/dev/null

installed="$(docker exec "$C" psql -X -v ON_ERROR_STOP=1 -U nfcore -d nfcore \
  -At -c "SELECT string_agg(version::text, ',' ORDER BY version) FROM fm_schema_migrations")"
[ "$installed" = "$(seq -s, 1 18)" ] || { echo "NO_GO restored fiscal ledger" >&2; exit 42; }
cakto="$(docker exec "$C" psql -X -v ON_ERROR_STOP=1 -U nfcore -d nfcore \
  -At -c "SELECT string_agg(version::text, ',' ORDER BY version) FROM fm_cakto_schema_migrations")"
[ "$cakto" = "1,2" ] || { echo "NO_GO restored Cakto ledger" >&2; exit 42; }
tables_before="$(docker exec "$C" psql -X -U nfcore -d nfcore -At \
  -c "SELECT count(*) FROM pg_tables WHERE schemaname='public'")"

# Only SHA256 fingerprint is retained/printed; customer records stay in
# isolated in-memory Postgres and are never displayed in output.
legacy_hash() {
  # A fixed restrict key is safe here because the generated SQL is NEVER
  # executed; it only normalizes the fingerprint comparison. PostgreSQL 16+
  # otherwise emits a different random key on every pg_dump invocation.
  docker exec "$C" pg_dump -U nfcore -d nfcore --data-only \
    --restrict-key=NFCoreCog02FingerprintOnly --no-owner --no-acl --inserts \
    --exclude-table=public.fm_schema_migrations \
    --exclude-table=public.fm_cognitive_token_counters \
    --exclude-table=public.fm_cognitive_token_reservations |
    sha256sum | awk '{print $1}'
}
before="$(legacy_hash)"
docker cp "$SCRATCH/m19.sql" "$C:/tmp/m19.sql" >/dev/null
docker exec "$C" psql -X -v ON_ERROR_STOP=1 -U nfcore -d nfcore \
  -f /tmp/m19.sql >/dev/null
installed_after="$(docker exec "$C" psql -X -U nfcore -d nfcore -At \
  -c "SELECT string_agg(version::text, ',' ORDER BY version) FROM fm_schema_migrations")"
[ "$installed_after" = "$(seq -s, 1 19)" ] || { echo "NO_GO migration ledger" >&2; exit 42; }
tables_after="$(docker exec "$C" psql -X -U nfcore -d nfcore -At \
  -c "SELECT count(*) FROM pg_tables WHERE schemaname='public'")"
[ "$tables_after" -eq "$((tables_before + 2))" ] ||
  { echo "NO_GO unexpected table count" >&2; exit 42; }
after="$(legacy_hash)"
[ "$after" = "$before" ] || { echo "NO_GO legacy data fingerprint changed" >&2; exit 42; }
exists="$(docker exec "$C" psql -X -U nfcore -d nfcore -At \
  -c "SELECT to_regclass('public.fm_cognitive_token_counters') IS NOT NULL AND to_regclass('public.fm_cognitive_token_reservations') IS NOT NULL")"
[ "$exists" = t ] || { echo "NO_GO canonical tables missing" >&2; exit 42; }
echo "PASS: isolated restore checksum valid, fiscal 1..18, Cakto 1..2"
echo "PASS: canonical migration19 to 1..19, two additive tables"
echo "PASS: legacy application data preserved, no live database operations"
