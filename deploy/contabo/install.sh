#!/bin/bash
# Instala/atualiza os scripts de deploy do NFCore no servidor. NÃO roda sozinho: o Diretor autoriza no chat.
# Uso (no servidor, como fmadmin):  bash /opt/fm/nfcore/src/deploy/contabo/install.sh [--cron]
# - copia deploy.sh, deploy-lib.sh e backup.sh para /opt/fm/nfcore (guarda cópia .pre-install-*)
# - NÃO mexe no .env, no banco nem nos containers
# - com --cron, instala o cron */5 do deploy (idempotente) e o backup diário 03:45
set -eu
ROOT=${NFCORE_ROOT:-/opt/fm/nfcore}; HERE=$(cd "$(dirname "$0")" && pwd); TS=$(date +%Y%m%d-%H%M%S)
for f in deploy.sh deploy-lib.sh backup.sh; do
  bash -n "$HERE/$f"
  [ -f "$ROOT/$f" ] && cp -p "$ROOT/$f" "$ROOT/$f.pre-install-$TS"
  install -m 755 "$HERE/$f" "$ROOT/$f"
done
echo "scripts instalados em $ROOT (copias anteriores: *.pre-install-$TS)"
if [ "${1:-}" = "--cron" ]; then
  DL='*/5 * * * * flock -n /tmp/nfcore-deploy.lock /opt/fm/nfcore/deploy.sh >> /opt/fm/nfcore/deploy.log 2>&1'
  BL='45 3 * * * /opt/fm/nfcore/backup.sh >> /opt/fm/nfcore/backup.log 2>&1'
  crontab -l > "/tmp/crontab.pre-nfcore-$TS" 2>/dev/null || true
  for L in "$DL" "$BL"; do
    key=$(echo "$L" | grep -o 'nfcore/[a-z-]*\.sh')
    crontab -l 2>/dev/null | grep -q "$key" || { (crontab -l 2>/dev/null; echo "$L") | crontab -; echo "cron adicionado: $key"; }
  done
fi
"$ROOT/deploy.sh" --check || true
