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

## Trial público opt-in (`/v1/public/trial-plans`)

Desligado por padrão. Para habilitar, defina `NFCORE_PUBLIC_TRIAL_ALLOWED_ORIGINS` no `.env` (modelo em `.env.example`) com as origens separadas por vírgula; cada uma precisa também constar em `NFCORE_ALLOWED_ORIGINS`, e o e-mail de ativação precisa estar configurado — o runtime recusa subir (`RuntimeConfigurationError`) se qualquer pré-requisito faltar em ambiente de produção. Isso é decisão do Diretor, não automática por estar documentada aqui.

## Checklist de homologação (`tpAmb=2`) antes de produção (`tpAmb=1`)

Antes de qualquer decisão de ativar `tpAmb=1` (produção fiscal real), rodar a partir do servidor ou de um host com a mesma saída de rede:

```
PYTHONPATH=src python3 scripts/healthcheck_homologation.py --require-all-pinned-reachable
```

Confere conectividade TLS (sem assinar ou submeter nada) com os webservices de homologação já integrados e pinados no código: SEFAZ NF-e SP e SEFIN Nacional (NFS-e). **Nota Paulistana aparece como `NOT_PINNED`** — ainda não existe cliente de transporte real integrado para ela (`gateway/nfse_paulistana_envelope.py` só monta o envelope XML); o script nunca inventa ou tenta adivinhar esse endpoint. Um resultado verde aqui é pré-condição de rede, não prova de homologação fiscal, autorização de provedor ou prontidão operacional — não substitui a certificação por tenant.

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


### Identidades fiscais S2S do Bridge

Monte no serviço da API, em modo somente leitura, um arquivo de credenciais
gerenciado fora do Git e aponte `NFCORE_BRIDGE_CREDENTIALS_FILE` para o caminho
interno do container. Restrinja o acesso ao arquivo à operação autorizada e ao
processo da API. O arquivo deve conter um array JSON de registros com
`credential_id`, `caller_id`, `host_namespace`, `capabilities`, `scope_grants`
(lista de objetos com `tenant_id` e `unit_id`), `environments`
(`homologation` ou `production`), `secret_sha256`, `valid_from` e `expires_at`
(ISO 8601 com fuso) e `revoked` (booleano). Gere o Bearer com alta entropia e
entregue-o ao integrador por canal seguro. O arquivo contém apenas seu verificador
SHA-256. Cada grant deve corresponder ao binding fiscal já autorizado no NFCore.

A API lê o arquivo no arranque. Rotação e revogação exigem atualização atômica
do arquivo e reinício de todos os workers. Verifique
`bridge_workload_identity_configured` em `/runtime/profile` e valide uma consulta
autenticada de capacidades. Arquivo configurado inválido bloqueia o arranque.
Sem o caminho configurado, a API inicia com o Bridge sem credenciais.


## Cofre A1 — persistência N3 (somente com evidência de host)

**Auditoria de host 13/11/2026 (Contabo vmi3692211):** a API corrente já usa
bind RW `/var/lib/nfcore/vault` → `/var/lib/nfcore/vault`.
O auditor root-owned retornou `A1_VAULT_INFRA_GATE=PRECHECK_LOCAL_PARCIAL`:
diretório, formato da chave e permissões OK; **zero ciphertexts presentes**;
backup externo, custódia da chave e restore isolado **NÃO VERIFICADOS**.
O `compose.prod.yml` do Git foi reconciliado nesta PR e agora também
preserva explicitamente o **mesmo bind RW** no destino `/var/lib/nfcore/vault`,
com `create_host_path: false`. O `install.sh` **não** instala Compose;
o arquivo efetivo do host continua sendo a autoridade operacional e não
pode ser substituído sem diff, backup e preflight. O overlay candidato
é opcional e **não deve ser ativado no host já configurado**.
Não provisionar
`/var/lib/nfcore/a1-vault`, nem aplicar um segundo mount ao destino.
Antes de qualquer deploy, confirmar que o Compose **efetivo no host** preserva
o bind, independentemente da ausência desse mount na versão Git de
`compose.prod.yml`. Não executar `docker compose up` para validar a hipótese.

A PR #462 prepara `compose.a1-vault.opt-in.yml` e `a1-vault-ops.py` para
reutilizar o **mesmo** EncryptedA1Vault da API, com arquivos cifrados fora da
camada efêmera. Nenhum overlay é aplicado por `deploy.sh` ou `install.sh`.
Até o host ser auditado, **não habilite o overlay nem substitua containers**:
um mount novo pode ocultar certificados já armazenados na camada antiga.

Após o preflight read-only `audit-a1-vault-readonly.py` e a migração auditada
de eventuais ciphertexts existentes, provisionar diretório do host com
UID/GID 10001 e permissões 0700 (arquivos 0600), fora do checkout Git.
O operador define `NFCORE_A1_VAULT_HOST_DIR` em configuração privada e
ativa o overlay na composição **canônica**, não em uma segunda API.

Para backup externo cifrado, configurar repositório restic remoto
(`RESTIC_REPOSITORY`) e arquivo de senha próprio (`RESTIC_PASSWORD_FILE`,
0600, diferente da chave do Vault). Sob identidade host autorizada:

```sh
python3 deploy/contabo/a1-vault-ops.py backup
python3 deploy/contabo/a1-vault-ops.py restore-test
```

A rotina de restore usa somente diretório temporário isolado, confere SHA-256
dos arquivos cifrados e **nunca escreve no cofre ativo**. A chave mestra
`NFCORE_A1_VAULT_KEY_BASE64` exige custódia recuperável **separada do
repositório restic e fora da VPS**. Backup de ciphertext sem essa chave não
significa A1 recuperável. Exigir teste de recuperação de A1 com material
sintético/autorizado, sem expor PKCS#12 ou segredo.

Exemplos `nfcore-a1-backup.service.example` e
`nfcore-a1-backup.timer.example` preparam agendamento diário com
`EnvironmentFile=/etc/nfcore/a1-backup.env` privado. São opt-in:
não foram instalados, habilitados nem testados no servidor; configurar
alertas, retenção e prova de destino efetivamente offsite antes de GO.

Checklist completo e N3 aprovado:
`docs/checkpoints/NFCORE_A1_N3_OPERATIONAL_READINESS_2026-11-13.md`.
