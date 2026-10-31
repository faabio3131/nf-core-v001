#!/bin/bash
# Backup lógico do banco do NFCore (pg_dump formato custom) + sha256. Saída final: "OK <arquivo> itens <N>".
# Retenção: 7 dias. Cron diário 03:45 e antes de cada deploy (chamado pelo deploy.sh).
set -eu
DEST=${NFCORE_BACKUP_DIR:-/opt/fm/backups/nfcore-diario}
DBC=${NFCORE_DBCONT:-nfcore-db}; DBN=${NFCORE_DBNAME:-nfcore}; DBU=${NFCORE_DBUSER:-nfcore}
umask 077; mkdir -p "$DEST"
F="$DEST/nfcore-$(date +%Y%m%d-%H%M%S).dump"
docker exec "$DBC" pg_dump -U "$DBU" -d "$DBN" --format=custom --no-owner --no-acl > "$F"
ITENS=$(docker exec -i "$DBC" pg_restore -l < "$F" | grep -vc '^;' || true)
[ "${ITENS:-0}" -gt 20 ] || { echo "ERRO: dump suspeito ($ITENS itens)"; rm -f "$F"; exit 1; }
(cd "$DEST" && sha256sum "$(basename "$F")" > "$(basename "$F").sha256")
find "$DEST" -name 'nfcore-*.dump*' -mtime +7 -delete
echo "OK $F itens $ITENS"
