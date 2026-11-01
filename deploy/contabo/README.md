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
| `deploy.sh` | Detecta commit novo em `production`, faz backup, build, exige schema atual sem DDL, sobe e confere a saúde; falhou, volta somente código |
| `deploy-lib.sh` | Verificação (sha256) e restauração de dump do banco |
| `backup.sh` | `pg_dump` custom + sha256, retenção de 7 dias (`OK <arquivo> itens <N>`) |
| `compose.prod.yml` | Composição de produção (`nfcore-db`, `nfcore-api`, `nfcore-portal`; redes `internal` e `proxy-net`); worker fora até a composição GSM ser aprovada |
| `.env.example` | Nomes das variáveis do `/opt/fm/nfcore/.env` (sem valores; o `.env` real nunca é versionado) |
| `install.sh` | Copia os scripts para `/opt/fm/nfcore` (com cópia `.pre-install-*`); com `--cron` liga o cron do deploy (*/5, flock) e o backup diário 03:45 |
| `test-deploy.sh` | Testa o `deploy.sh` com `docker` simulado (code-only, schema pendente, rollback, integridade); roda no CI |

## Fluxo do deploy
1. Compara `origin/production` com o SHA em `.deployed`; sem mudança, não faz nada.
2. Recusa histórico reescrito (só aceita avanço).
3. Backup do banco verificado por sha256; sem backup verificado, **aborta**.
4. Guarda as imagens atuais como `:prev` e faz o build da versão nova.
5. `migration_guard --check-policy` e `--assert-current-production` **somente leitura**: exigem versões fiscais e Cakto atuais. Se houver schema pendente, divergente ou inacessível, **bloqueia**.
6. **Nunca executa `--apply`**, DDL ou restauração do banco no fluxo automático. Migration precisa de autorização específica, backup/rollback governados e execução separada.
7. Sobe API e Portal; exige `/health/ready` (API) e Portal respondendo por até 2 min.
8. Falha depois do gate de schema: rollback **somente de imagens/commit**. Não restaura o banco produtivo. O commit que falhou vai para `.failed-sha`.

**Atenção:** o fluxo contém apenas API e Portal. Worker/GSM não está nesse compose; não declarar publicação completa por este deploy. A restauração do banco exige runbook manual com ensaio isolado, sem `DROP SCHEMA public CASCADE` automático.

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

## Worker canônico — composição opt-in (NFC-EXEC-17)

`compose.worker.opt-in.yml` é uma **candidata desativada**: não é incluída em `deploy.sh`, `compose.prod.yml`, `install.sh` ou cron. Nenhum fluxo automático habilita Worker. Teste estático e seguro: `bash deploy/contabo/test-worker-opt-in.sh` (não inicia containers).

O serviço reutiliza `Dockerfile.worker` e `kordena_fiscal.runtime.worker_main`. Só usa rede `internal` (sem porta pública), processo UID 10001, filesystem read-only, `/tmp` temporário, capabilities removidas e healthcheck canônico. A identity GSM exige bind mount **read-only** de arquivo preexistente (não cria caminho host), UID 10001 e permissão 0600; `production_gsm.py` valida projeto, identidade, vigência, tenant/unidade e bindings duráveis. Configuração do Worker fica em `/opt/fm/nfcore/.env.worker` (modelo de nomes em `worker-env.example`), nunca no repositório. O operador define `NFCORE_WORKER_IDENTITY_HOST_PATH` no ambiente Compose somente após configurar a identidade.

**Não executar o Worker até:** autorização humana específica, acesso operacional ao servidor, auditoria do `production`/DB/segredos GSM, observabilidade, E2E de escopo/outbox/retry, recovery e Go/No-Go. Em especial, `NFCORE_WORKER_GSM_MODE` e material de assinatura não podem ser simulados em produção. O overlay por si só não constitui integração produtiva nem homologação.

