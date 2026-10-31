# FM NFCORE V1 — Reconciliação cruzada anti-retrabalho (31/10/2026)

**Tipo:** auditoria READ-ONLY de código/PRs/CI, seguida somente de atualização documental isolada. **Não constitui certificação comercial, homologação, autorização de deploy, promoção ou alteração de produção.**

## Fonte de verdade e baseline

- Repositório efetivo: `faabio3131/nf-core-v001`, `main=d68c62d9c7e90581ad5efd387927f83c40a59ba2` no início desta auditoria. O nome antigo `faabio3131/kordena-fiscal-engine-v2` resolveu para o **mesmo repository ID GitHub 1366374504**: alias/rename, não dois códigos concorrentes.
- CI da `main` no SHA acima: run `41167507102` SUCCESS; Governança `41167507147` SUCCESS. Também há runs da PR correspondentes SUCCESS (`41167510730`/`41167510715`).
- `AGENTS.md`, cronograma de 59 IDs, ledger de 59 IDs, anexo BUILD e ledger BUILD são autoridades de escopo e governança, **mas registros históricos não prevalecem sobre código e PR CURRENT**.
- A PR #278 RTC-09 foi MERGED em `a01414853cdad9cc4ade8886b8a53074a57a2568`; CI pós-merge `41166087218` SUCCESS e Governança `41166087207` SUCCESS no mesmo SHA. A PR #260 BLD-03 foi MERGED depois, em `d68c62d9c7e90581ad5efd387927f83c40a59ba2`, com gates verdes.
- A auditoria abrangeu PRs abertas/merges recentes, `main`, `production`, `AGENTS.md`, cronogramas BUILD/RTC, ledger mestre, código de superfície web e repositório `faabio3131/fm-site-novo`. **Não inspecionou diretamente os containers, banco ou serviços da Contabo**; o estado implantado continua por comprovar no SHA correto.

## Reconciliação sem reconstrução (BUILD)

| Bloco | Situação do código/GitHub no baseline | Estado adequado de controle e ação |
| --- | --- | --- |
| BLD-00 | DONE no ledger; PRs #226/#227 integradas | **Não reconstruir** inventário; revalidar apenas capacidades alteradas por commits novos |
| BLD-01 | DONE no ledger; PRs #228/#229/#230 integradas | **Não reconstruir** login, CSRF, RBAC, tenant/unidade, onboarding, UX já certificados |
| BLD-02 | DONE interno no ledger; #253/#254/#255/#258 integradas, CI/Gov pós-merge registradas | **Não reconstruir** emissão preparada, consulta, recuperação e handlers internos; transporte/homologação oficial é etapa distinta |
| BLD-03 | Ingresso público protegido e `portal/trial.*` integrados por #234/#235/#260, CI/Gov da main verdes; #237 teste PG e **#279 correção de gate comercial** ainda OPEN/DRAFT | **IN_PROGRESS para fechamento**, não `PENDING` nem `DONE` integral: revisar #279 (segurança/prioridade) e #237 contra testes atuais; validar offer/release, fluxo browser→DB e dependências de preço/admin; não refazer formulário |
| BLD-04 | Aquisição/checkout/provisioning/fulfillment/release são código preexistente; **#281** acrescenta testes da fronteira autenticada `/v1/commercial/command/events`, OPEN/DRAFT | **IN_PROGRESS em microentrega**, sem construir segunda cadeia comercial; fechar lacunas por inventário HTTP→estado canônico→DB/Worker e CI |
| BLD-05 | Gateways/provider-neutral e fiscal OperationPath já existem; transporte oficial não está configurado | **PENDING/PARCIAL**: apenas delta neutro provado ausente; provider/jurisdição/credenciais/homologação exigem decisão/prova separadas |
| BLD-06 | Worker, outbox, retries, audit e persistência já existem; #243 proposta isolada de cache GSM ainda OPEN/DRAFT | **PENDING de certificação integrada Web→DB→Worker**, não refazer infraestrutura; reavaliar #243 contra `main` antes de aproveitar |
| BLD-07 | Site canônico `fm-site-novo`, main `f5661ca68f84815a61bff8bb9518c0bfb18dc04d`; **site PR #12** já contém cadastro de trial e CTA, OPEN/DRAFT com validação estática SUCCESS no SHA `c3acfc34fdd7d0a05ef80da6c347be9b414f4ea2` | **PENDING de integração**, não reimplementar CTA; auditar diffs/contratos da #12, alinhas gates #279/catalog/offer e somente integrar com autorização e testes adequados |
| BLD-08 | Nenhuma prova de jornada Web publicada para todas as funções no SHA atual | **PENDING**, sem declarar `CONSTRUCTION_AND_WEB_INTEGRATION_COMPLETE` ou `COMMERCIAL_LIVE` |

**Próxima ação elegível:** concluir análise de segurança e os gates HEAD exato da **PR #279**, depois reconciliar #237 sem duplicar testes. BLD-04 #281 pode avançar independentemente, mas seu teste isolado não encerra BLD-04. Com BLD-03 fechado no código, alinhar e revisar a PR #12 do site; BLD-05/06/08 continuam por deltas específicos, nunca refazer o que a main prova.

## Frente RTC (separada de BUILD)

O cronograma `docs/NFCORE_RTC_MASTER_EXECUTION_SCHEDULE_2026-10-30.md` continua descrevendo RTC-00 como `IN_PROGRESS` e RTC-01..09 como `PENDING` **no tracker inicial**, mas desde então **#267–#275 e #278 foram integradas à main**. Portanto a tabela é um snapshot de abertura e **não pode ser usada para recriar RTC-01/02/03/09**. Entregas RTC-01/02/03/09 são incrementais, não evidência de aceitação integral de cada WP. **PR #280 RTC-03** está OPEN/DRAFT para vincular `TaxRuleEngine` ao catálogo verificado: comparar código integrado e fonte normativa antes de qualquer merge (sem autorização automática da trilha RTC). RTC-04..12, especialmente homologação oficial RTC-12, permanecem sem certificação final no escopo auditado.

## Branch `production` e Contabo — NÃO promover

- `production=01334dcbcb998adb0a9e70b46612dcb26c23c592` versus `main=d68c62d9c7e90581ad5efd387927f83c40a59ba2`: `compare production...main` reportou `diverged`, **68 commits à frente na main e 5 exclusivos em production**, com 38 arquivos diferentes.
- **PR #277** (`main→production`) está OPEN/DRAFT e representa preparação; **não** é prova de implantação nem autorização para merge na production. Seu corpo registra histórico de pré-voo Contabo, mas isso não substitui verificação atual de containers e artefatos. A PR deve ser recalculada a cada avanço da `main`.
- Alterações em `production`, deploy, SSH, migrations produtivas, DNS, segredos, billing real, assinatura/emissão fiscal real e piloto operacional **não foram executados nesta auditoria**.

## PRs abertas — classificação preventiva

- **Trilha ativa com código não integrado:** #279 BLD-03/04, #281 BLD-04, #280 RTC-03; #277 promoção protegida; #12 no repositório do site. Não assumir que CI verde de cada branch transfere certificação à main.
- **Candidatas a reaproveitamento/revisão, sem merge por antiguidade:** #237 (teste concorrência PostgreSQL do trial); #243 (cache GSM, branch baseada em main antiga); #238 (pesquisa pricing); #201 (contadores), #205 (matriz P09).
- **Potencialmente obsoletas ou supersedidas; não integrar sem comparar diffs:** #165, #182, #188, #189, #204. A própria #204 alerta que registros de migrations comerciais anteriores estão superados; #182 equivale a UX de senha já tocada pela #217; #188 tem sobreposição de métricas com trabalhos P09 subsequentes.
- PRs #256/#257 foram fechadas sem merge porque a entrega BLD-02 foi consolidada na #258; NÃO reabrir automaticamente.

## Inconsistências documentais comprovadas

1. `docs/NFCORE_V1_BUILD_INTEGRATION_LEDGER.md` no cabeçalho ainda diz "próximo BLD-03" e última main `aa04c8b2`, embora #260 já tenha integrado o formulário; a seção BLD-03 continua sem registrar #260.
2. `docs/NFCORE_RTC_MASTER_EXECUTION_SCHEDULE_2026-10-30.md` preserva o tracker **inicial** mesmo após merges #267–#275/#278; interpretar como snapshot, não CURRENT.
3. `docs/NFCORE_V1_COMMERCIAL_LAUNCH_CURRENT.md` começa com evidências Railway e SHA de 10/10. **Não é CURRENT operacional Contabo de 31/10**.
4. `AGENTS.md` reúne snapshots históricos Railway e iniciativas antigas; as regras de governança acima dos checkpoints continuam válidas, mas não se pode reutilizar estados/SHAs de cada seção histórica como status atual.
5. O ledger das 59 tarefas não deve ser alterado como consequência mecânica dos merges BUILD/RTC; só com critérios próprios e evidência.

## Sequência recomendada — dependências e gates

1. **BLD-03 segurança:** inspecionar o diff exato #279 e fechar com CI/Gov no HEAD; verificar `CommercialReleaseAdministrationService.current` como autoridade única; não habilitar oferta pública sem decisão comercial aprovada.
2. **BLD-03 provas restantes:** comparar #237 com a atual suíte PG e integrar apenas teste único ainda ausente; validar cadastro→tenant/OWNER→assinatura→ativação sem inventar preço ou duração.
3. **BLD-04:** aproveitar #281 e complementar somente os elos não cobertos da cadeia eventos autenticados→reconciliação→persistência/Worker, sem repetir testes existentes.
4. **BLD-07:** reconciliar site PR #12 com o contrato NFCore atual, readiness/segurança/CORS, e só depois avaliar merge CI verde próprio; não publicar site automaticamente.
5. **BLD-05/06:** localizar lacunas específicas após fechamento dos contratos internos; distinguir implementação técnica de provider/homologação e publicação externa.
6. **BLD-08:** matriz única por jornada e teste em ambiente autorizado no mesmo SHA, sem alegar promoção ou homologação.
7. **RTC:** em paralelo e independente, retomar #280 somente com revisão normativa e autorização própria; não recriar RTC-01/02/03/09 já parcialmente integradas.
8. **Production/Contabo:** tratar #277 separadamente, com backup/rollback/health/approval explícitos. Nenhum merge implícito de `main` para `production`.

## Gates de continuidade

Em toda retomada, verificar `repo ID`, `main SHA`, `production SHA`, PRs OPEN/MERGED/CLOSED, HEAD dos candidatos, CI/Gov do mesmo SHA, diff vs `main`, estado de `fm-site-novo`, autorização por trilha e separação `INTEGRATED_NOT_DEPLOYED` vs `WEB_LIVE`. Não registrar `DONE` global por CI verde isolada. Esta auditoria não muda checkboxes das 59 tarefas nem ativa serviços.

**Referências GitHub:** PRs [#260](https://github.com/faabio3131/nf-core-v001/pull/260), [#278](https://github.com/faabio3131/nf-core-v001/pull/278), [#279](https://github.com/faabio3131/nf-core-v001/pull/279), [#281](https://github.com/faabio3131/nf-core-v001/pull/281), [#280](https://github.com/faabio3131/nf-core-v001/pull/280), [#277](https://github.com/faabio3131/nf-core-v001/pull/277), [site #12](https://github.com/faabio3131/fm-site-novo/pull/12); CI main [#41167507102](https://github.com/faabio3131/nf-core-v001/actions/runs/41167507102), Gov [#41167507147](https://github.com/faabio3131/nf-core-v001/actions/runs/41167507147).


## Atualização de execução sobre baseline inicial (31/10/2026)

- **BLD-03 PR #279**: gate comercial `CommercialReleaseAdministrationService.current` revisado; pré-merge CI `41168166175` e Gov `41168166227` SUCCESS no HEAD `ac079f2729869d916047e9935fe89909f4fe7f14`. Merge BUILD-ONLY autorizado por `AGENTS.md`, commit `9564406e2c2af6cee99266301309f045dbbd878a`; **Governança pós-merge SUCCESS e CI pós-merge ainda em execução na última consulta**. Não certificar a `main` pós-merge antes de CI verde.
- **BLD-03 PR #237 CLOSED sem merge**: o teste real de limite de trial PostgreSQL já foi aproveitado na `main` em `tests/runtime/test_nfv1_public_trial_postgres.py`, descrito no docstring como adaptação da #237. A variante integrada cria schema individual, restringe host local, configura search_path isolado e remove só o schema criado; a PR histórica usa `DROP SCHEMA public CASCADE` e não deve voltar. Não repetir implementação.
- **Site PR #12** (branch existente `feat/nfcore-public-trial-form-20261020`): corrigidas `src/nfcore-trial.html` e `docs/nfcore-trial.html` para usar a API Contabo `https://api.nfcore.com.br` no lugar da antiga Railway. Teste estático atualizado para rejeitar URL Railway. Commit final `f8cdd918c242b320c4bf116a7843266e52b75a10`, CI `41198630091` SUCCESS. PR permanece Draft, **não mergeada nem publicada**, até verificar origem permitida/CORS, release aprovado e riscos de publicação Cloudflare.
- **Explicação da divergência `production`**: `compare main...production` listou cinco commits exclusivos: `612eae1` (#240), `7a32047` (#244), `ac0b889` (#262), `9e402cc` (#264) e `01334dc` (#266). **Todos são commits de merge** de PRs de promoção anteriores, não cinco features independentes. A história das branches é não linear: embora estes SHAs de merges não apareçam em `main`, eles preservam integrações próprias da trilha de promoção. Em `compare main...production`, o GitHub informou lista de arquivos alterados vazia; ainda assim, a reconciliação exige revisão de `production` e autorização específica, nunca `git reset --hard`/force push. O número de commits exclusivos em `main` é móvel a cada novo merge (após #279 já era 77 na última comparação), não um indicador de 77 features ausentes em produção.
- A rota `/health/ready` da API Contabo e sua URL foram citadas na PR #277; **não houve nesta etapa login no servidor, confirmação do SHA do container publicado, migração, deploy, alteração da production ou ativação fiscal**.


### Incremento seguinte — BLD-04 e site (31/10/2026)

- **BLD-04 PR #281**: testes HTTP de `/v1/commercial/command/events` revisados, CI pré-merge `41168608800` e Governança `41168608803` SUCCESS no HEAD `974e2b8c02449a4afaee69ee6b8b2366f04d83fc`. Merged BUILD-ONLY em `5d894ffcf34c8a9ee6d66876ee35c2c9273ee32a`; CI pós-merge `41199329018` e Governança `41199328979` iniciadas (ainda não certificar no momento desta anotação). **BLD-04 permanece parcial**, pois o teste HTTP isolado não comprova toda a cadeia de aquisição/billing/fulfillment.
- **BLD-03 #279**: primeira CI pós-merge `41198490385` SUCCESS e Governança `41198490371` SUCCESS no mesmo SHA `9564406e2c2af6cee99266301309f045dbbd878a`; run duplicada `41198495390` ainda executava, sem substituir gate verde já obtido.
- **Site #12**: correção adicional no cadastro para preservar `Idempotency-Key` em retries de payload idêntico; `src/nfcore-trial.html`, `docs/nfcore-trial.html` e teste foram atualizados, HEAD `451477ef76bf867ae6bfe89c335dd2d206f215cf`; CI estática `41198948564` SUCCESS. PR ainda não mergeada. Antes de publicar, conferir CORS/origins reais, plano/release aprovado e se Cloudflare publica main automaticamente.
- **Limpeza sem perda de conteúdo**: #182 (toggle senha), #189 (auditoria Railway anterior ao BLD-00) e #204 (pre-Cakto/Railway, incompatível com CURRENT) foram CLOSED sem merge por estarem supersedidas. Não reintegrar commits históricos.
- **Próxima ação**: confirmar CI/Gov pós-merge da #281, fechar evidência BLD-03/04 apenas nos limites provados, testar conexão site/Contabo em ambiente autorizado, continuar BLD-04 com delta funcional comprovadamente ausente. A branch `production` não foi alterada.
