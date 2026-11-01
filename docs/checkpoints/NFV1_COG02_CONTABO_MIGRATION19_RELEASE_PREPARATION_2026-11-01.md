# NFCore V1 — Preparação COG-02: migration 19 + Web Contabo (01/11/2026)

**ESTADO: PREPARATION_ONLY / NO_GO_PRODUCTION.** Não autoriza nem executa migration, merge em `production`, deploy ou habilitação Gemini/OpenAI. Autorização do proprietário nesta sessão: **preparar** a aplicação governada da migration 19 e atualização Web. Cada operação produtiva requer gate e aprovação específica após evidência do servidor.

## Fontes de verdade verificadas neste checkpoint

- Repositório canônico `faabio3131/nf-core-v001`; `main=d3d1002a54b78b0c7df7f77f28aeac181bc2c40d` no levantamento; PR #301 **MERGED**, CI pré-merge #41324055176 **SUCCESS**, Gov #41324055254 **SUCCESS**. O conector de runs filtra por pull request, portanto **CI/Gov pós-merge na main NÃO VERIFICADAS**.
- `production=a3a2b3c97d26780b1e2b7581b4c93b6f07e86a70` no compare da branch, divergente da `main`: main 205 commits à frente, production 6 exclusivos, 127 arquivos diferentes na comparação. Não interpretar o Git como prova do estado dos containers.
- PR de release #296 **OPEN/DRAFT/NO_GO**, HEAD `b29396051eacfe56db8f55471def3b5fbce38fa2` no levantamento, construído a partir de main anterior; **não promover nem reutilizar o seu HEAD antigo** sem recriar/reconciliar a árvore à `main` atual e CI/Gov próprios.
- Servidor-alvo documentado: Contabo `vmi3692211`, implantação pull em `/opt/fm/nfcore`, `production` conferida pelo cron a cada 5 minutos. Desktop Commander `DESKTOP-URCTNQ1` **OFFLINE** nesta sessão. **Não foram lidos** `.deployed`, scripts instalados, cron, Docker, banco, backup, DNS, TLS, logs ou SHA efetivo dos containers.
- `deploy/contabo/deploy.sh` versionado é **code-only**, executa `--check-policy` e `--assert-current-production` sem DDL, backup pré-deploy, health e rollback de código. Já `scripts/ci/run_production_promotion.sh` é **legado/alternativo e executa `--apply`**; PROIBIDO usar esse script para o procedimento Contabo.
- `PostgresFiscalDatabase.require_current_schema()` exige o conjunto exato de migrations **1..19** no código novo. Um runtime anterior pode exigir **1..18**. Logo, **migration antes do deploy pode interromper a API antiga**; deploy antes de migration é recusado pelo gate. **NÃO executar a sequência produtiva sem janela de manutenção validada ou release intermediária de compatibilidade certificada**.
- Quotas aprovadas em `docs/NFCORE_V1_COG02_APPROVED_AI_QUOTAS_2026-11-01.md`; trial 750k/210k (30 dias), Essencial 1M/300k, Crescimento 3M/900k, Escala 8M/2,4M (mensal). O código inclui migração 19 aditiva de reservas. **Modelos reais continuam OFF** até assinatura, quotas publicadas, segredos e auditoria comprovados.

## 1. Preflight READ-ONLY — obrigatório e sem credenciais no chat

Rodar **somente depois de restabelecer acesso ao host** e conferir usuário `fmadmin`, a partir da cópia versionada do script sem instalá-lo por engano. O script `deploy/contabo/preflight-cog02.sh` **não faz** git fetch/checkout/push, Docker compose, backup, DDL, escrita no banco ou restart. Exige congelar o SHA de `main` na variável `NFCORE_COG02_TARGET_MAIN_SHA` e compara diretamente com `git ls-remote`. Inspeciona somente `.deployed`, digests dos containers em execução, sequências 1..18/1..19, referência das branches e existência de candidatos de backup.

Exemplo de invocação **no host autorizado**, usando o SHA exato validado previamente:

```bash
NFCORE_COG02_TARGET_MAIN_SHA=d3d1002a54b78b0c7df7f77f28aeac181bc2c40d \
  bash /opt/fm/nfcore/src/deploy/contabo/preflight-cog02.sh
```

Se a `main` avançar, congelar o **novo** HEAD auditado e repetir a CI/Gov, nunca editar SHA só para passar. Se script não estiver presente na cópia instalada, não antecipar checkout/push: atualizar fonte via fluxo de código aprovado ou usar revisão read-only equivalente, sempre sem tocar `production`.

**Não compartilhar valores de `.env`/DATABASE_URL, segredos, certificados, tokens ou dumps nos logs/PR.**

## 2. Gates para preparar a migration 19

1. Obter `main`, `production` e `deployed` efetivos; comparar `deploy/contabo/deploy.sh` instalado com o arquivo versionado. Auditar cron (pode disparar automaticamente), saúde do banco, volumes, NPM/DNS/TLS e status de API/Portal.
2. Rodar checks **read-only**: `python scripts/ci/migration_guard.py --check-policy` no código candidato e consultar `fm_schema_migrations` / `fm_cakto_schema_migrations` sem alterar o banco. Exigir sequência contínua conhecida **1..18** para v19 pendente, ou **1..19** para v19 já presente. Qualquer outro estado é **NO_GO**. Se outras migrations estiverem pendentes, plano muda e exige auditoria/autorização própria.
3. Antes de qualquer DDL: produzir backup `pg_dump` da instância certa, com SHA-256 validado, verificar integridade e executar ensaio de restore **somente em banco isolado/descartável**. Comprovar retenção, acesso e rollback de dados; backup presente em disco **não** prova que restaura.
4. Inspecionar a migration 19 (somente `CREATE TABLE fm_cognitive_token_counters` e `CREATE TABLE fm_cognitive_token_reservations`, sem alteração destrutiva) e políticas no `scripts/ci/migration_guard.py`. Exigir auditoria de impacto/performance/locks e plano de interrupção controlada.
5. **Decisão humana nova e explícita:** autorizar migration produtiva com SHA, ambiente, janela, responsável, backup verificado e estratégia de retorno. A palavra `preparar` não concede essa permissão.
6. Executar a migration **uma vez** pelo orquestrador canônico em ambiente controlado com aprovação temporária e comprovada, **sem** executar `run_production_promotion.sh` e **sem** permitir que cron publique código simultaneamente. Validar `--assert-current-production` **read-only** após DDL.
7. Sem compatibilidade comprovada 18↔19, planejar **janela com manutenção/indisponibilidade controlada** entre a migration e o deploy. Evitar falsas promessas de zero downtime. Nunca restaurar dados produtivos automaticamente por rollback de imagem.

## 3. Gates para atualização Web/API Contabo

1. A release #296 NÃO é atual. Reconciliar candidato a partir de **main CURRENT**, preservando o ancestral histórico de production, mesma árvore de código que o SHA de main escolhido, sem reverter arquivos, com PR Draft e CI/Gov na candidata.
2. A comparação atual tem **127 arquivos e mais de 200 commits** entre as branches; revisar impactos dos módulos RTC, BUILD, Web, comerciais, banco e container, não presumir que a PR #301 seja a única mudança publicada.
3. Checar readiness do runtime e da borda `api.nfcore.com.br`, `app.nfcore.com.br`, TLS/Nginx Proxy Manager, CORS da origem publicada, health live/ready e jornada com login real em ambiente controlado. Nenhuma simulação equivale à homologação fiscal.
4. Durante a preparação, **não** fazer merge/push em `production`: esse ato pode disparar deploy em até 5 minutos. Quando autorizada a promoção, conferir bloqueios anteriores (migration 19 certificada, backup/restauração, SHA de imagens, janela) e registrar Go/No-Go humano.
5. Publicação futura pelo mecanismo existente `deploy/contabo/deploy.sh` (code-only), após aprovação. Smoke autenticado e verificação do SHA de API/Portal, persistência, logs, alertas e rollback do código. Worker/GSM não está incluso no compose, e fiscal oficial/billing real têm gates próprios.
6. Manter `NFCORE_COGNITIVE_DURABLE_AI_ENABLED` desabilitado até publicação versionada de quotas pagas + auditoria, chaves no secret store, observabilidade e teste de custos. Não colocar chaves reais em repo/PR/chat.

## 4. Critérios de aceite e status do checkpoint

| Gate | Estado neste checkpoint |
| --- | --- |
| COG-02 código/migration 19 integrado à main | CONFIRMADO (#301, `d3d1002a`) |
| CI/Gov pré-merge da #301 | SUCCESS |
| CI/Gov pós-merge da main | NÃO VERIFICADOS |
| Script read-only preflight Contabo | IMPLEMENTADO NA PR DE PREPARAÇÃO; CI PENDENTE |
| Backup/restore real Contabo | NÃO VERIFICADOS |
| Schema/migration 19 no banco Contabo | NÃO VERIFICADO / NÃO APLICADO POR ESTE EXECUTOR |
| Reconciliação PR release #296 com main atual | PENDENTE |
| Candidata de release aprovada | NÃO |
| Merge production/deploy/ativação de IA | **NÃO EXECUTADOS** |

**Bloqueio principal:** Desktop Commander offline; falta evidência da versão e schema reais da Contabo. **Próxima ação:** concluir CI da PR preparatória, integrar na main somente se gates verdes e autorizados, restabelecer acesso seguro read-only ao servidor, obter inventário de runtime/banco/backup; então submeter Go/No-Go das operações produtivas separadas.

## 5. Atualização verificada no servidor — 01/11/2026 18:02 UTC

**FATOS CONFIRMADOS — inspeção estritamente read-only, SSH `fmadmin` via Desktop Commander, IP 13.140.234.22:**

- Identidade do host: `vmi3692211`; SSH autenticado por chave via PC autorizado, sem envio de senha.
- `/opt/fm/nfcore/.deployed` contém `SHA=a3a2b3c97d26780b1e2b7581b4c93b6f07e86a70`. Checkout `/opt/fm/nfcore/src` no mesmo SHA, HEAD destacado e `git status --short` sem alterações reportadas. É a versão da branch `production`, não a `main` atual.
- `nfcore-db`, `nfcore-api` e `nfcore-portal` em execução, com Docker HEALTHY. Existem outros produtos e containers no mesmo host; não tocá-los.
- `fm_schema_migrations` consultada via `docker exec nfcore-db psql -U nfcore -d nfcore` de forma somente leitura: versões instaladas **1 a 18 inclusive**, sem 19. Não houve DDL.
- Backup diário `/opt/fm/backups/nfcore-diario/nfcore-20261101-034501.dump` presente com sidecar SHA-256; `sha256sum -c` resultou **OK**. Log diário às 03:45 registra **OK** em 29/10, 30/10, 31/10 e 01/11. **Integridade SHA-256 não substitui ensaio de restauração.**
- `https://api.nfcore.com.br/health/ready` respondeu **HTTP 200**; `https://app.nfcore.com.br/` respondeu **HTTP 200**, consultados a partir do host via curl. Isto não certifica jornadas autenticadas, TLS aprofundado, fiscal ou Web comercial.
- `/opt/fm/nfcore/deploy.sh` e `/opt/fm/nfcore/nfcore-backup.sh` existem no host. **Seu conteúdo/diferença com os scripts do GitHub e cron efetivo ainda não foram auditados.**
- A PR #302 no commit `c412637c8d4b82316398ac954d32ec4463839ba7` passou **FM NFCORE V1 CI #41332772663**, **Deploy Contabo #41332772670** e **Governança #41332772693**. O bug de índices dos argumentos Docker no mock foi corrigido sem alterar o script de preflight. Esta atualização documental exige nova CI no HEAD resultante.

**CURRENT → TARGET:** production/schema 18 saudável → release candidata atual reconciliada, plano de compatibilidade 18↔19, backup com restore ensaiado, janela aprovada, migration 19 e código novo promovidos sob Go/No-Go separado. Até lá **NO_GO_PRODUCTION**. Acesso operacional read-only está restabelecido, mas não equivale a aprovação de deploy. A PR #296 segue Draft/obsoleta e #302 Draft sem merge.

## 6. Correção operacional Contabo — 01/11/2026, executada e verificada

**AUTORIZAÇÃO DO PROPRIETÁRIO:** corrigir conjuntamente mecanismo de deploy e seus contratos no servidor, **sem migration 19 e sem atualizar a aplicação**.

**GATE E CURRENT antes da correção**

- SSH via Desktop Commander conectado ao PC autorizado, usuário `fmadmin`, host `vmi3692211`, IP público validado pelo proprietário. Acesso por chave já carregada; nenhuma senha foi solicitada, lida ou publicada.
- `/opt/fm/nfcore/.deployed`, checkout Git e `origin/production`: `a3a2b3c97d26780b1e2b7581b4c93b6f07e86a70`.
- O script instalado executava `migration_guard.py --apply` com flags de aprovação produtiva embutidas e `nf_restore_db` no rollback: **risco produtivo comprovado**. O compose instalado usava imagens `:cur`, enquanto o fluxo seguro do GitHub usa `:current`; faltava `/opt/fm/nfcore/backup.sh`.
- Backups diários existentes, com SHA-256 válido no dump de 01/11. Banco fiscal na versão 18 e Cakto 1–2; API e Portal saudáveis. Restore real em banco isolado ainda NÃO foi executado.
- Scripts seguros retirados da árvore CURRENT da `main` verificada por merge de ensaio (tree idêntica); staged em `/opt/fm/nfcore/.safe-deploy-stage-20261101`. `bash -n`, teste de negação sem autorização e matriz mock do `deploy.sh`: **TODOS PASSARAM**. A falha inicial na cópia mock foi de permissão de execução do `backup.sh` transferido por SCP; corrigida apenas na cópia de ensaio antes da aprovação do gate.
- Ativador versionado `deploy/contabo/activate-code-only-host.sh`, com lock `/tmp/nfcore-deploy.lock`, SHA congelado, verificação das refs/containers/contratos, snapshot de reversão e bloqueio de execução sem autorização explícita.

**CORREÇÃO PRODUTIVA AUTORIZADA (somente artefatos operacionais, sem release):**

1. Sob o mesmo lock exclusivo do cron, confirmou-se a igualdade entre `.deployed`, checkout e `origin/production` no SHA acima.
2. Backup dos scripts/compose e marcador anterior, com permissão restrita, em `/opt/fm/nfcore/.code-only-host-contract-backup-20261101T184541Z`.
3. Tags de imagem locais `nfcore-api:current` e `nfcore-portal:current` criadas como aliases das imagens `:cur` atuais; atualizado **somente** o campo de imagem dos serviços no `docker-compose.yml` instalado. Nenhum container foi recriado.
4. Instalados `deploy.sh` **code-only**, `deploy-lib.sh` com proteção de restore apenas para DB descartável, e `backup.sh` compatível com o caminho `/opt/fm/backups/nfcore-diario`. O backup diário legada `nfcore-backup.sh` continua no cron, operando sem alterações.
5. `deploy.sh` instalado **não contém** `--apply`, flags de aprovação de migration produtiva ou invocação de restore automático; exige `--assert-current-production` read-only para um futuro deploy autorizado. `deploy.sh status` e `--check` executados com sucesso sem atualizar a aplicação.
6. Validação pós-instalação: Git e `.deployed` ainda `a3a2b3c...`; API, Portal e DB Docker healthy; API `/health/ready` HTTP **200**, Portal HTTPS HTTP **200**; ledger `fm_schema_migrations` ainda **18 versões, máximo 18**; cron de deploy `*/5` e backup 03:45 preservados; compose válido com imagens `:current`. **Sem DDL, deploy, alteração de dados, alteração de `.env` ou restart.**

**GATES E PRs:** #302 contém a preparação e o ativador, ainda Draft/sem merge; #303 candidata de compatibilidade schema 18/19, Draft/sem merge; #304 reconciliação de release, Draft/sem merge. As PRs #303/#304 tiveram CI e governança verdes no último HEAD consultado; CI da #302 estava em execução antes deste checkpoint, exigindo conferência no novo HEAD após registro. Nenhuma dessas PRs foi integrada a `production` e nenhuma tag/branch de aplicação produtiva foi promovida.

**RISCO REMANESCENTE / NO_GO:** migration 19 permanece pendente. Antes de aplicar DDL ou autorizar o merge de release: testar restore de dump em banco inteiramente isolado, certificar compatibilidade bridge 18↔19 com cenário realista de PostgreSQL, congelar SHA da release, confirmar plano de manutenção/rollback e aprovar separadamente migration e deploy. O backup anterior do script inseguro existe **somente para recuperação operacional**, não deve ser reativado como autoridade automática de deploy. O mecanismo code-only agora está ativo na Contabo, mas **não autoriza operações produtivas futuras por si só**.
