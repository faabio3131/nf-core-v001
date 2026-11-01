#!/usr/bin/env bash
# ONE-TIME governed repair of Contabo's installed NFCore deploy contract.
# No application code checkout, DB access/DDL, container restart or .env reads.
# Must run with the same flock as the existing production deploy cron.
set -Eeuo pipefail

ROOT="${NFCORE_ROOT:-/opt/fm/nfcore}"
STAGE="${NFCORE_SAFE_DEPLOY_STAGE:-}"
EXPECTED="${NFCORE_EXPECTED_DEPLOYED_SHA:-}"
if [[ "${1:-}" != "--install" || "${NFCORE_HOST_CONTRACT_APPROVED:-}" != "true" ]]; then
  echo "NO_GO: explicit --install and NFCORE_HOST_CONTRACT_APPROVED=true required" >&2
  exit 42
fi
[[ "$EXPECTED" =~ ^[0-9a-f]{40}$ ]] || { echo "NO_GO: missing pinned SHA" >&2; exit 42; }
[[ -d "$STAGE" && ! -L "$STAGE" ]] || { echo "NO_GO: verified staging directory absent" >&2; exit 42; }

# Cron and this installer use exactly this lock: prevent a simultaneous
# code-pull deployment while switching operational files.
exec 9>/tmp/nfcore-deploy.lock
flock -x -w 60 9 || { echo "NO_GO: deploy lock unavailable" >&2; exit 42; }

DEPLOYED="$(sed -n 's/^SHA=//p' "$ROOT/.deployed")"
CHECKOUT="$(git -C "$ROOT/src" rev-parse HEAD)"
REMOTE="$(git -C "$ROOT/src" ls-remote --exit-code origin refs/heads/production | awk 'NR==1 {print $1}')"
if [[ "$DEPLOYED" != "$EXPECTED" || "$CHECKOUT" != "$EXPECTED" || "$REMOTE" != "$EXPECTED" ]]; then
  echo "NO_GO: deployed, checkout and remote production must all match pinned SHA" >&2
  exit 42
fi
for f in deploy.sh deploy-lib.sh backup.sh; do
  [[ -f "$STAGE/$f" && ! -L "$STAGE/$f" ]] || { echo "NO_GO: staged $f unavailable" >&2; exit 42; }
  bash -n "$STAGE/$f"
done
grep -Fq -- '--assert-current-production' "$STAGE/deploy.sh" ||
  { echo "NO_GO: staged deploy lacks read-only schema gate" >&2; exit 42; }
if grep -Eq '[$]MG[[:space:]]+--apply|nf_restore_db|NFCORE_SCHEMA_MIGRATION_APPROVED=true|NFCORE_PRODUCTION_APPROVAL=PRODUCTION_APPROVED' "$STAGE/deploy.sh"; then
  echo "NO_GO: staged deploy may migrate or restore database" >&2
  exit 42
fi
[[ -r "$ROOT/docker-compose.yml" && -r "$ROOT/deploy.sh" && -r "$ROOT/deploy-lib.sh" ]] ||
  { echo "NO_GO: installed deployment contract incomplete" >&2; exit 42; }
[[ ! -e "$ROOT/backup.sh" ]] ||
  { echo "NO_GO: backup.sh already installed, require separate reconciliation" >&2; exit 42; }

# Validate only service image names, never display Compose's resolved .env.
old_images="$(docker compose -f "$ROOT/docker-compose.yml" config --images)"
printf '%s\n' "$old_images" | grep -Fxq 'nfcore-api:cur' ||
  { echo "NO_GO: expected legacy API tag missing" >&2; exit 42; }
printf '%s\n' "$old_images" | grep -Fxq 'nfcore-portal:cur' ||
  { echo "NO_GO: expected legacy Portal tag missing" >&2; exit 42; }
docker image inspect nfcore-api:cur nfcore-portal:cur >/dev/null
for svc in nfcore-db nfcore-api nfcore-portal; do
  [[ "$(docker inspect --format '{{.State.Running}}' "$svc")" == "true" ]] ||
    { echo "NO_GO: $svc not running" >&2; exit 42; }
done
API_IMAGE="$(docker inspect --format '{{.Image}}' nfcore-api)"
PORTAL_IMAGE="$(docker inspect --format '{{.Image}}' nfcore-portal)"

SNAP="$ROOT/.code-only-host-contract-backup-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$SNAP"
cp -p "$ROOT/deploy.sh" "$ROOT/deploy-lib.sh" "$ROOT/docker-compose.yml" "$ROOT/.deployed" "$SNAP/"
rollback() {
  trap - ERR
  echo "NO_GO: activation failed; restoring installed files" >&2
  cp -p "$SNAP/deploy.sh" "$ROOT/deploy.sh"
  cp -p "$SNAP/deploy-lib.sh" "$ROOT/deploy-lib.sh"
  cp -p "$SNAP/docker-compose.yml" "$ROOT/docker-compose.yml"
  rm -f "$ROOT/backup.sh"
  echo "NO_GO: legacy files restored; DO NOT merge production; inspect $SNAP" >&2
  exit 1
}
trap rollback ERR

# Image tags are aliases only. Do not restart or recreate running containers.
docker tag nfcore-api:cur nfcore-api:current
docker tag nfcore-portal:cur nfcore-portal:current
sed -i 's/image: nfcore-api:cur$/image: nfcore-api:current/' "$ROOT/docker-compose.yml"
sed -i 's/image: nfcore-portal:cur$/image: nfcore-portal:current/' "$ROOT/docker-compose.yml"
new_images="$(docker compose -f "$ROOT/docker-compose.yml" config --images)"
printf '%s\n' "$new_images" | grep -Fxq 'nfcore-api:current'
printf '%s\n' "$new_images" | grep -Fxq 'nfcore-portal:current'
docker compose -f "$ROOT/docker-compose.yml" config --quiet

# Atomic replacement under cron lock; leave historical daily backup cron alone.
install -m 755 "$STAGE/deploy.sh" "$ROOT/.deploy.sh.code-only.new"
install -m 644 "$STAGE/deploy-lib.sh" "$ROOT/.deploy-lib.sh.code-only.new"
install -m 755 "$STAGE/backup.sh" "$ROOT/.backup.sh.code-only.new"
mv -f "$ROOT/.deploy-lib.sh.code-only.new" "$ROOT/deploy-lib.sh"
mv -f "$ROOT/.backup.sh.code-only.new" "$ROOT/backup.sh"
mv -f "$ROOT/.deploy.sh.code-only.new" "$ROOT/deploy.sh"

bash -n "$ROOT/deploy.sh"
[[ "$(git -C "$ROOT/src" rev-parse HEAD)" == "$EXPECTED" ]]
[[ "$(sed -n 's/^SHA=//p' "$ROOT/.deployed")" == "$EXPECTED" ]]
[[ "$(docker inspect --format '{{.Image}}' nfcore-api)" == "$API_IMAGE" ]]
[[ "$(docker inspect --format '{{.Image}}' nfcore-portal)" == "$PORTAL_IMAGE" ]]
"$ROOT/deploy.sh" status
"$ROOT/deploy.sh" --check
printf 'SAFE_CONTRACT_ACTIVATED; deployed=%s; snapshot=%s; no DB migration, service restart, or application checkout\n' "$EXPECTED" "$SNAP"
trap - ERR
