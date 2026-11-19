#!/bin/bash
# Teste do deploy.sh com `docker` simulado (nenhum container real). Rodar: bash deploy/contabo/test-deploy.sh
# shellcheck disable=SC2034
set -u
HERE=$(cd "$(dirname "$0")" && pwd); T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fail=0; ok(){ echo "OK   $1"; }; ko(){ echo "FALHA $1"; fail=1; }
chk(){ if eval "$2"; then ok "$1"; else ko "$1"; fi; }

# --- docker falso: comportamento controlado por arquivos em $T/ctl ---
mkdir -p "$T/bin" "$T/ctl" "$T/root" "$T/bk"
cat > "$T/bin/docker" <<'D'
#!/bin/bash
C="$CTL"; echo "docker $*" >> "$C/calls"
id_for(){ printf 'sha256:%064d' "$1"; }
image_id(){
  local file="$C/img-$1"
  if [[ "$1" == sha256:* ]]; then printf '%s\n' "$1"; return; fi
  [ -f "$file" ] || return 1
  cat "$file"
}
tag_for(){ case "$1" in nfcore-api|nfcore-portal) echo "$1:current";; *) echo "$1:controlled";; esac; }
container_id(){ cat "$C/running-$1"; }
case "$1 $2" in
  "ps -a"|"ps --format")
    printf '%s\n' nfcore-db nfcore-api nfcore-portal
    if [ -f "$C/worker-present" ] && { [ "$2" = -a ] || [ ! -f "$C/worker-stopped" ]; }; then echo nfcore-worker; fi
    if [ -f "$C/unknown-worker" ]; then echo nfcore-unknown-worker; fi
    exit 0;;
  "image inspect")
    if [ "$3" = -f ]; then
      case "$4" in
        *org.opencontainers.image.revision*) cat "$C/sha-$5";;
        *) image_id "$5";;
      esac
    else image_id "$3" >/dev/null; fi
    exit $?;;
  "inspect -f")
    case "$3" in
      *com.docker.compose.project*) echo "nfcore/$4";;
      *com.docker.compose.config-hash*) printf '%064d\n' 42;;
      *State.Running*) echo true;;
      *State.Health.Status*) echo healthy;;
      *'.Image'*) container_id "$4";;
      *) exit 1;;
    esac
    exit $?;;
  "compose config")
    if [ "$3" = --services ]; then
      printf '%s\n' nfcore-api nfcore-portal
      [ -f "$C/worker-configured" ] && echo nfcore-worker
    elif [ "$3" = --hash ]; then
      if [ -f "$C/config-drift" ]; then printf '%s %064d\n' "$4" 43
      else printf '%s %064d\n' "$4" 42; fi
    elif [ "$3" = --format ]; then
      python3 - "$NFCORE_ROOT/src" "$C/worker-configured" "$C/wrong-context" <<'PY'
import json, pathlib, sys
context = sys.argv[1]
if pathlib.Path(sys.argv[3]).exists():
    context = "/tmp/other-src"
services = {}
for suffix, tag in (("api", "current"), ("portal", "current"), ("worker", "controlled")):
    if suffix == "worker" and not pathlib.Path(sys.argv[2]).exists():
        continue
    name = "nfcore-" + suffix
    services[name] = {
        "container_name": name,
        "image": name + ":" + tag,
        "build": {"context": context, "dockerfile": "Dockerfile." + suffix},
    }
print(json.dumps({"name": "nfcore", "services": services}))
PY
    else exit 1; fi
    exit 0;;
  "compose build")
    [ -f "$C/build-fail" ] && { echo "simulated build error"; exit 65; }
    sha=""
    for arg in "$@"; do
      case "$arg" in
        NFCORE_RELEASE_SHA=*) sha="${arg#*=}";;
        nfcore-api|nfcore-portal|nfcore-worker|nfcore-bling-worker)
          tag=$(tag_for "$arg")
          seqno=$(cat "$C/sequence"); seqno=$((seqno+1)); echo "$seqno" > "$C/sequence"
          id_for "$seqno" > "$C/img-$tag"
          printf '%s\n' "$sha" > "$C/sha-$tag";;
      esac
    done
    exit 0;;
  "compose run")
     if [[ "$*" == *--assert-current-production* && -f "$C/schema-pending" ]]; then
       # The first is the old image preflight; fail only after build has run.
       if grep -q 'docker compose build' "$C/calls"; then echo "schema pending"; exit 1; fi
     fi
     if [[ "$*" == *--check-policy* && -f "$C/mig-policy-fail" ]]; then echo "policy denied"; exit 1; fi
     [[ "$*" == *--apply* ]] && { echo "UNSAFE APPLY"; exit 91; }
     exit 0;;
  "compose up")
    if [ -f "$C/up-fail" ]; then rm -f "$C/up-fail"; echo "simulated up failure"; exit 71; fi
    if [ -f "$C/rollback-fail" ] && [ "$(grep -c 'docker compose up' "$C/calls")" -gt 1 ]; then exit 71; fi
    for arg in "$@"; do
      case "$arg" in nfcore-api|nfcore-portal|nfcore-worker|nfcore-bling-worker)
        image_id "$(tag_for "$arg")" > "$C/running-$arg";;
      esac
    done
    exit 0;;
  "compose stop") exit 0;;
esac
case "$1" in
  tag) image_id "$2" > "$C/img-$3" || exit 1;;
  exec)
    if [[ "$*" == *pg_dump* ]]; then head -c 4096 /dev/urandom;
    elif [[ "$*" == *pg_restore\ -l* ]]; then cat >/dev/null; for i in $(seq 1 30); do echo "$i; item"; done
    elif [[ "$*" == *pg_restore* ]]; then cat >/dev/null; echo restaurado >> "$C/restored"
    elif [[ "$*" == *select\ max* ]]; then echo 18
    elif [[ "$*" == *psql* ]]; then :;
    else [ -f "$C/unhealthy" ] && exit 1; fi;;
  *) exit 1;;
esac
exit 0
D
chmod +x "$T/bin/docker"
export NFCORE_HEALTH_TRIES=2 NFCORE_HEALTH_WAIT=0 PATH="$T/bin:$PATH" CTL="$T/ctl" NFCORE_ROOT="$T/root" NFCORE_BACKUP_DIR="$T/bk"
cp "$HERE"/deploy.sh "$HERE"/deploy-lib.sh "$HERE"/backup.sh "$T/root/"

# --- repositório de origem com branch production ---
git init -q --bare "$T/origin.git"
git clone -q "$T/origin.git" "$T/root/src" 2>/dev/null; cd "$T/root/src" || exit 1
git config user.email t@t; git config user.name t; git checkout -q -b production
echo 1 > f; git add f; git commit -q -m c1; git push -q origin production
V1=$(git rev-parse HEAD); echo "SHA=$V1" > "$T/root/.deployed"
printf 'sha256:%064d\n' 1 > "$CTL/img-nfcore-api:current"
printf 'sha256:%064d\n' 2 > "$CTL/img-nfcore-portal:current"
cp "$CTL/img-nfcore-api:current" "$CTL/running-nfcore-api"
cp "$CTL/img-nfcore-portal:current" "$CTL/running-nfcore-portal"
echo 10 > "$CTL/sequence"
newcommit(){ (cd "$T/root/src" && git checkout -q production && echo "$1" > f && git add f && git commit -q -m "$1" && git push -q origin production && git rev-parse HEAD && git checkout -q "$(sed -n s/^SHA=//p "$T/root/.deployed")"); }
run(){ : > "$CTL/calls"; bash "$T/root/deploy.sh" "$@" > "$T/out" 2>&1; echo $?; }

rc=$(run); chk "sem mudanca: sai 0 e nao faz nada" '[ "$rc" = 0 ] && [ ! -s "$CTL/calls" ]'
V2=$(newcommit c2)
# Sem qualquer autorização de migration, o deploy code-only deve funcionar com schema atual.
unset NFCORE_SCHEMA_MIGRATION_APPROVED NFCORE_PRODUCTION_APPROVAL
rc=$(run --check); chk "--check mostra o que mudaria e nao implanta" 'grep -q MUDARIA "$T/out" && [ "$(sed -n s/^SHA=//p "$T/root/.deployed")" = "$V1" ]'
rc=$(run); chk "deploy ok grava o SHA novo" '[ "$rc" = 0 ] && grep -q "DEPLOY OK" "$T/out" && [ "$(sed -n s/^SHA=//p "$T/root/.deployed")" = "$V2" ]'
chk "deploy ok fez backup verificado" 'grep -q "backup verificado" "$T/out"'
chk "deploy valida schema sem DDL" 'grep -q -- "--assert-current-production" "$CTL/calls" && ! grep -q -- "--apply" "$CTL/calls"'

V3=$(newcommit c3); touch "$CTL/schema-pending"
rc=$(run); chk "schema pendente => rollback sem migration, revisao antiga fica" '[ "$rc" = 1 ] && grep -q "schema pendente/divergente" "$T/out" && [ "$(sed -n s/^SHA=//p "$T/root/.deployed")" = "$V2" ] && [ ! -f "$CTL/restored" ] && ! grep -q -- "--apply" "$CTL/calls"'
chk "commit que falhou e marcado" '[ "$(cat "$T/root/.failed-sha")" = "$V3" ]'
rc=$(run); chk "commit que falhou nao repete" '[ "$rc" = 0 ] && [ ! -s "$CTL/calls" ]'
rm -f "$CTL/schema-pending" "$T/root/.failed-sha"

V4=$(newcommit c4); touch "$CTL/mig-policy-fail"
rc=$(run); chk "politica bloqueia migracao destrutiva => recusado, sem tocar no banco" '[ "$rc" = 1 ] && grep -q "politica de migration bloqueou" "$T/out" && [ ! -f "$CTL/restored" ]'
rm -f "$CTL/mig-policy-fail" "$T/root/.failed-sha"

touch "$CTL/build-fail"
rc=$(run); chk "docker build que falha bloqueia deploy mesmo com tag antiga presente" '[ "$rc" = 1 ] && grep -q "docker compose build failed" "$T/out" && [ "$(sed -n s/^SHA=//p "$T/root/.deployed")" = "$V2" ] && ! grep -q -- "--apply" "$CTL/calls"'
rm -f "$CTL/build-fail" "$T/root/.failed-sha"

touch "$CTL/up-fail"
rc=$(run); chk "docker compose up falhou => rollback do codigo" '[ "$rc" = 1 ] && grep -q "docker compose up failed" "$T/out" && [ "$(sed -n s/^SHA=//p "$T/root/.deployed")" = "$V2" ] && [ ! -f "$CTL/restored" ]'
rm -f "$T/root/.failed-sha"

touch "$CTL/unhealthy"
rc=$(run); chk "health falhou => rollback somente codigo, sem restore de banco" '[ "$rc" = 1 ] && [ ! -f "$CTL/restored" ] && grep -q "NO_GO_ROLLBACK_UNVERIFIED" "$T/out" && [ "$(sed -n s/^SHA=//p "$T/root/.deployed")" = "$V2" ]'
rm -f "$CTL/unhealthy" "$CTL/restored" "$T/root/.failed-sha"

rc=$(run); chk "depois de corrigido, o mesmo commit implanta" '[ "$rc" = 0 ] && [ "$(sed -n s/^SHA=//p "$T/root/.deployed")" = "$V4" ]'

# Production Worker is already active; cron MUST NOT deploy API/Portal alone.
V5=$(newcommit c5)
touch "$CTL/worker-present" "$CTL/worker-configured"
printf 'sha256:%064d\n' 3 > "$CTL/img-nfcore-worker:controlled"
cp "$CTL/img-nfcore-worker:controlled" "$CTL/running-nfcore-worker"
rc=$(run); chk "cron recusa release parcial com Worker existente" '[ "$rc" = 42 ] && grep -q "coordinated deployment" "$T/out" && ! grep -q "compose build" "$CTL/calls"'
touch "$CTL/worker-stopped"
export NFCORE_COORDINATED_DEPLOY_APPROVED_SHA="$V5"
rc=$(run --coordinated); chk "nao reativa Worker parado" '[ "$rc" = 42 ] && ! grep -q "compose up" "$CTL/calls"'
rm "$CTL/worker-stopped" "$CTL/worker-configured"
rc=$(run --coordinated); chk "nao implanta Worker fora do compose efetivo" '[ "$rc" = 42 ] && ! grep -q "compose build" "$CTL/calls"'
touch "$CTL/worker-configured" "$CTL/unknown-worker"
rc=$(run --coordinated); chk "consumidor desconhecido ativo bloqueia" '[ "$rc" = 42 ] && ! grep -q "compose build" "$CTL/calls"'
rm "$CTL/unknown-worker"
touch "$CTL/config-drift"
rc=$(run --coordinated); chk "deriva de Compose bloqueia antes de build" '[ "$rc" = 42 ] && ! grep -q "compose build" "$CTL/calls"'
rm "$CTL/config-drift"
touch "$CTL/wrong-context"
rc=$(run --coordinated); chk "contexto de build nao canonico bloqueia" '[ "$rc" = 42 ] && ! grep -q "compose build" "$CTL/calls"'
rm "$CTL/wrong-context"
rc=$(run --coordinated); chk "release coordenada atualiza Worker e marca SHA somente apos digests/health" '[ "$rc" = 0 ] && grep -q "compose stop nfcore-worker" "$CTL/calls" && grep -q "compose up .*nfcore-worker" "$CTL/calls" && [ "$(sed -n s/^SHA=//p "$T/root/.deployed")" = "$V5" ] && cmp -s "$CTL/img-nfcore-worker:controlled" "$CTL/running-nfcore-worker"'
unset NFCORE_COORDINATED_DEPLOY_APPROVED_SHA
(cd "$T/root/src" && git checkout -q -B production "$V1" && git push -q -f origin production)
rc=$(run); chk "historico reescrito e recusado" '[ "$rc" = 2 ] && grep -q "RECUSADO" "$T/out"'

: > "$T/bk/x.dump"; chk "restore em banco nao descartavel e negado" '! (. "$HERE/deploy-lib.sh"; NFCORE_RESTORE_DISPOSABLE_DB=true nf_restore_db "$T/bk/x.dump")'
: > "$T/bk/x.dump"; chk "dump sem sha256 nao e aceito" '! (. "$HERE/deploy-lib.sh"; nf_verify_dump "$T/bk/x.dump")'
[ "$fail" = 0 ] && echo "TODOS OS TESTES PASSARAM" || { echo "HA FALHAS"; exit 1; }
