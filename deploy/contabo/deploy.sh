#!/bin/bash
# NFCore — deploy automático no Contabo (modelo "pull"): o servidor puxa a branch `production`.
# Autorização = merge/push em `production` (decisão do Diretor). Cron */5 com flock (ver install.sh).
# Uso: deploy.sh [run] | --check | status
# Deploy de código SEM migration; schema pendente bloqueia. Falha volta à aplicação anterior.
set -uo pipefail
ROOT=${NFCORE_ROOT:-/opt/fm/nfcore}; SRC="$ROOT/src"; STATE="$ROOT/.deployed"; FAILED="$ROOT/.failed-sha"
BRANCH=${NFCORE_DEPLOY_BRANCH:-production}
MODE=${1:-run}
log(){ echo "$(date -u +%FT%TZ) $*"; }
# shellcheck source=/dev/null
. "$ROOT/deploy-lib.sh"
cd "$SRC" || exit 1

SHA=$(sed -n 's/^SHA=//p' "$STATE" 2>/dev/null || true); [ -n "$SHA" ] || SHA=$(git rev-parse HEAD)
if [ "$MODE" = "status" ]; then echo "implantado: ${SHA:0:7}"; exit 0; fi
git fetch -q origin "$BRANCH" || { log "fetch falhou"; exit 1; }
N=$(git rev-parse "origin/$BRANCH")
[ "$N" = "$SHA" ] && exit 0
# Só aceita avanço da versão implantada (recusa histórico reescrito).
git merge-base --is-ancestor "$SHA" "$N" || { log "RECUSADO: ${N:0:7} nao descende de ${SHA:0:7} (historico reescrito)"; exit 2; }
if [ "$MODE" = "--check" ]; then echo "MUDARIA: ${SHA:0:7} -> ${N:0:7}"; exit 0; fi
# Não repete um deploy que já falhou para este mesmo commit.
[ "$(cat "$FAILED" 2>/dev/null)" = "$N" ] && exit 0

# Deploys automáticos são code-only; migration exige procedimento separado e aprovado.

cd "$ROOT" || exit 1
log "== DEPLOY inicio ${SHA:0:7}->${N:0:7}"
log "backup do banco"
BKOUT=$("$ROOT/backup.sh") || { log "FALHA no backup, abortando"; exit 3; }
BKFILE=$(echo "$BKOUT" | sed -n 's/^OK \([^ ]*\) itens.*/\1/p')
nf_verify_dump "$BKFILE" || { log "backup nao verificado, abortando"; exit 3; }
log "backup verificado: $BKFILE"

rollback(){
  log "ROLLBACK: $1"
  echo "$N" > "$FAILED"
  # Não houve mudança de schema: rollback apenas dos containers/commit.
  for s in api portal; do docker image inspect "nfcore-$s:prev" >/dev/null 2>&1 && docker tag "nfcore-$s:prev" "nfcore-$s:current"; done
  (cd "$SRC" && git checkout -q "$SHA")
  docker compose up -d --no-build nfcore-api nfcore-portal 2>&1 | tail -n 3
  log "== DEPLOY FALHOU; versao anterior ${SHA:0:7} restaurada"
  exit 1
}

# Guarda as imagens atuais como :prev para o rollback.
for s in api portal; do docker image inspect "nfcore-$s:current" >/dev/null 2>&1 && docker tag "nfcore-$s:current" "nfcore-$s:prev"; done
(cd "$SRC" && git checkout -q "$N") || rollback "checkout falhou"
log "build"; docker compose build 2>&1 | tail -n 3 || rollback "docker compose build failed"
for s in api portal; do docker image inspect "nfcore-$s:current" >/dev/null 2>&1 || rollback "build de $s nao gerou imagem"; done

MG="docker compose run --rm --no-deps -T nfcore-api python scripts/ci/migration_guard.py"
log "schema: checando politica (somente leitura)"
$MG --check-policy < /dev/null > /tmp/nfcore-mig.log 2>&1 || rollback "politica de migration bloqueou release"
log "schema: exigindo versoes atuais sem aplicar migrations"
$MG --assert-current-production < /dev/null >> /tmp/nfcore-mig.log 2>&1 || rollback "schema pendente/divergente; migration exige fluxo humano separado"

log "subindo"; docker compose up -d nfcore-api nfcore-portal 2>&1 | tail -n 3 || rollback "docker compose up failed"
ok=0
for _ in $(seq 1 "${NFCORE_HEALTH_TRIES:-24}"); do
  sleep "${NFCORE_HEALTH_WAIT:-5}"
  if docker exec nfcore-api python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/health/ready', timeout=3).read()" >/dev/null 2>&1 \
     && docker exec nfcore-portal python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8081/', timeout=3).read()" >/dev/null 2>&1; then ok=1; break; fi
done
[ "$ok" = 1 ] || rollback "saude nao confirmou em 2 min"
echo "SHA=$N" > "$STATE"; rm -f "$FAILED"
log "== DEPLOY OK ${N:0:7}"
