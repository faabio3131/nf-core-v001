# NFCore — migração segura dos workers à Contabo (trilha exclusiva de operações)

**Checkpoint:** 2026-11-11, fuso BRT. **Status:** auditoria e implementação de preflight; **migração física ainda NÃO realizada**.
**Responsável desta trilha:** Operação e migração de workers. **Fora de escopo:** expansão municipal/UF de outro agente, `AGENTS.md`, cofre do IRON, alteração do código fiscal, novos conectores, emissão fiscal produtiva.
**Repositório:** `faabio3131/nf-core-v001`. **Branch de trabalho exclusiva:** `ops/nfcore-workers-contabo-preflight-20261111`; não fazer cherry-pick/merge automático de PRs de expansão nem da PR #422.
**Baseline confirmado na abertura:** `main@545b7606208eedf77b3fd6b852ccb82b4716f6b8`, `production@61015a837be8b2e5e3b0f1cdb5fb14c5c875fb91`. Confirmar novamente antes do cutover.

## Achado principal — bloqueio histórico do Claude Code

Fonte de continuidade histórica (26/10/2026): havia API, Portal, PostgreSQL e primeiro platform_admin, mas **nenhuma unidade/SecretBinding GSM** e **nenhum worker de produção** no Compose principal; PR #243 do cache GSM não foi mergeada naquele momento. O estado atual da PR #243 é fechado sem merge; a implementação de cache/rotatividade hoje existe no código de `production` em `production_multi_gsm.py`. Histórico é contexto, não fonte da verdade técnica.

Evidência direta de 11/11 fornecida pelo operador:
- `docker ps -a --filter name=nfcore`: DB/API/Portal principais `healthy`, worker **de ensaio** saudável, **nenhum** `nfcore-worker` nem `nfcore-bling-worker`.
- `ls -ld /opt/fm/nfcore/.env.worker /opt/fm/nfcore/.env.bling.worker /opt/fm/nfcore/docker-compose.override.yml`: os três **ausentes**.
- GCP `fm-nfcore-prod`, número `646230745113`: duas contas SA, `nfcore-api` e `nfcore-worker`, ativas; **uma key ID no console para Worker**. Secret Manager global mostrava somente `nfcore-openai-api-key`. Isso **não prova** posse da chave JSON privada, sua validade ou IAM secret-level.
- Railway último status consultado: `nfcore-worker` antigo OFFLINE; verificar novamente antes de habilitar novo consumidor.
- Auditoria GitHub Actions [#42941524225](https://github.com/faabio3131/nf-core-v001/actions/runs/42941524225) comprovou canal SSH/readiness da API e host; não audita identidades de worker nem faz migração.
- PR [#422](https://github.com/faabio3131/nf-core-v001/pull/422) separada/sem merge, CI [#42954475796](https://github.com/faabio3131/nf-core-v001/actions/runs/42954475796) 3.815 PASS/3 SKIP; prepara segurança do esquema Bling 19→21. Não acoplar a instalação GSM geral ao DDL Bling.

## Autoridades (sem cofre novo ou mistura de SaaS)

| Dado/segredo | Autoridade | Regra |
|---|---|---|
| OAuth e token do Bling | instalação canônica do NFCore; token criptografado no PostgreSQL com chave externa | Não copiar de Railway nem de outro SaaS; Client Secret e master-key via mounts protegidos |
| Certificado A1 | `EncryptedA1Vault` do próprio NFCore, por tenant/unidade/CNPJ homologação | Não é chave HMAC do Worker; não tocar no cofre IRON |
| Chave da identidade SA Worker | Conta `nfcore-worker@fm-nfcore-prod.iam.gserviceaccount.com` | Privado, modo 0600, UID10001 e mount RO no container; nunca Git/chat/env plaintext |
| HMAC dos webhooks de saída | Google Secret Manager, `SecretBinding` por tenant/unidade | IAM `secretAccessor` somente no recurso exato, versão pinada, escopo validado |
| Release | branch `production` e `.deployed` | SHA de imagem Worker deve corresponder ao código autorizado; não subir `main` no host produtivo |

**Conclusão:** projeto/SA já existem, mas a credencial privada válida, as políticas IAM por segredo e os bindings não foram certificados. **Cadastro da FM Tecnologia como cliente não destrava o bootstrap da identidade**. O worker multiempresa pode iniciar sem clientes com service account válida, porém não executará entregas até ter unidade/binding/destino aprovados. `healthy` sem dispatch não é certificação E2E.

## Separação funcional dos dois workers

**Worker GSM geral**: `Dockerfile.worker` + `worker_main.py` + `production_multi_gsm.py`; perfil `worker-authorized`, `compose.worker.opt-in.yml`. Processa outbox **DELIVER_WEBHOOK_OPERATION** por escopos autorizados de **HOMOLOGATION**. **Não é o motor síncrono da emissão NF-e/NFS-e.** Não requer esquema Bling v21, cliente cadastrado ou A1 para subir vazio.

**Worker Bling**: mesmo código/DB canônicos, outro perfil `bling-worker-authorized` com `NFCORE_WORKER_CONNECTOR=bling-multi` e `compose.bling.worker.opt-in.yml`; API Bling é overlay da API existente. Depende de migrações 20 e 21 + cliente OAuth app Bling da FM + Client Secret, chave AES-GCM e scopes reais. **Cliente final não é necessário para testar isoladamente o código**, mas OAuth/secret real e autorização são necessários para ativar essa integração externa de maneira funcional.

**Ensaio**: `nfcore-ensaio-worker-1` jamais pode ser usado como worker principal nem como prova de dados fiscais reais.

## Gates pré-corte e sequência sem perda ou quebra

**G0 — CURRENT e ausência de dupla execução (read-only).**
- Reconfirmar `main`, `production`, PRs de expansão e #422, CI de cada HEAD, checkout `/opt/fm/nfcore/src` e `.deployed`.
- Rodar `deploy/contabo/worker-readonly-preflight.py --expected-production-sha <SHA_PRODUCTION>` via SSH `fmadmin`; **não lê conteúdo do .env, JSON, certificados, vault ou outros SaaS**.
- Verificar estado atual do Railway por serviço, timers/crons e ausência de segundo consumidor da mesma outbox; não remover dados do Railway até certificar cutover. Identificar backlog e leases com consultas aprovadas read-only, nunca `TRUNCATE`.
- Confirmar `nfcore-db`, API, Portal, identidade fiscal de homologação e snapshots de backup. Falha de host, release ou SSH = NO-GO.

**G1 — Identidade GSM de produção e Secret Manager (sem cliente).**
- Inspecionar apenas metadados e permissões da conta `nfcore-worker` no projeto exclusivo `fm-nfcore-prod`; confirmar chave ainda habilitada/sem revogação e validade conforme código, secreta apenas no operador seguro.
- Localizar legitimamente a **chave JSON privada** correspondente a essa key ID. **O Google não permite baixar novamente o conteúdo de uma chave já criada.** Não procurar indiscriminadamente chaves em outros SaaS nem copiar do Railway/staging.
- Se não houver posse do arquivo privado válido, o cutover é **NO-GO** até emissão de **nova key temporária** por operador autorizado, revisão IAM, entrega criptografada, rotação e revogação posterior da key antiga somente após certificar dependências. Nunca exibir material em chat, Actions ou logs.
- Preparar no host path exclusivo da identidade Worker com 0600, proprietário UID10001; não modificar SSH/firewall, env base, IRON, nem restaurar backup sem gate.
- Configuração host-owned `.env.worker` deve ter `NFCORE_WORKER_GSM_MODE=multi-tenant-production-sa-v1`, projeto/number/allowlist, as duas SA como identificadores, HOST_NAMESPACE, key ID, created/expiry. Sem `GOOGLE_APPLICATION_CREDENTIALS`, wildcard, Client Secret nem credenciais em JSON via env.
- Não conceder secretAccessor no projeto inteiro. Sem tenant ainda, é válido não ter segredo HMAC de cliente; não fabricar binding/segredo para deixar verde.

**G2 — Prova não mutável de imagem e schema.**
- Confirmar `production` no checkout e no `.deployed`, imagem do Dockerfile.worker construída do mesmo release pinado, Docker config + mounts RO e rede interna, sem porta externa, healthcheck e sem duplicar API/DB.
- `worker_main.py` valida PostgreSQL/schema antes de processar. Probar schema atual 19 sem Bling; `NFCORE_WORKER_ONESHOT=true` é **somente teste de dependências**, não valida assinatura/identidade, e **não** deve ser usado como prova de E2E nem para executar trabalho. Nunca habilitar worker em staging por engano.

**G3 — Ativar worker GSM geral de forma controlada (exige prova de G0–G2).**
- Congelar janela, aprovar release exato, criar backup verificado e **ensaiar restore em base isolada**. Conservar rollback da imagem e arquivo de configuração original.
- Ativar `compose.worker.opt-in.yml` pelo perfil autorizado sem alterar `compose.prod.yml`, `/opt/fm/nfcore/.env` nem serviços IRON; uma instância única, sem criar filas/tabelas novas.
- Confirmar `nfcore-worker` com processo UID10001, container íntegro, imagem/commit, health fresco, observabilidade, zero mensagens quando não houver destino autorizado; testar autorização negativa e recuperação de lease/retry/DLQ em dados isolados, sem emissão fiscal.
- **Não alterar ainda** `restart: no` nem automatizar deploy: primeiro certificar idempotência, crash recovery, shutdown gracioso e reversibilidade. Depois aprovar supervisão/persistência pós-reboot com monitoramento e versão pinada em PR operacional independente.
- Falha: parar **somente** o worker novo, manter API/portal/DB, retirar perfil opt-in, preservar backlog/outbox e fazer postmortem; não restaurar DB só por falha de startup do worker.

**G4 — Bling, trilha independente.**
- PR #422 e release candidata #420 precisam de reconciliação e autorização de merge **separadas da expansão nacional**; nenhum reset/force-push.
- Ensaiar restauração de dump real em PostgreSQL isolado, `migration_guard.py --plan-production-bling` somente leitura, obter aprovação de DDL e aplicar 20/21 pela autoridade canônica (nunca em startup), verificar esquema, logs e backup/recovery.
- Cliente OAuth app Bling deve ser da FM, registrado com redirects/scopes reais, chave AES/Client Secret no host, com mount RO por UID10001; API Bling ativada no MESMO `nfcore-api` e depois worker via perfil opt-in. Cliente/contador necessário apenas para fluxo OAuth real e emissão externa; sem isso, marcar `EXTERNAL_UNVERIFIED`.
- Não criar credenciais inventadas nem desligar gate para obter Docker `healthy`.

**G5 — Certificação operacional e Go/No-Go.**
- Testes reais de restart/reboot planejado, readiness pós-recuperação, snapshot/restore, quotas, logs redigidos, retries/DLQ, tenant isolation, dupla execução negativa, rollback de configuração/worker.
- Web jornadas, auth/RBAC, tenant/unidade, A1 e homologação fiscal externa verificadas **separadamente** com certificado da contabilidade quando autorizado.
- Classificar A Funcional, B Paridade comercial, C Produção técnica, D Operação, E Comercial. Nenhum item 100% sem prova.

## Condições de parada

A instalação é **NO-GO** se faltar arquivo SA privado correspondente à key ID atual, se o host/branch/SHA diferirem, se não houver backup/restore ensaiado, se as permissões de arquivo não permitirem UID10001 ou se houver worker concorrente. A ativação Bling também é **NO-GO** sem DDL certificado, segredos da aplicação e testabilidade segura. **O usuário autorizou migração apenas sob condição de segurança demonstrada; isso não constitui autorização para improvisar uma credencial, editar DB, compartilhar cofre IRON ou tocar nas PRs do agente de cobertura.**

## Evidência e checklist persistente

Auditoria consolidada [issue #424](https://github.com/faabio3131/nf-core-v001/issues/424), incidente [#417](https://github.com/faabio3131/nf-core-v001/issues/417), PR de Bling [#422](https://github.com/faabio3131/nf-core-v001/pull/422).
Esta trilha **não atualiza** `AGENTS.md` nem arquivos fiscais/municipais: outro agente é autoridade da expansão. Quando houver output real do novo preflight, publicar somente status/sha/metadados no checkpoint e resolver G0–G1 antes da migração.


## Reconciliação de implementação e EGM — 11/11/2026

- **G0, marcador real da release:** `deploy/contabo/deploy.sh` grava `.deployed` como `SHA=<40 caracteres>`. O inventário foi alinhado ao formato canônico; SHA cru, duplicado, host incorreto ou checkout divergente causam `NO_GO`.
- **Fail closed:** o executável agora retorna exit code não zero para `RESULT=NO_GO_*`. A ausência do worker não pode ser interpretada como preflight aprovado apenas porque Docker respondeu.
- **Fronteira entre SaaS:** os mounts privados de identidade devem pertencer a um namespace aprovado do NFCore: `/opt/fm/nfcore`, `/etc/nfcore` ou `/run/nfcore`. Caminhos externos, `..` e escapes por symlink são rejeitados **sem abrir arquivos de outro SaaS**. Se a instalação legítima usa caminho diferente, exigir revisão humana e ajuste explícito do contrato, nunca bypass no host.
- **Testes de regressão adicionados:** formato do marcador, rejeição de marcador ambíguo, status de saída NO-GO, caminho cross-SaaS e symlink de diretório. Este checkpoint não converte testes sintéticos em prova de host real.
- **Documentos de governança:** `AGENTS.md` pertence à trilha de expansão geográfica e não será alterado aqui. `agentes.md` exige evidências e certificação antes de produção. O EGM (Elephant-Goldfish Model) requer revisão independente nativa, relatório de drift e prova de isolamento de revisores. **Nenhuma execução Goldfish nativa é alegada nesta PR**; o gate EGM independente segue pendente até haver artefatos verificáveis.
- **Canal operacional:** a tentativa de inspecionar a VPS via Desktop Commander em 11/11 retornou limite mensal de uso, sem executar comandos no host. Não inferir que o host atual corresponde ao inventário histórico. Usar apenas canal SSH autorizado, com host key previamente conferida e comandos read-only, ou o Plano B previamente aprovado. Não instalar/rotacionar credenciais, ativar workers, editar IAM, realizar DDL ou reboot como contorno.
- **Certificação:** a PR #425 só pode avançar após CI completa no HEAD exato, inspeção/retorno read-only sanitizado, revisão EGM independente exigida e conciliação dos gates G0–G5. Mesmo com CI verde, identidade privada, `.env.worker`, bindings e execução E2E seguem não comprovados até validação no host. Sem merge/deploy automático.

## Plano B — ampliação GSM sem Desktop Commander (11/11/2026)

**Estado:** código candidato na PR #425. O comando GSM da auditoria remota ainda exige revisão, integração autorizada e atualização administrativa dos arquivos root-owned da VPS. Nenhuma nova execução GSM no host está certificada por esta seção.

**Autoridade única:** manter `nfcoreaudit`, o mesmo environment `nfcore-contabo-audit` e o mesmo `sudoers` sem argumentos do Plano B. Não instalar outro serviço, outra autoridade de secrets, agente persistente, shell interativo, usuário Docker ou túnel. Não executar este fluxo em `pull_request`, branch desprotegida ou repositório não revisado.

**Contrato SSH ampliado:**
- `nfcore-audit <production_SHA40> <sha256_64>`: modo legado Bling, inalterado e compatível com o stdin original.
- `nfcore-gsm-audit <production_SHA40> <sha256_64>`: novo modo GSM que transmite exclusivamente o marcador `gsm` e os dois digests para o helper sudoers root-owned.
- O helper somente permite os destinos absolutos root-owned `/usr/local/libexec/nfcore-audit/bling-operational-host-audit.sh` ou `/usr/local/libexec/nfcore-audit/worker-readonly-preflight.py`, conforme o modo; nunca um path/argumento remoto livre. Valida owner, symlinks, ancestors e hash SHA-256 da opção selecionada.
- GSM roda via `/usr/bin/python3 -I` com ambiente mínimo, sem importar código executável do checkout `/opt/fm/nfcore/src`; o script do checkout serve só como **referência auditável de hash**.
- A auditoria não imprime chave privada, `.env.worker`, conteúdo de Secret Manager, Docker inspect bruto, dados de outro SaaS ou certificados. O GitHub filtra novamente a saída com vocabulário de status restrito.

**Gate administrativo de instalação (HUMAN_APPROVAL_REQUIRED):** após review, CI e autorização específica, o operador legítimo deverá conferir que `main`, `production` e a árvore instalada correspondem às revisões autorizadas. Comparar os hashes dos scripts revisados; instalar em um único procedimento controlado `host-audit-command.sh` como `ssh-gate.sh`, `root-host-audit.sh` como `root-audit.sh` e `worker-readonly-preflight.py` como `worker-readonly-preflight.py` sob `/usr/local/libexec/nfcore-audit`, todos `root:root`, `0555`, nunca symlink ou group/world-writable. Preservar o script Bling existente. Validar sudoers e todos os ancestrais e provar que os dois modos funcionam sem shell. Preparar rollback dos arquivos anteriores e jamais sobrescrever parcialmente o par SSH/root gate. A PR não instala nada no host.

**Auditoria após provisionamento do canal:** executar manualmente `NFCore Contabo GSM Read-only Audit (Plan B)` na branch **main protegida**, fornecendo o SHA exato da branch `production`. O workflow recusará mismatch de SHA, host key desconhecida, segredo ausente, digest divergente e qualquer relatório GSM incompleto. Se o worker ainda não existir, o resultado correto é `NO_GO_GENERAL_WORKER`, não um falso PASS.

**Critérios independentes para ativar o GSM:**
1. Release: `main` para auditoria revisada; `production`, checkout da VPS, `.deployed` e imagem worker compatíveis no SHA aprovado. Branch `main` por si só não autoriza executar código em produção.
2. Identidade privada: confirmar **fora do GitHub e do chat** a chave privada da SA `nfcore-worker`, titularidade, validade/revogação, permissões IAM mínimas e acesso apenas aos SecretBindings aprovados. Metadados de arquivo/mount não comprovam autenticação Google; não gerar chave sem autorização.
3. Configuração: `.env.worker` com proprietário/modo restritos, flags corretas, UID 10001, mount somente leitura, network interna, sem portas e sem `docker-compose up` automático. A auditoria não lê valores.
4. Consumidores: inventário local de `nfcore-*` workers apenas; existência de worker de ensaio demanda revisão. **Railway**, outros hosts, cron/systemd, DB claims, leases/outbox e exclusividade entre workers permanecem `UNVERIFIED_EXTERNAL` até evidências autorizadas e atuais.
5. Resiliência: backup verificável, restore ensaiado em destino isolado, rollback do worker e observabilidade; nenhum backup é considerado certificado somente pelo checksum.
6. Aprovação: GO/NO-GO humano específico antes de provisionamento GSM, mudança de IAM, ativação de perfil Docker, deploy ou cutover. Nenhuma migração/ativação Bling é autorizada pela aprovação do GSM.

**Isolamento:** esta trilha não modifica IRON, vault compartilhado, credenciais de outro SaaS, `AGENTS.md`, regiões/municípios ou branches/PRs da expansão nacional. A CI prova apenas o código e os contratos simulados; não substitui auditoria da VPS nem autorização externa.
