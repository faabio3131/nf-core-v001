# NFCore — deploy automático no Contabo

Configuração versionada do deploy de produção do NFCore (servidor Contabo `vmi3692211`, pasta `/opt/fm/nfcore`).
Modelo **pull**: o servidor puxa a branch `production` a cada 5 minutos. **O merge/push em `production` é a
autorização do deploy** (decisão do Diretor, 26/10/2026). Nenhum agente entra no servidor para publicar.

> Estes arquivos são a **versão de referência** do repositório. O servidor roda a cópia instalada em
> `/opt/fm/nfcore`. Antes de instalar, compare (`diff /opt/fm/nfcore/deploy.sh deploy/contabo/deploy.sh`).
> Instalar no servidor exige ordem explícita do Diretor.

## Arquivos
| Arquivo | Função |
|---|---|
| `deploy.sh` | Detecta commit novo em `production`, faz backup, build, checa/aplica migrações, sobe e confere a saúde; falhou, volta |
| `deploy-lib.sh` | Verificação (sha256) e restauração de dump do banco |
| `backup.sh` | `pg_dump` custom + sha256, retenção de 7 dias (`OK <arquivo> itens <N>`) |
| `compose.prod.yml` | Composição de produção (`nfcore-db`, `nfcore-api`, `nfcore-portal`; redes `internal` e `proxy-net`); worker fora até a composição GSM ser aprovada |
| `.env.example` | Nomes das variáveis do `/opt/fm/nfcore/.env` (sem valores; o `.env` real nunca é versionado) |
| `install.sh` | Copia os scripts para `/opt/fm/nfcore` (com cópia `.pre-install-*`); com `--cron` liga o cron do deploy (*/5, flock) e o backup diário 03:45 |
| `test-deploy.sh` | Testa o `deploy.sh` com `docker` simulado (12 cenários); roda no CI |

## Fluxo do deploy
1. Compara `origin/production` com o SHA em `.deployed`; sem mudança, não faz nada.
2. Recusa histórico reescrito (só aceita avanço).
3. Backup do banco verificado por sha256; sem backup verificado, **aborta**.
4. Guarda as imagens atuais como `:prev` e faz o build da versão nova.
5. `migration_guard --check-policy`: bloqueia migração destrutiva (DROP/TRUNCATE/DELETE FROM, alteração de migração antiga). Bloqueou = deploy recusado, exige aprovação manual.
6. `migration_guard --apply` em transação única: falhou = banco intacto.
7. Sobe API e Portal; exige `/health/ready` (API) e Portal respondendo por até 2 min.
8. Qualquer falha: volta as imagens `:prev` e o SHA anterior; se já migrou, **restaura o banco do backup verificado**. O commit que falhou vai para `.failed-sha` e não é repetido.

Limite: gravações feitas entre o backup e uma restauração automática se perdem.

## Como publicar (agentes)
1. PR para `main`, CI verde.
2. **Somente com ordem do Diretor no chat:** promover `main` → `production` (PR ou push, conforme a regra da branch).
3. Em até 5 min o servidor implanta. Conferir `tail -n 30 /opt/fm/nfcore/deploy.log` (esperado `DEPLOY OK <sha>`).

## Comandos no servidor (`fmadmin`)
- `/opt/fm/nfcore/deploy.sh status` — SHA implantado · `--check` — o que mudaria, sem fazer.
- Deploy imediato: `flock -n /tmp/nfcore-deploy.lock /opt/fm/nfcore/deploy.sh`
- Pausar: comentar a linha do deploy no `crontab -e` (prefixo `#PAUSADO`).
- Instalar/atualizar scripts: `bash /opt/fm/nfcore/src/deploy/contabo/install.sh [--cron]`

## Fora do deploy automático
Segredos e `.env`, bootstrap do primeiro administrador (uma única vez, nunca reexecutar), Worker/GSM, hosts e certificados do Nginx Proxy Manager, DNS.
