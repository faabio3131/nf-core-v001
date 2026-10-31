# shellcheck shell=bash
# Funções de segurança do banco usadas pelo deploy.sh (testáveis em separado). Não executar direto.
DBC=${NFCORE_DBCONT:-nfcore-db}; DBN=${NFCORE_DBNAME:-nfcore}; DBU=${NFCORE_DBUSER:-nfcore}

# Confere sha256 de um dump. Uso: nf_verify_dump ARQUIVO.dump
nf_verify_dump(){
  local f="$1"
  [ -f "$f" ] && [ -f "$f.sha256" ] || return 1
  (cd "$(dirname "$f")" && sha256sum -c "$(basename "$f").sha256" >/dev/null 2>&1)
}

# Restaura o banco a partir de um dump verificado. Uso: nf_restore_db ARQUIVO.dump
nf_restore_db(){
  local f="$1" DBC=${NFCORE_DBCONT:-nfcore-db} DBN=${NFCORE_DBNAME:-nfcore} DBU=${NFCORE_DBUSER:-nfcore}
  nf_verify_dump "$f" || { echo "dump ou sha256 ausente/nao confere"; return 1; }
  docker exec "$DBC" psql -U "$DBU" -d "$DBN" -v ON_ERROR_STOP=1 -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" >/dev/null || return 1
  docker exec -i "$DBC" pg_restore -U "$DBU" -d "$DBN" --no-owner --no-privileges --exit-on-error < "$f" || return 1
  echo "restaurado; versao de schema: $(docker exec "$DBC" psql -U "$DBU" -d "$DBN" -Atc 'select max(version) from fm_schema_migrations')"
}
