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
case "$1 $2" in
  "image inspect") [ -f "$C/img-$3" ] ;;
  "compose build") touch "$C/img-nfcore-api:current" "$C/img-nfcore-portal:current" ;;
  "compose run") [ -f "$C/mig-$( [[ "$*" == *--apply* ]] && echo apply || echo policy)-fail" ] && { echo "erro simulado"; exit 1; }
                 [[ "$*" == *--apply* ]] && echo "applied=($(cat "$C/applied" 2>/dev/null))" ;;
  "compose up"|"compose stop") : ;;
esac
case "$1" in
  tag) [ -f "$C/img-$2" ] && touch "$C/img-$3" ;;
  exec)
    if [[ "$*" == *pg_dump* ]]; then head -c 4096 /dev/urandom; 
    elif [[ "$*" == *pg_restore\ -l* ]]; then cat >/dev/null; for i in $(seq 1 30); do echo "$i; item"; done
    elif [[ "$*" == *pg_restore* ]]; then cat >/dev/null; echo restaurado >> "$C/restored"
    elif [[ "$*" == *select\ max* ]]; then echo 18
    elif [[ "$*" == *psql* ]]; then :
    else [ -f "$C/unhealthy" ] && exit 1; fi ;;
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
touch "$CTL/img-nfcore-api:current" "$CTL/img-nfcore-portal:current"
newcommit(){ (cd "$T/root/src" && git checkout -q production && echo "$1" > f && git add f && git commit -q -m "$1" && git push -q origin production && git rev-parse HEAD); }
run(){ : > "$CTL/calls"; bash "$T/root/deploy.sh" "$@" > "$T/out" 2>&1; echo $?; }

rc=$(run); chk "sem mudanca: sai 0 e nao faz nada" '[ "$rc" = 0 ] && [ ! -s "$CTL/calls" ]'
V2=$(newcommit c2)
rc=$(run --check); chk "--check mostra o que mudaria e nao implanta" 'grep -q MUDARIA "$T/out" && [ "$(sed -n s/^SHA=//p "$T/root/.deployed")" = "$V1" ]'
rc=$(run); chk "deploy ok grava o SHA novo" '[ "$rc" = 0 ] && grep -q "DEPLOY OK" "$T/out" && [ "$(sed -n s/^SHA=//p "$T/root/.deployed")" = "$V2" ]'
chk "deploy ok fez backup verificado" 'grep -q "backup verificado" "$T/out"'

V3=$(newcommit c3); touch "$CTL/mig-apply-fail"
rc=$(run); chk "migracao que falha => rollback, versao antiga fica" '[ "$rc" = 1 ] && grep -q "ROLLBACK" "$T/out" && [ "$(sed -n s/^SHA=//p "$T/root/.deployed")" = "$V2" ] && [ ! -f "$CTL/restored" ]'
chk "commit que falhou e marcado" '[ "$(cat "$T/root/.failed-sha")" = "$V3" ]'
rc=$(run); chk "commit que falhou nao repete" '[ "$rc" = 0 ] && [ ! -s "$CTL/calls" ]'
rm -f "$CTL/mig-apply-fail" "$T/root/.failed-sha"

V4=$(newcommit c4); touch "$CTL/mig-policy-fail"
rc=$(run); chk "politica bloqueia migracao destrutiva => recusado, sem tocar no banco" '[ "$rc" = 1 ] && grep -q "politica de migracao bloqueou" "$T/out" && [ ! -f "$CTL/restored" ]'
rm -f "$CTL/mig-policy-fail" "$T/root/.failed-sha"

echo "'versao'" > "$CTL/applied"; touch "$CTL/unhealthy"
rc=$(run); chk "migrou mas saude falhou => restaura o banco do backup e volta" '[ "$rc" = 1 ] && [ -f "$CTL/restored" ] && grep -q "restaurando o banco" "$T/out" && [ "$(sed -n s/^SHA=//p "$T/root/.deployed")" = "$V2" ]'
rm -f "$CTL/unhealthy" "$CTL/applied" "$CTL/restored" "$T/root/.failed-sha"

rc=$(run); chk "depois de corrigido, o mesmo commit implanta" '[ "$rc" = 0 ] && [ "$(sed -n s/^SHA=//p "$T/root/.deployed")" = "$V4" ]'

(cd "$T/root/src" && git checkout -q -B production "$V1" && git push -q -f origin production)
rc=$(run); chk "historico reescrito e recusado" '[ "$rc" = 2 ] && grep -q "RECUSADO" "$T/out"'

: > "$T/bk/x.dump"; chk "dump sem sha256 nao e aceito" '! (. "$HERE/deploy-lib.sh"; nf_verify_dump "$T/bk/x.dump")'
[ "$fail" = 0 ] && echo "TODOS OS TESTES PASSARAM" || { echo "HA FALHAS"; exit 1; }
