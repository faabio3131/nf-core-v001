#!/usr/bin/env bash
# Teste controlado: restaura o backup em PostgreSQL descartavel e sem rede.
# O unico acesso ao banco de producao e uma consulta SELECT de contagem de tabelas.
set -euo pipefail

DIR="${NFCORE_BACKUP_DIR:-/opt/fm/backups/nfcore-diario}"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/nfcore-restore-test.XXXXXXXX")"
CIDFILE="$TMP/container-id"
T="nfcore-restore-test-$(date -u +%Y%m%d%H%M%S)-$$-$RANDOM"

cleanup() {
  if [[ -s "$CIDFILE" ]]; then
    docker rm -fv "$(cat "$CIDFILE")" >/dev/null 2>&1 || true
  fi
  rm -f -- "$CIDFILE"
  rmdir -- "$TMP" >/dev/null 2>&1 || true
}
trap cleanup EXIT

shopt -s nullglob
dumps=("$DIR"/nfcore-*.dump)
if (( ${#dumps[@]} == 0 )); then
  echo "RESTORE_TEST_FALHOU: nenhum backup encontrado" >&2
  exit 1
fi
D="$(ls -t -- "${dumps[@]}" | head -n 1)"
echo "dump: $D"
(cd "$DIR" && sha256sum -c "$(basename "$D").sha256")

# Nao remove conteineres anteriores nem baixa imagens; limita o consumo.
# --cidfile permite remover exclusivamente o conteiner criado nesta execucao.
docker run -d --cidfile "$CIDFILE" --name "$T" --network none \
  --pull=never --memory 512m --cpus 1 --pids-limit 128 \
  -e POSTGRES_PASSWORD=restore-test -e POSTGRES_DB=nfcore \
  postgres:16-alpine >/dev/null

for ((attempt=1; attempt<=30; attempt++)); do
  docker exec "$T" pg_isready -U postgres -d nfcore >/dev/null 2>&1 && break
  sleep 2
done
docker exec "$T" pg_isready -U postgres -d nfcore >/dev/null
docker cp "$D" "$T":/tmp/restore.dump
docker exec "$T" pg_restore -U postgres -d nfcore --no-owner --no-acl --exit-on-error /tmp/restore.dump

Q="select count(*) from information_schema.tables where table_schema='public'"
R="$(docker exec "$T" psql -U postgres -d nfcore -Atc "$Q")"
P="$(docker exec nfcore-db psql -U nfcore -d nfcore -Atc "$Q")"
echo "tabelas restauradas=$R producao=$P"
if [[ "$R" =~ ^[0-9]+$ && "$P" =~ ^[0-9]+$ ]] && (( R > 0 )) && [[ "$R" == "$P" ]]; then
  echo "RESTORE_TEST_OK"
else
  echo "RESTORE_TEST_FALHOU" >&2
  exit 1
fi
