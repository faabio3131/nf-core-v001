#!/bin/bash
# NFCore — same Contabo code-only deploy authority. Never migrate or restore DB.
# Cron runs API/Portal only when no production Worker exists.
# Existing production Workers require a separately authorized coordinated release,
# using the effective host Compose; never activate a missing or stopped Worker.
set -uo pipefail
ROOT=${NFCORE_ROOT:-/opt/fm/nfcore}; SRC="$ROOT/src"; STATE="$ROOT/.deployed"; FAILED="$ROOT/.failed-sha"
BRANCH=${NFCORE_DEPLOY_BRANCH:-production}
MODE=${1:-run}
log(){ echo "$(date -u +%FT%TZ) $*"; }
blocked(){ log "NO_GO: $*"; exit 42; }
case "$MODE" in run|--check|status|--coordinated) ;; *) blocked "invalid deploy mode";; esac
# Maintenance window: an operator-created freeze file stops the cron auto-deploy
# (mode run) without touching anything. Read-only modes and the explicitly
# approved --coordinated release used inside the window keep working.
FREEZE=${NFCORE_DEPLOY_FREEZE_FILE:-$ROOT/.deploy-freeze}
if [ "$MODE" = run ] && [ -e "$FREEZE" ]; then
  log "FROZEN: deploy automatico suspenso pela janela de manutencao ($FREEZE)"; exit 0
fi
# Never run two mutating deploys at once (5-minute cron vs. a slow build).
if [ "$MODE" = run ] || [ "$MODE" = --coordinated ]; then
  exec 9>"${NFCORE_DEPLOY_LOCK_FILE:-$ROOT/.deploy.lock}" || blocked "deploy lock unavailable"
  if ! flock -n 9; then
    [ "$MODE" = run ] && { log "SKIP: outro deploy em andamento"; exit 0; }
    blocked "another deploy holds the lock"
  fi
fi
# shellcheck source=/dev/null
. "$ROOT/deploy-lib.sh"
cd "$SRC" || exit 1

SHA=$(sed -n 's/^SHA=//p' "$STATE" 2>/dev/null || true)
[[ "$SHA" =~ ^[a-f0-9]{40}$ ]] || blocked "missing or invalid deployed SHA"
if [ "$MODE" = "status" ]; then echo "implantado: ${SHA:0:7}"; exit 0; fi
git fetch -q origin "$BRANCH" || { log "fetch falhou"; exit 1; }
N=$(git rev-parse "origin/$BRANCH") || blocked "remote commit unavailable"
[[ "$N" =~ ^[a-f0-9]{40}$ ]] || blocked "invalid target SHA"
[ "$N" = "$SHA" ] && exit 0
git merge-base --is-ancestor "$SHA" "$N" || { log "RECUSADO: ${N:0:7} nao descende de ${SHA:0:7} (historico reescrito)"; exit 2; }
if [ "$MODE" = "--check" ]; then echo "MUDARIA: ${SHA:0:7} -> ${N:0:7}"; exit 0; fi
[ "$(cat "$FAILED" 2>/dev/null)" = "$N" ] && exit 0
[ "$(git rev-parse HEAD)" = "$SHA" ] || blocked "checkout differs from deployed SHA"
[ -z "$(git status --porcelain)" ] || blocked "checkout has local changes"

cd "$ROOT" || exit 1
services=(nfcore-api nfcore-portal)
workers=()
names=$(docker ps -a --format '{{.Names}}') || blocked "Docker inventory unavailable"
running=$(docker ps --format '{{.Names}}') || blocked "Docker running inventory unavailable"
if grep -Fxq nfcore-worker <<<"$names"; then
  grep -Fxq nfcore-worker <<<"$running" || blocked "production Worker is stopped; never auto-activate"
  workers+=(nfcore-worker)
fi
while IFS= read -r name; do
  case "$name" in
    nfcore-worker) ;;
    nfcore-*worker*) blocked "unexpected running NFCore consumer; scoped review required";;
  esac
done <<<"$running"
if (( ${#workers[@]} > 0 )); then
  [[ "$MODE" == --coordinated && "${NFCORE_COORDINATED_DEPLOY_APPROVED_SHA:-}" == "$N" ]] ||
    blocked "existing Worker requires separately approved coordinated deployment"
  services+=("${workers[@]}")
elif [[ "$MODE" == --coordinated ]]; then
  blocked "coordinated deployment cannot activate an absent Worker"
fi
if [[ "$MODE" == --coordinated && "$BRANCH" != production ]]; then
  blocked "coordinated release must target production"
fi

# Keep the installed effective Compose as authority. Do not generate a parallel
# service, overlay credentials, or print resolved environment values.
declare -A tags previous candidate
tags[nfcore-api]=nfcore-api:current
tags[nfcore-portal]=nfcore-portal:current
tags[nfcore-worker]=nfcore-worker:controlled
configured=$(docker compose config --services 2>/dev/null) || blocked "effective Compose unavailable"
config_check='import json, sys
from pathlib import Path

config = json.load(sys.stdin)
source = Path(sys.argv[1]).resolve()
if config.get("name") != "nfcore":
    raise SystemExit(42)
for spec in sys.argv[2:]:
    name, tag = spec.split("=", 1)
    service = config["services"][name]
    build = service.get("build") or {}
    expected = {
        "nfcore-api": "Dockerfile.api",
        "nfcore-portal": "Dockerfile.portal",
        "nfcore-worker": "Dockerfile.worker",
    }[name]
    if (service.get("container_name") != name or service.get("image") != tag
            or Path(build.get("context", "")).resolve() != source
            or (source / build.get("dockerfile", "")).resolve() != source / expected):
        raise SystemExit(42)
'
specs=()
for svc in "${services[@]}"; do
  grep -Fxq "$svc" <<<"$configured" || blocked "selected service missing in effective Compose: $svc"
  specs+=("$svc=${tags[$svc]}")
done
docker compose config --format json 2>/dev/null | python3 -c "$config_check" "$SRC" "${specs[@]}" 2>/dev/null ||
  blocked "effective Compose project, service or image contract mismatch"
for svc in "${services[@]}"; do
  [[ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}/{{index .Config.Labels "com.docker.compose.service"}}' "$svc")" == "nfcore/$svc" ]] ||
    blocked "container ownership mismatch: $svc"
  [[ "$(docker inspect -f '{{.State.Running}}' "$svc")" == true &&
     "$(docker inspect -f '{{.State.Health.Status}}' "$svc")" == healthy ]] ||
    blocked "baseline service not healthy: $svc"
  live_hash=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.config-hash"}}' "$svc") ||
    blocked "running Compose config hash unavailable"
  configured_hash=$(docker compose config --hash "$svc" 2>/dev/null | awk -v svc="$svc" '$1 == svc { print $2 }') ||
    blocked "effective Compose config hash unavailable"
  [[ "$live_hash" =~ ^[a-f0-9]{64}$ && "$configured_hash" == "$live_hash" ]] ||
    blocked "effective Compose differs from running container: $svc"
  previous[$svc]=$(docker inspect -f '{{.Image}}' "$svc") || blocked "running digest unavailable: $svc"
  [[ "${previous[$svc]}" =~ ^sha256:[a-f0-9]{64}$ ]] || blocked "invalid baseline digest"
  [[ "$(docker image inspect -f '{{.Id}}' "${tags[$svc]}")" == "${previous[$svc]}" ]] ||
    blocked "running image and canonical tag differ: $svc"
done

# Code-only rollback MUST be compatible with the currently installed schema.
# A v21->v23 cutover is a separate governed operation, never this cron.
MG=(docker compose run --rm --no-deps --pull never -T nfcore-api python scripts/ci/migration_guard.py)
umask 077
MIGLOG=$(mktemp "$ROOT/.nfcore-migration-check.XXXXXXXX") || blocked "cannot create private migration log"
trap 'rm -f -- "$MIGLOG"' EXIT
"${MG[@]}" --assert-current-production < /dev/null > "$MIGLOG" 2>&1 ||
  blocked "running release is incompatible with schema; use governed cutover"

log "== DEPLOY inicio ${SHA:0:7}->${N:0:7}"
log "backup do banco"
BKOUT=$("$ROOT/backup.sh") || { log "FALHA no backup, abortando"; exit 3; }
BKFILE=$(echo "$BKOUT" | sed -n 's/^OK \([^ ]*\) itens.*/\1/p')
nf_verify_dump "$BKFILE" || { log "backup nao verificado, abortando"; exit 3; }
log "backup verificado: $BKFILE"

ready(){
  local expected="$1" svc id expected_id
  for _ in $(seq 1 "${NFCORE_HEALTH_TRIES:-24}"); do
    local all_ok=true
    for svc in "${services[@]}"; do
      if [ "$expected" = previous ]; then expected_id="${previous[$svc]}"; else expected_id="${candidate[$svc]}"; fi
      id=$(docker inspect -f '{{.Image}}' "$svc" 2>/dev/null) || all_ok=false
      [[ "$id" == "$expected_id" &&
         "$(docker inspect -f '{{.State.Running}}' "$svc" 2>/dev/null)" == true &&
         "$(docker inspect -f '{{.State.Health.Status}}' "$svc" 2>/dev/null)" == healthy ]] || all_ok=false
    done
    if [[ "$all_ok" == true ]] &&
       docker exec nfcore-api python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/health/ready', timeout=3).read()" >/dev/null 2>&1 &&
       docker exec nfcore-portal python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8081/', timeout=3).read()" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${NFCORE_HEALTH_WAIT:-5}"
  done
  return 1
}

services_changed=false
rollback(){
  log "ROLLBACK: $1"
  echo "$N" > "$FAILED" || log "NO_GO: failed marker write failed"
  local recovered=true svc
  for svc in "${services[@]}"; do
    docker tag "${previous[$svc]}" "${tags[$svc]}" || recovered=false
  done
  (cd "$SRC" && git checkout -q "$SHA") || recovered=false
  if [[ "$services_changed" == true && "$recovered" == true ]]; then
    docker compose up -d --no-deps --no-build --pull never --force-recreate "${services[@]}" >/dev/null 2>&1 || recovered=false
  fi
  if [[ "$recovered" == true ]] && ready previous; then
    log "== DEPLOY FALHOU; versao anterior ${SHA:0:7} restaurada e verificada"
  else
    log "NO_GO_ROLLBACK_UNVERIFIED; intervencao operacional obrigatoria; sem restore de banco"
  fi
  exit 1
}

# Snapshot actual running digests; preserve exact image IDs for recovery.
for svc in "${services[@]}"; do
  docker tag "${previous[$svc]}" "$svc:prev" || blocked "cannot preserve baseline image: $svc"
done
(cd "$SRC" && git checkout -q "$N") || rollback "checkout falhou"
log "build"
docker compose build --build-arg "NFCORE_RELEASE_SHA=$N" "${services[@]}" 2>&1 | tail -n 3 || rollback "docker compose build failed"
for svc in "${services[@]}"; do
  candidate[$svc]=$(docker image inspect -f '{{.Id}}' "${tags[$svc]}") ||
    rollback "build de $svc nao gerou imagem"
  [[ "${candidate[$svc]}" =~ ^sha256:[a-f0-9]{64}$ ]] ||
    rollback "invalid candidate digest: $svc"
  [[ "$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "${tags[$svc]}")" == "$N" ]] ||
    rollback "candidate SHA label mismatch: $svc"
done

log "schema: checando politica (somente leitura)"
"${MG[@]}" --check-policy < /dev/null > "$MIGLOG" 2>&1 || rollback "politica de migration bloqueou release"
log "schema: exigindo versoes atuais sem aplicar migrations"
"${MG[@]}" --assert-current-production < /dev/null >> "$MIGLOG" 2>&1 || rollback "schema pendente/divergente; migration exige fluxo humano separado"

# No implicit starts of unknown or disabled services; graceful stop of only
# already-running, approved workers. An unsuccessful stop triggers recovery.
services_changed=true
if (( ${#workers[@]} > 0 )); then
  docker compose stop "${workers[@]}" >/dev/null 2>&1 || rollback "worker stop failed"
fi
log "subindo"
docker compose up -d --no-deps --no-build --pull never --force-recreate "${services[@]}" 2>&1 | tail -n 3 ||
  rollback "docker compose up failed"
ready candidate || rollback "saude ou digests nao confirmaram"
# Publish a marker only after every selected runtime actually matches.
marker=$(mktemp "$ROOT/.deployed.new.XXXXXXXX") || rollback "marker staging failed"
if ! printf 'SHA=%s\n' "$N" > "$marker" || ! mv -f "$marker" "$STATE"; then
  rm -f -- "$marker"; rollback "marker persistence failed"
fi
rm -f "$FAILED"
log "== DEPLOY OK ${N:0:7}"
