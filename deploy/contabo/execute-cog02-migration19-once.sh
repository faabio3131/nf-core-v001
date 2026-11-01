#!/usr/bin/env bash
# ONE-SHOT COG-02 production migration19 using the canonical migration_guard.
# Requires explicit human approval. No deploy, no service restart, no live .env read.
set -Eeuo pipefail
umask 077
ROOT=/opt/fm/nfcore
STAGE=/opt/fm/nfcore/.safe-deploy-stage-20261101
EXPECTED_SHA=79172ef9125c49f1e60e5a0a56e6b4c5f67c71be
IMAGE=nfcore-cog02-migration19:d3d1002
test "$1" = --authorized-migration19
test "$2" = "$EXPECTED_SHA"
exec 9>/tmp/nfcore-deploy.lock
flock -x -w 60 9 || { echo "NO_GO lock unavailable"; exit 42; }
[ "$(sed -n 's/^SHA=//p' "$ROOT/.deployed")" = "$EXPECTED_SHA" ] ||
  { echo "NO_GO unexpected deployed SHA"; exit 42; }
[ "$(git -C "$ROOT/src" rev-parse HEAD)" = "$EXPECTED_SHA" ] ||
  { echo "NO_GO unexpected checkout"; exit 42; }
[ "$(git -C "$ROOT/src" ls-remote origin refs/heads/production | cut -f1)" = "$EXPECTED_SHA" ] ||
  { echo "NO_GO production branch moved"; exit 42; }
test ! -s "$ROOT/.failed-sha" ||
  { echo "NO_GO failure marker exists"; exit 42; }
[ "$(grep -Ec -- '--apply|nf_restore_db|NFCORE_SCHEMA_MIGRATION_APPROVED=true|NFCORE_PRODUCTION_APPROVAL=PRODUCTION_APPROVED' "$ROOT/deploy.sh" || :)" = 0 ] ||
  { echo "NO_GO unsafe installed deploy"; exit 42; }
for SERVICE in nfcore-db nfcore-api nfcore-portal; do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$SERVICE")" = healthy ] ||
    { echo "NO_GO unhealthy runtime"; exit 42; }
done
docker image inspect "$IMAGE" >/dev/null
VERSIONS="$(docker exec nfcore-db psql -X -v ON_ERROR_STOP=1 -U nfcore -d nfcore -Atc "SELECT string_agg(version::text, ',' ORDER BY version) FROM fm_schema_migrations")"
CAKTO="$(docker exec nfcore-db psql -X -v ON_ERROR_STOP=1 -U nfcore -d nfcore -Atc "SELECT string_agg(version::text, ',' ORDER BY version) FROM fm_cakto_schema_migrations")"
[ "$VERSIONS" = "$(seq -s, 1 18)" ] && [ "$CAKTO" = "1,2" ] ||
  { echo "NO_GO schema baseline unexpected"; exit 42; }
EXISTING="$(docker exec nfcore-db psql -X -v ON_ERROR_STOP=1 -U nfcore -d nfcore -Atc "SELECT (to_regclass('public.fm_cognitive_token_counters') IS NOT NULL) OR (to_regclass('public.fm_cognitive_token_reservations') IS NOT NULL)")"
[ "$EXISTING" = f ] || { echo "NO_GO migration tables already exist"; exit 42; }

OVERRIDE="$STAGE/cog02-one-shot-compose.yml"
test ! -e "$OVERRIDE" || { echo "NO_GO override exists"; exit 42; }
cat > "$OVERRIDE" <<'YAML'
services:
  nfcore-api:
    image: nfcore-cog02-migration19:d3d1002
YAML
IMAGES="$(docker compose -f "$ROOT/docker-compose.yml" -f "$OVERRIDE" config --images)"
printf '%s\n' "$IMAGES" | grep -Fxq "$IMAGE" ||
  { echo "NO_GO migration image compose mismatch"; exit 42; }
docker compose -f "$ROOT/docker-compose.yml" -f "$OVERRIDE" config --quiet

# New backup under lock, no DDL until checksum and structure are verified.
BACKUP_OUT="$("$ROOT/backup.sh")" ||
  { echo "NO_GO pre-migration backup failed"; exit 42; }
BACKUP="$(printf '%s\n' "$BACKUP_OUT" | awk '$1=="OK" {print $2}')"
[ -n "$BACKUP" ] && [ -f "$BACKUP" ] && [ -f "$BACKUP.sha256" ] ||
  { echo "NO_GO backup missing"; exit 42; }
(cd "$(dirname "$BACKUP")" && sha256sum -c "$(basename "$BACKUP").sha256" >/dev/null) ||
  { echo "NO_GO backup checksum"; exit 42; }
echo "BACKUP_VERIFIED=$(basename "$BACKUP")"
LOG="$STAGE/migration19-production-guarded.log"
test ! -e "$LOG" || { echo "NO_GO previous migration log exists"; exit 42; }

# Exactly one DB-write authority. The approved environment variables are only
# supplied to this one-shot candidate container, not deployed services or cron.
if ! docker compose -f "$ROOT/docker-compose.yml" -f "$OVERRIDE" \
  run --rm --no-deps -T \
  -e NFCORE_SCHEMA_MIGRATION_APPROVED=true \
  -e NFCORE_PRODUCTION_APPROVAL=PRODUCTION_APPROVED \
  nfcore-api python scripts/ci/migration_guard.py --apply >"$LOG" 2>&1; then
  echo "NO_GO migration orchestrator failed. Restricted diagnostic log at $LOG"
  echo "NO automatic DB restore. Investigate current ledger and service health."
  exit 42
fi
echo "CANONICAL_MIGRATION_GUARD_PASS"

AFTER="$(docker exec nfcore-db psql -X -v ON_ERROR_STOP=1 -U nfcore -d nfcore -Atc "SELECT string_agg(version::text, ',' ORDER BY version) FROM fm_schema_migrations")"
[ "$AFTER" = "$(seq -s, 1 19)" ] ||
  { echo "NO_GO unexpected post-migration ledger"; exit 42; }
TABLES="$(docker exec nfcore-db psql -X -v ON_ERROR_STOP=1 -U nfcore -d nfcore -Atc "SELECT (to_regclass('public.fm_cognitive_token_counters') IS NOT NULL) AND (to_regclass('public.fm_cognitive_token_reservations') IS NOT NULL)")"
[ "$TABLES" = t ] || { echo "NO_GO missing tables"; exit 42; }
docker exec nfcore-api python -c "import os; from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase; db=PostgresFiscalDatabase(os.environ['DATABASE_URL']); print('BRIDGE_SCHEMA=' + str(len(db.require_current_schema()))); db.close()"
echo "PRODUCTION_MIGRATION19_APPLIED_VERIFIED; deploy unchanged; backup=$BACKUP"
