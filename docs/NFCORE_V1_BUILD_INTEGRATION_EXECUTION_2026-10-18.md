# FM NFCORE V1 — Anexo executivo de construção e integração Web (BUILD-ONLY)

**Status:** APROVADO PARA EXECUÇÃO INTERNA pelo proprietário em 18/10/2026.  
**Vínculo obrigatório:** `docs/NFCORE_V1_COMPLETION_MASTER_EXECUTION_SCHEDULE_2026-10-05.md` + `docs/NFCORE_V1_EXECUTION_LEDGER.md`.  
**Controle próprio de evidência:** `docs/NFCORE_V1_BUILD_INTEGRATION_LEDGER.md`.  
**Agente executor:** `AGENTS.md`, seção "Autonomia BUILD-ONLY".  
**Projeto:** FM NFCORE V1 — Commercial Launch. **Produto:** NFCore, não o nome histórico do repo.

## 1. Decisão e objetivo

Este é um **anexo de execução da construção**, não um segundo cronograma mestre concorrente, nem uma mudança nas 59 tarefas e estados certificados. O proprietário determina: **terminar construção e ligação funcional dos módulos existentes antes de homologação externa, testes/certificação finais, produção definitiva e rotina operacional completa**. O avanço interno é permitido mesmo com gates externos diferidos, sem pintar tais gates de verde.

**Definition of Done BUILD:** funcionalidade da V1 codificada **na autoridade canônica**, conectada de Portal/site → API → domínio/application → persistência/Worker conforme aplicável; autenticação/RBAC/tenant/unidade fail-closed; estados de bloqueio reais; testes dirigidos + CI/Governança internos verdes; PR integrada + CI pós-merge verde; matriz de paridade atualizada. Se ainda não estiver publicada em staging, declarar `INTEGRATED_NOT_DEPLOYED`, não `WEB_LIVE`; fechamento da construção Web exige demonstração real das superfícies após publicação governada.

**Não é DoD BUILD:** pagamento real, notas autorizadas por SEFAZ/prefeitura, credenciais fiscais/clientes reais, homologação oficial, backup periódico/RPO/RTO de produção, rollout definitivo, Go/No-Go, certificação final das matrizes A–E.

## 2. Fatos e limites auditados no início

- Snapshot GitHub `main=44cddbabb4e91b55dcc730e6976fcc2ce7f00d75`, CI #1054 SUCCESS, Governança #475 SUCCESS. **Snapshot histórico; reconsultar a cada retomada**.
- Canonical runtime: `src/kordena_fiscal/runtime/api.py` e composition PostgreSQL. UI: `portal/`. Site institucional **correto**: `faabio3131/fm-site-novo` (estático). Repo de site histórico `fm-tecnologia-web-platform` **não** é destino da integração (PR #33 fechada sem merge).
- Portal/API/Worker/Postgres online 1/1 no staging Railway, denominado `production` na UI Railway, **mas `NFCORE_ENVIRONMENT=staging`**. Não é infraestrutura final.
- Existentes, NÃO REFAZER: domínio fiscal versionado, API e Portal, sessão humana/CSRF/RBAC, tenant/unidade, PostgreSQL, PasswordRecovery com e-mail, `GovernedTrialService`, pricing/release administrativos, comercial provisioning/fulfillment, outbox/Worker, GSM e backup+restore ensaiados.
- Perfil real mais recente: `commercial_trial_configured=false`, `pricing_catalog_published=false`, `commercial_first_party_acquisition_configured=false`, `commercial_checkout_provider_configured=null`, `fiscal_provider_transport_real_configured=false`, `fiscal_runtime_external_execution_ready=false`; oferta `trial_enabled=false`, `purchase_enabled=false`. A entrega do binding commercial GSM ainda **não** foi declarada concluída. Não inventar preço ou ligar checkout.
- Caminho fiscal interno `queryArchiveReference` existe; emissão/cancelamento/inutilização **não** devem receber handler fake em runtime. Ausência de homologação oficial não impede construir o adapter determinístico candidato nem a UI governada.
- As 59 tarefas antigas mantêm `32 DONE / 27 PENDING` no ledger consultado. Isso **não** mede percentual do código construído. P05-T01/T02, P02 e P03 internas estão certificadas; não reabrir sem regressão.
- PRs antigas abertas: #165, #182, #188, #189, #201, #204, #205. Auditar **diff atual vs main**, aplicar somente delta não integrado, não mergear por antiguidade.

## 3. Autoridades canônicas / mapa de impacto

| Superfície | Autoridade única | Regra |
| --- | --- | --- |
| Site institucional | `faabio3131/fm-site-novo` | HTML estático, sem secrets/HMAC/JWT no browser; link ao ingresso seguro hospedado na aplicação existente |
| Portal e sessão | `portal/`, `web/app.py`, `web/portal_api.py` | não criar segundo frontend, UI não autoriza; preservar sessões, CSRF, RBAC, escopo |
| Runtime API | `runtime/api.py` + composition root | reutilizar endpoints/serviços; sem API paralela |
| Comercial/trial | `application/commercial_trial.py`, pricing/release, fulfillment/provisioning | tenant e OWNER só no NFCore; trial não habilita produção fiscal |
| Fiscal | CanonicalFiscalOperationPath + services determinísticos + gateway registrado | sem fake/synthetic como autorização oficial; sem segunda regra ou persistence |
| Secrets | GSM/SecretBinding/SecretResolver canônicos | sem segredo no Git, logs, site ou HTML; binding administrativo por autoridade autenticada |
| Worker | outbox/Worker existente | retries/idempotência/auditoria, sem duplicar fila nem emissor |
| Dados | PostgreSQL canônico e migrations governadas | não resetar, migrar ou rodar SQL destrutivo sem aprovação específica |

## 4. Sequência **BUILD-ONLY** executável

Cada `NFV1-BLD-xx` corresponde a um **bloco verificável de construção**. Se amplo, decompor em PRs pequenas `BLD-xx.a`, `BLD-xx.b` no ledger sem criar novo domínio. Um bloco pode ser classificado `ALREADY_INTEGRATED` **somente com evidência do mesmo CURRENT**; não exige reimplementação nem repetir CI antiga.

### NFV1-BLD-00 — Inventário integral da paridade código × Web

- Confrontar PR #189, checkpoint `NFV1_WEB_PARITY_AND_FUNCTIONAL_INTEGRATION_2026-10-18.md`, `/runtime/profile`, `portal/app.js`, URLs de API, tela/ações, endpoints, permissionamento e DB/Worker. Mapear **todas** as telas e verbos CRUD, não só menu.
- Entregar tabela `capacidade → código/autoridade → UI → endpoint → RBAC/tenant → persistência/Worker → prova → lacuna → delta`. Para cada item: `ALREADY_INTEGRATED`, `IMPLEMENTED_NOT_WIRED`, `MISSING_CODE`, `CONFIG_BLOCKED`, `DEFERRED_EXTERNAL`; lacunas com IDs filhos e prioridade.
- Gate: nenhuma lacuna funcional sem classificação; nenhum código novo antes de medir delta; evitar reconstruir P02/P03/Worker.

### NFV1-BLD-01 — Identidade, onboarding e paridade operacional do Portal

- Revalidar **por evidências existentes** login, logout, recuperação, sessões, tenants, múltiplas unidades, permissões, usuário/OWNER, ativação e acesso após primeira unidade. Confrontar UI × API, incluindo mutações e vazios/erros.
- Corrigir apenas ações UI indisponíveis apesar de backend canônico existente; incluir formulário/estado de resposta quando faltar; garantir RBAC, CSRF, tenant/unidade no backend.
- Gate: jornada navegável sem segundo login e sem botão morto; matriz BLD-00 com cobertura das superfícies críticas e testes dirigidos.

### NFV1-BLD-02 — Paridade fiscal Web e executores internos

- Ligar consultas de documentos/arquivo, intents governadas de emissão, cancelamento, inutilização, erros, reconciliação, certificados/providers e webhook settings à **mesma** API e contratos existentes.
- Implementar handler/adapter determinístico interno reutilizável **somente onde faltar**; rotas de escrita seguem fail-closed se não houver transporte/credencial/autoridade oficiais.
- Gate: ações internas com estado real ou bloqueio explícito; não usar `FakeFiscalOperationsGateway` em runtime nem alegar emissão fiscal oficial.

### NFV1-BLD-03 — Cadastro de trial do cliente na Web (prioridade comercial)

- Site correto `fm-site-novo` é estático: sua CTA deve chegar a uma página de cadastro hospedada **na aplicação NFCore existente**, ou canal Command S2S canônico aprovado, nunca expor `X-NFCore-Signature` ou segredo no navegador.
- Reutilizar `GovernedTrialService`, pricing/planos, assinatura canônica, geração tenant/OWNER, entrega de ativação, login e expiração; proteção antiabuso, rate-limit, CSRF/origin conforme contrato, idempotência e contra criação duplicada.
- Compor o **binding comercial GSM já criado** pelo endpoint administrativo autenticado; se falta sessão de `platform_admin`, registrar `BLOCKED_HUMAN_ACTION`, prosseguir com o código não dependente. NÃO usar SQL manual ou identidade fabricada.
- Catálogo e `trial_days` reais dependem de aprovação humana de produto; desenvolver parametrizável e provar internamente com fixture sintética, sem publicar oferta falsa.
- Gate: browser → entrada segura → serviço canônico → tenant/OWNER/subscription/activation em banco de teste, sem duplicação, senha/segredo vazado, nem ativar checkout/fiscal.

### NFV1-BLD-04 — Comercial interno: proposta, aquisição, assinatura, cobrança e Command

- Mapear catálogo, release, checkout projection, aquisição, pagamento confirmado via evento **sintético assinado**, fulfillment, provisioning, ativação, upgrade/cancelamento, portal de cobrança, Command service identity e reconciliação.
- Completar somente composição, rotas/portas e telas ausentes; **um** estado canônico de compra/assinatura/tenant, sem cadastro paralelo ou integração de provedor como segunda autoridade.
- Gate: cadeia end-to-end **interna** reproduzível com PostgreSQL descartável e eventos autenticados sintéticos; cobrança real e KYC diferidos.

### NFV1-BLD-05 — Transporte fiscal: código e contratos completos antes da homologação

- Definir matriz técnica mínima de operações do primeiro adapter (sem declarar jurisdição/provedor oficialmente homologados). Auditar gateways/fiscal OperationPath/Signing/CSC/timeout/unknown outcome/cancel/inutilização/consulta.
- Implementar e conectar no adapter **canônico** a infraestrutura determinística, requests/responses normalizados, idempotência, reconciliação/unknown, estados e contratos; para adapter específico que dependa da seleção do provedor, registrar `BLOCKED_HUMAN_DECISION`, não inventar escolha.
- Gate: unit/integration/contract tests com fixtures e transport fake **somente nos testes**; contrato de provider fiscal real pronto para credencial/homologação posterior. Se não existe um adapter de provedor selecionado, **não** declarar capacidade fiscal externa `CONSTRUCTED_100`.

### NFV1-BLD-06 — Worker e persistência da cadeia interna

- Verificar que operações originadas pela Web chegam às transações, fila/outbox e Worker canônicos; retries/replay e idempotência não duplicam ações; dead-letter/erro aparente na UI quando aplicável.
- Corrigir lacunas de ligação; não exigir dispatch externo real, backup periódico de staging ou observabilidade de produção para declarar **construção**.
- Gate: ensaio em PostgreSQL descartável com efeitos internos reais e fronteira externa simulada explicitamente; nenhum processamento sem identidade autorizada.

### NFV1-BLD-07 — Integração site FM novo × NFCore, sem frontend paralelo

- `fm-site-novo` aponta para Portal existente, mas **ainda não oferece trial público operacional**. Ligar CTA de trial somente após endpoint seguro governado de BLD-03 e readiness de oferta; preservar URL estática sem chaves.
- Garantir jornadas login, trial, ativação e retorno à Web; estados sem oferta publicada permanecem claros, não botão que promete cadastro inexistente.
- Gate: teste navegador ponta a ponta da ligação entre aplicações com backend autorizado; cada modificação no site novo requer branch/PR/CI **no repositório correto**, não no legado.

### NFV1-BLD-08 — Fechamento de construção/integridade e handoff

- Reauditar matriz BLD-00 + resultados BLD-01..07 na `main` e no Web provisório quando publicação especificamente autorizada; por componente classificar `DONE_CODE`, `INTEGRATED_NOT_DEPLOYED`, `BUILD_DONE_WEB_DEMO` ou `BLOCKED_HUMAN_DECISION`.
- Exigir que nenhuma lacuna `MISSING_CODE` ou `IMPLEMENTED_NOT_WIRED` do **escopo V1** permaneça. Executar gates internos CI/segurança/isolamento, frontend/build, integração PostgreSQL e E2E **funcional**, sem confundir com homologação/certificação **externa**.
- Encerrar construção **apenas** quando `CONSTRUCTION_AND_WEB_INTEGRATION_COMPLETE` tiver prova de jornada Web por função; se input humano de plano/provedor impedir exercício real, registrar `READY_AWAITING_CONFIGURATION` e pedir decisão pontual. Nada de `100%` por contagem de PR.

## 5. Protocolo de execução autônoma aprovado

1. Antes de **cada** bloco: conferir `main`/SHA, PRs, CI, diff e runtime, ler ledger BUILD; classificar o que existe; trabalhar no **primeiro bloco ainda não concluído**, exceto subtarefas independentes de código documentadas quando predecessor bloqueado por decisão externa/humana.
2. Autorização **permanente apenas neste anexo BUILD-ONLY**: implementar correções dentro do escopo aprovado, abrir/atualizar PR Draft, corrigir falhas, e **realizar merge sem novo pedido** quando HEAD exato mergeable, CI integral e Governança SUCCESS, revisão de segurança/impacto completa, sem blocker de decisão humana e sem testes desabilitados. Marcar Ready antes do merge. Após merge checar CI/Gov da main, tratar qualquer regressão antes de avançar.
3. Se vermelho: **não mergear**; corrigir a causa, reexecutar checks do SHA corrigido, prosseguir somente depois de verde. Falha de runner/conta não é PASS e deve ser registrada; não remover checks obrigatórios nem usar bypass de branch protection.
4. Se código já estiver implementado e testado, **registrar evidência**, não escrever novamente. Nenhum PR somente para repetir certificação ou rodar os mesmos testes sem alteração.
5. **Aprovação humana específica continua obrigatória** para: definição de preços e dias de trial, seleção contratual de provedor, criação/rotação de segredos reais, credenciais reais, gasto, nova política de segurança, migração de schema no banco compartilhado/produtivo, deploy/mudança de infraestrutura, DNS, mudança de visibilidade, acesso fiscal oficial, pagamentos reais, promoção definitiva e qualquer operação irreversível. **A autorização de merge não autoriza deploy.**
6. Sem dados de clientes reais no estágio de construção atual; dados de testes são sintéticos. Backup e restore pontuais **já foram comprovados**; P09-T04 rotina, P05-T05 rollback rehearsal e operação 24×7 **deferidos** para a etapa adequada, sem bloquear BUILD.
7. Ao concluir PR: registrar no ledger BUILD `PR, head, merge SHA, CI/Gov PR e pós-merge, delta funcional, evidência de UI/DB quando aplicável, blockers e próximo bloco`. Estado só muda depois dos comprovantes.
8. Nunca alterar o ledger de 59 tarefas para marcar `DONE` por avanço de BUILD; manter certificação externa/produção nas fases originais.

## 6. Fila futura separada — NÃO EXECUTAR COMO BUILD

- P05-T03/T04/T05: ensaios e certificação operacional externos restantes, reuso de evidências de login, recovery, DB e worker; T05 rollback real diferido.
- P08: cobrança, webhook, pagamento, KYC, renovação e chargeback **reais**.
- P09-T04/T05: rotina de backup/recovery, RPO/RTO, retenção, alertas e runbooks definitivos; não repetir restore já provado sem regressão.
- P10: homologação fiscal oficial e pilotos.
- P11: infraestrutura definitiva, DNS/TLS e promoção.
- P12: certificações finais A–E e Go/No-Go.
- P07 técnica de adapter pode avançar internamente via BLD-05, mas o **gate externo do P07** não recebe `DONE` por simulação.

## 7. Resultado esperado

`CONSTRUCTION_AND_WEB_INTEGRATION_COMPLETE` é marco **interno de construção funcional demonstrada**. Não significa `PRODUCTION_APPROVED`, `COMMERCIAL_LIVE` ou homologação fiscal. O cronograma mestre de 59 tarefas permanece em execução, com seus gates externos preservados e sem exigir repetição de etapas já comprovadas.


## 8. Decisão posterior do Diretor — NFV1-BLD-09 Core Cognitivo Vertical V1 (31/10/2026)

**Novo requisito obrigatório para fechamento da V1: Core Cognitivo Vertical consultivo**, sem engine próprio, usando backend central FM/Command, identidades server-side governadas, Vault/Secret Reference, escopo tenant/unidade, RBAC, minimização, cota por entitlement, proveniência e IA advisory (nunca execução fiscal). Este bloco **não integra o escopo aprovado em 18/10**, cuja lista histórica BLD-00..08 é preservada; foi **adicionado por decisão expressa posterior**, sem reabrir blocos certificados nem alterar os 59 IDs do cronograma mestre. O texto histórico “NFCORE V2 cognitive architecture remains outside this V1 closure” fica superado **neste ponto de escopo**. O piloto operacional de 02/11 é independente.

**Plano detalhado e ordem de trabalho:** [`NFV1_BLD09_COGNITIVE_CORE_V1_DESIGN_2026-10-31.md`](NFV1_BLD09_COGNITIVE_CORE_V1_DESIGN_2026-10-31.md), T01 contrato S2S → T02 Context Pack → T03 porta/adapter central → T04 rejeições → T05 CST/cClassTrib/NCM consultivos → T06 conciliação/dúvidas → T07 entitlement/uso/custos → T08 gates E2E. **Estado: PENDING_IMPLEMENTATION / proposta documental, sem autorização para deploy, credencial, migração, mudança de produção ou declaração de GO.** Gate BLD-08 de construção fiscal/Web não certifica automaticamente o BLD-09.
