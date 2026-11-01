#!/usr/bin/env bash
# COG-02 release preflight for the Contabo NFCore host.
# READ-ONLY: NO git checkout/fetch/push, docker compose, pg_dump, DDL or service changes.
# This is a diagnostic gate, NEVER an authorization to migrate/deploy.
set -euo pipefail

ROOT="${NFCORE_ROOT:-/opt/fm/nfcore}"
SRC="$ROOT/src"
DATABASE_CONTAINER="${NFCORE_DBCONT:-nfcore-db}"
DATABASE_NAME="${NFCORE_DBNAME:-nfcore}"
DATABASE_USER="${NFCORE_DBUSER:-nfcore}"
EXIT_BLOCKED=42

blocked() {
  printf 'COG02 PREFLIGHT NO_GO: %s\n' "$*" >&2
  exit "$EXIT_BLOCKED"
}

command -v git >/dev/null || blocked "git unavailable"
command -v docker >/dev/null || blocked "docker unavailable"
[ -d "$SRC/.git" ] || blocked "canonical checkout missing at $SRC"

# No local ref mutations. Remote branch SHAs come from ls-remote, not a
# possibly stale origin/production cache.
read_remote() {
  git -C "$SRC" ls-remote --exit-code origin "refs/heads/$1" |
    awk 'NR == 1 { print $1 }'
}

main_sha="$(read_remote main)" || blocked "cannot read origin/main"
production_sha="$(read_remote production)" || blocked "cannot read origin/production"
[ -n "$main_sha" ] && [ -n "$production_sha" ] ||
  blocked "remote branch SHA unavailable"

# Frozen target is required; do not promote moving main opportunistically.
target="${NFCORE_COG02_TARGET_MAIN_SHA:-}"
[ -n "$target" ] || blocked "NFCORE_COG02_TARGET_MAIN_SHA not set"
[[ "$target" =~ ^[0-9a-f]{40}$ ]] || blocked "invalid frozen target SHA"
[ "$target" = "$main_sha" ] || blocked "frozen target differs from current main"

deployed=""
if [ -r "$ROOT/.deployed" ]; then
  deployed="$(sed -n 's/^SHA=//p' "$ROOT/.deployed" | head -n 1)"
fi
[[ "$deployed" =~ ^[0-9a-f]{40}$ ]] ||
  blocked "deployed SHA missing or invalid"

for service in nfcore-db nfcore-api nfcore-portal; do
  running="$(docker inspect --format '{{.State.Running}}' "$service" 2>/dev/null)" ||
    blocked "$service missing"
  [ "$running" = true ] || blocked "$service not running"
done

# No secrets are printed. Query only the migration ledger; do not assume the
# currently running container corresponds to the HEAD in the checkout.
installed="$(
  docker exec "$DATABASE_CONTAINER"     psql -X -v ON_ERROR_STOP=1 -U "$DATABASE_USER" -d "$DATABASE_NAME" -At       -c "SELECT COALESCE(string_agg(version::text, ',' ORDER BY version), '') FROM fm_schema_migrations"       2>/dev/null
)" || blocked "unable to inspect production migration ledger"

expected18="$(seq -s, 1 18)"
expected19="$(seq -s, 1 19)"
case "$installed" in
  "$expected18") migration="REQUIRED_SEPARATELY" ;;
  "$expected19") migration="ALREADY_PRESENT" ;;
  *) blocked "schema drift or unexpected installed migrations (neither 1..18 nor 1..19)" ;;
esac

# Cross-check other infrastructure without disclosing environment or DB
# credentials. These are evidence hints, NOT restoration proof.
image_api="$(docker inspect --format '{{.Image}}' nfcore-api)"
image_portal="$(docker inspect --format '{{.Image}}' nfcore-portal)"
[ -n "$image_api" ] && [ -n "$image_portal" ] ||
  blocked "running image digest unavailable"
backup_dir="${NFCORE_BACKUP_DIR:-/opt/fm/backups/nfcore-diario}"
[ -d "$backup_dir" ] || blocked "backup directory unavailable"
backup_count="$(find "$backup_dir" -maxdepth 1 -type f -name 'nfcore-*.dump' | wc -l)"
[ "$backup_count" -gt 0 ] || blocked "no existing backup candidate"

printf 'COG02 PREFLIGHT READ_ONLY\n'
printf 'main=%s\nproduction=%s\ndeployed=%s\n' "$main_sha" "$production_sha" "$deployed"
printf 'api_image=%s\nportal_image=%s\n' "$image_api" "$image_portal"
printf 'migration19=%s\nbackup_candidates=%s\n' "$migration" "$backup_count"
printf 'COG02 NO_GO_FOR_PROMOTION: host SHA, backup restore, canary and controlled migration require separate verified gates\n'
