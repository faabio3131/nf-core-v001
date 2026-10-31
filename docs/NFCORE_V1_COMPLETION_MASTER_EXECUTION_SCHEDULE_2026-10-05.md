# FM NFCORE V1 — CRONOGRAMA MESTRE DE CONCLUSÃO E CERTIFICAÇÃO

> **Decisão posterior aprovada (18/10/2026) — execução BUILD-ONLY antes de homologação externa:** `docs/NFCORE_V1_BUILD_INTEGRATION_EXECUTION_2026-10-18.md` é o **anexo subordinado de execução** para concluir **código e integração na mesma Web** sem reabrir fases internas certificadas. Seu estado/provas estão em `docs/NFCORE_V1_BUILD_INTEGRATION_LEDGER.md`, com governança em `AGENTS.md`. Isto **não acrescenta, renumera nem encerra** nenhum dos 59 itens deste mestre; a precedência interna BLD não transforma P05/P07/P08/P09/P10/P11/P12 em DONE. A homologação fiscal e comercial real, operações finais, backups periódicos e produção permanecem pendentes e ocorrerão no momento próprio. Autorização de merge automático **somente** para PRs BUILD-ONLY inteiramente verdes, não para deploy, gasto, credenciais, DNS ou operações irreversíveis.


**Status:** CANONICAL EXECUTION CONTROL CANDIDATE  
**Data-base da auditoria:** 2026-10-05  
**Projeto:** NFCore Commercial Launch  
**Produto:** FM NFCORE V1  
**Repositório canônico:** faabio3131/kordena-fiscal-engine-v2  
**Branch canônica:** main  
**CURRENT auditado:** 0644901ac0816b9bf8f12c648d010418486a6483  
**CI do CURRENT:** FM NFCORE V1 CI #566 — SUCCESS  
**PRs abertas no momento da auditoria:** 0

**Objetivo:** concluir o FM NFCORE V1 de forma comprovável, sem reconstruções paralelas, fases esquecidas ou promoção indevida de código preparado para estado operacional.  
**Padrão automatizado de execução:** `docs/standards/FM_AI_MASTER_PLAN_EXECUTION_STANDARD.md` + `docs/NFCORE_V1_EXECUTION_LEDGER.md` + `scripts/check_nfcore_plan.py`.

> Este documento governa as pendências identificadas na auditoria completa de 2026-10-05. Para a execução pós-auditoria, ele prevalece sobre cronogramas históricos quando houver divergência de estado. Documentos históricos permanecem como evidência, mas não substituem o CURRENT técnico.

---

# 1. REGRA CONSTITUCIONAL DE EXECUÇÃO

A linha obrigatória é:

~~~text
AUDITORIA CURRENT
 -> DESIGN / DECISÃO
 -> IMPLEMENTAÇÃO
 -> TESTES
 -> GATES
 -> PR
 -> CI DA PR
 -> EVIDÊNCIA
 -> MERGE QUANDO AUTORIZADO
 -> CI DA MAIN
 -> DEPLOY CONTROLADO
 -> EVIDÊNCIA DE RUNTIME
 -> CERTIFICAÇÃO
 -> PRÓXIMO BLOCO
~~~

Nenhuma fase pode ser considerada concluída porque um arquivo, classe, rota, teste, harness, UI ou documento existe. Conclusão exige evidência reproduzível da camada correspondente.

---

# 2. FONTES DE VERDADE

Ordem obrigatória em cada retomada:

1. código CURRENT no Git/GitHub;
2. branch, HEAD, PRs, merges e main;
3. CI, testes, builds e evidências reproduzíveis;
4. este cronograma e NFCORE_V1_COMMERCIAL_LAUNCH_CURRENT.md;
5. ADRs, System Design e certificações anteriores;
6. documentação histórica;
7. conversa/memória somente como contexto.

Antes de qualquer alteração:

- [ ] reconfirmar main;
- [ ] reconfirmar HEAD;
- [ ] listar PRs abertas;
- [ ] validar CI do HEAD;
- [ ] verificar staging real;
- [ ] verificar drift main x ambientes;
- [ ] identificar a autoridade canônica;
- [ ] declarar CURRENT -> TARGET;
- [ ] congelar escopo;
- [ ] definir mapa de impacto;
- [ ] definir critérios de aceite;
- [ ] definir testes;
- [ ] registrar ações proibidas no bloco.

---

# 3. VOCABULÁRIO DE STATUS — USO OBRIGATÓRIO

| Status | Significado |
|---|---|
| NOT_STARTED | trabalho ainda não iniciado |
| READY_TO_START | predecessores certificados |
| IN_PROGRESS | implementação/teste em andamento |
| BLOCKED_INTERNAL | depende de correção ou decisão técnica interna |
| BLOCKED_EXTERNAL | depende de terceiro, credencial, homologação, conta, DNS, certificado ou provider |
| IMPLEMENTED_NOT_INTEGRATED | código existe, mas não está ligado à linha operacional canônica |
| INTEGRATED_NOT_DEPLOYED | integração está na main, mas não no ambiente-alvo |
| DEPLOYED_NOT_CERTIFIED | implantado sem matriz de evidência concluída |
| DONE_CERTIFIED | critérios de aceite, testes, CI, evidência e integração concluídos |

É proibido usar “pronto”, “100%”, “finalizado”, “homologado”, “produção” ou “live” sem classificação e evidência.

---

# 4. CURRENT CONFIRMADO NA AUDITORIA DE 2026-10-05

## 4.1 Repositório e qualidade

- main: 0644901ac0816b9bf8f12c648d010418486a6483;
- PRs abertas: 0;
- CI #566: SUCCESS;
- Ruff: PASS;
- Mypy: 0 issues em 178 source files;
- Pytest: 1099 PASS / 0 FAIL;
- frontend tests: 11;
- Playwright: 7 PASS;
- secret scan: PASS;
- Python dependency audit: sem vulnerabilidades conhecidas;
- Node dependency audit: 0 vulnerabilidades;
- containers API/Worker/Portal: build PASS;
- imagens non-root: PASS;
- PostgreSQL backup/restore CI: PASS;
- readiness sobre DB restaurado: PASS;
- SBOM: gerado.

## 4.2 Staging real

Projeto Railway: FM NFCORE Staging.

| Componente | Revisão auditada |
|---|---|
| main CURRENT | 0644901ac0816b9bf8f12c648d010418486a6483 |
| API staging | f9b5b2c5b436045947159f1e76be9303f5a95d90 |
| Portal staging | f9b5b2c5b436045947159f1e76be9303f5a95d90 |
| Worker staging | 1c34ba001935952f83ec0b065144e0b8311a5650 |

PostgreSQL, API e Portal existem no staging. O Worker existe como serviço, mas não está comprovado como processo contínuo operacional.

Classificação:

STAGING_REAL / VERSION_DRIFT_PRESENT / NOT_CERTIFIED_AGAINST_CURRENT

## 4.3 Gaps estruturais confirmados

1. motor fiscal existe, mas o runtime oficial não injeta BridgeSecurityBoundary e BridgeRequestExecutor;
2. PortalOperationExecutor não está composto no app oficial;
3. superfícies Web estão descritas, mas várias não estão disponíveis no executor durável;
4. aquisição, trial e webhook Cakto existem, mas não estão compostos no runtime padrão;
5. worker contínuo exige handler_factory, mas o entrypoint oficial não o fornece;
6. provider fiscal real não existe; há fake/synthetic;
7. secret manager concreto não existe; há boundary provider-neutral;
8. tracing/exporters operacionais não estão ativos;
9. homologação fiscal oficial não existe;
10. produção NFCore não está comprovada;
11. canal comercial real não foi certificado;
12. documentação CURRENT histórica está parcialmente defasada.

---

# 5. REGRAS ANTI-ERRO E ANTI-ESQUECIMENTO

## Diretriz transversal aprovada — configuração externa — 2026-10-08

O dono confirmou que credenciais, APIs e parâmetros de integrações externas
devem ser configuráveis. Para providers já suportados, contratar ou configurar
um novo cliente não pode exigir alteração de código nem novo deploy.

- Adapters, contratos e validações permanecem no código; contas, ambientes,
  bindings, parâmetros permitidos e referências de credenciais são configuração
  governada, versionada e auditada pelas autoridades existentes.
- Segredos, certificados, tokens e chaves reais não entram em Git, logs ou
  respostas de leitura. A persistência canônica guarda referências/metadados;
  o material secreto pertence ao backend seguro, com resolução efêmera.
- Configuração do cliente respeita tenant/unidade/ambiente/purpose/version e
  RBAC existentes. Credenciais da plataforma não são administradas pelo tenant.
- Configuração incompleta, inválida, expirada ou revogada bloqueia a operação
  dependente. A UI mostra o bloqueio; não promove readiness sem prova.
- Rotação/revogação deve ser aplicada pelo mecanismo governado de configuração,
  sem editar código por cliente. Endpoints/destinos continuam sujeitos à política
  de egress/SSRF aprovada; configurável não significa URL arbitrária permitida.
- Novo provider pode exigir um adapter novo. Após suportado, sua adoção por
  clientes ocorre por configuração. Configurabilidade não substitui validação
  de conectividade, credenciais e homologação externa por escopo.

Esta diretriz rege os critérios das tarefas existentes de configuração,
comercial, secrets e providers; não altera a ordem do ledger nem declara essas
capacidades já implementadas ou homologadas.

## 5.1 Dependência obrigatória

Ordem vigente em `main` antes desta proposta (2026-10-09): P0, P1, P2, P3, P4, P6, P5, P7, P8, P9, P10, P11, P12. **Proposta sujeita a decisão/merge:** P0, P1, P2, P3, P4, P6, **P09-T01→T03 (somente construção interna)**, P5, P7, P8, P09-T04→T05, P10, P11, P12. P6 usa a infraestrutura staging existente para certificar o backend concreto; P5 só retoma depois do gate P6. Cada tarefa segue o ledger, com seus gates e autorizações próprias. A mudança remove o ciclo de dependência P5/P6 e não dispensa pendências de P5.

Fases paralelas somente podem ocorrer quando não mascaram blocker anterior.

## 5.2 Toda mudança precisa de ID

Formato obrigatório: NFV1-Pxx-Tyy.

Nenhuma pendência descoberta durante execução pode ficar somente no chat. Deve ser resolvida, registrada como tarefa, registrada como blocker ou rejeitada explicitamente com justificativa técnica.

## 5.3 Zero pendência invisível

Ao terminar cada fase, varrer:

- [ ] TODO/FIXME/HACK relevante;
- [ ] rota sem composição;
- [ ] frontend referenciando superfície indisponível;
- [ ] configuração sem runtime;
- [ ] serviço em SHA divergente;
- [ ] teste pulado relevante;
- [ ] feature flag provisória;
- [ ] mock/synthetic em caminho real;
- [ ] configuração manual não documentada;
- [ ] runbook ausente;
- [ ] evidência externa faltante;
- [ ] observabilidade ausente;
- [ ] rollback não provado.

Uma caixa [x] só pode ser marcada com evidência correspondente.

---

# 6. CRONOGRAMA MESTRE

# P0 — RECONCILIAÇÃO DE GOVERNANÇA E CURRENT

**Status inicial:** READY_TO_START

**Status certificado em 2026-10-05:** DONE_CERTIFIED

## Objetivo

Eliminar divergência documental e fixar um ponto de partida único.

## Tarefas

### NFV1-P00-T01 — Reconciliar documentação CURRENT

- atualizar NFCORE_V1_COMMERCIAL_LAUNCH_CURRENT.md;
- registrar a auditoria de 2026-10-05;
- apontar este cronograma como controle de execução;
- preservar histórico sem convertê-lo em CURRENT.

### NFV1-P00-T02 — Congelar matriz de capacidades

Criar matriz:

capacidade -> domínio -> application -> infra -> persistence -> API -> auth/RBAC -> tenant/unit -> Web -> tests -> CI -> staging -> production.

### NFV1-P00-T03 — Registrar staging drift

Persistir main SHA, API SHA, Portal SHA, Worker SHA, banco/migrations, domínios e runtime status.

## Gate

- [x] documentação coincide com Git/Railway;
- [x] matriz de capacidades existe;
- [x] blockers conhecidos possuem IDs.

**Gate de saída:** CURRENT_RECONCILED_2026_10_05

---

# P1 — PRODUCTION FISCAL COMPOSITION ROOT

**Status inicial:** READY_TO_START após P0  
**Prioridade:** CRÍTICA

## Objetivo

Conectar o motor fiscal existente à aplicação Web/runtime canônica sem criar segunda API ou segundo domínio.

## CURRENT

Existem contratos de emissão, consulta, cancelamento, inutilização, reconciliação, Provider Gateway, authorization boundary, production activation authority, signing, persistence e rotas HTTP. O app padrão não injeta os executores/segurança necessários.

## TARGET

~~~text
HTTP/API/Portal
 -> authority autenticada
 -> tenant/unit scope
 -> BridgeSecurityBoundary
 -> PortalOperationExecutor / BridgeRequestExecutor
 -> application/domain fiscal existente
 -> provider registry
 -> persistence/audit
~~~

## Tarefas

### NFV1-P01-T01 — Identificar composição canônica

- localizar executores válidos;
- impedir executor paralelo;
- mapear signing/provider/vault/production authority.

### NFV1-P01-T02 — Implementar composition root

- injetar BridgeSecurityBoundary;
- injetar BridgeRequestExecutor;
- injetar PortalOperationExecutor;
- preservar fail-closed;
- não habilitar produção fiscal automaticamente.

### NFV1-P01-T03 — Certificar autoridade

Testar tenant spoofing, unit spoofing, cross-tenant, cross-unit, RBAC, sessão, S2S e idempotência.

### NFV1-P01-T04 — Certificar API fiscal

Validar emissão, consulta, cancelamento, inutilização, reconciliação e demais operações do launch scope.

## Gate

- [ ] dependências internas compostas;
- [ ] ausência de provider/secret/produção continua fail-closed;
- [ ] UI não é autoridade;
- [ ] testes unit/integration/security verdes;
- [ ] CI completo verde.

**Gate de saída:** FISCAL_RUNTIME_COMPOSED_AND_CERTIFIED_INTERNAL

---

# P2 — PORTAL FUNCTIONAL PARITY

**Status inicial:** NOT_STARTED  
**Dependência:** P1

**Status interno certificado em 2026-10-08:** DONE_CERTIFIED condicionado ao
merge/gates completos do closeout T07. Evidência PR #131, CI #676/#677 e
Governance #97/#98 SUCCESS; checkpoint
`checkpoints/NFV1_P02_T07_CLOSEOUT_2026-10-08.md`. Não certifica staging,
provider/secret fiscal real, homologação ou produção.

## Objetivo

Expor no mesmo Portal as capacidades necessárias ao V1, reutilizando autoridades existentes.

## Superfícies a fechar

- Documentos;
- Emissões;
- Erros;
- Reconciliação;
- Capabilities;
- Certificados;
- Providers;
- Usuários;
- Webhooks;
- Integrações;
- Uso;
- Billing;
- Planos;
- Suporte;
- Inutilização.

## Tarefas

### NFV1-P02-T01 — Matriz frontend x backend

Para cada superfície registrar authority, endpoint, projection, mutações, RBAC, tenant/unit, estados e audit trail.

### NFV1-P02-T02 — Superfícies fiscais

Conectar documents, issuances, errors, reconciliation e capabilities.

### NFV1-P02-T03 — Configuração do cliente

Conectar certificates, providers, webhooks, integrations e settings sem expor secrets.

### NFV1-P02-T04 — Usuários e RBAC

Implementar administração baseada na autoridade humana existente e testar OWNER, ADMIN, OPERATOR, AUDITOR, BILLING e platform admin.

### NFV1-P02-T05 — Billing/Planos/Uso

Expor estado canônico, mantendo provider externo como adapter.

### NFV1-P02-T06 — Inutilização

Adicionar operação ao fluxo Web governado.

### NFV1-P02-T07 — Premium UX

Preservar identidade, mobile, acessibilidade e estados reais de bloqueio.

## Gate

- [x] nenhum item visível aponta para superfície inexistente;
- [x] mutações usam controles exigidos;
- [x] RBAC e tenant/unit validados;
- [x] Playwright cobre jornadas críticas;
- [x] visual premium preservado;
- [x] CI verde.

**Gate de saída:** PORTAL_COMMERCIAL_PARITY_CERTIFIED

---

# P3 — COMMERCIAL RUNTIME WIRING

**Status inicial:** NOT_STARTED  
**Dependência:** P1

**Certificação interna em 2026-10-08:** DONE_CERTIFIED condicionada à integração/gates do fechamento T05. PR #141 MERGED, CI #708/#709 e Governance #129/#130 SUCCESS; checkpoint `checkpoints/NFV1_P03_T05_IMPLEMENTATION_2026-10-08.md`. Não certifica integrações externas reais, staging ou produção.

## Objetivo

Conectar os componentes comerciais já construídos ao runtime real.

## Tarefas

### NFV1-P03-T01 — First-party acquisition

Compor CommercialAcquisitionService, security, rate limit, pricing, release, checkout, persistence e activation readiness.

### NFV1-P03-T02 — Trial

Compor GovernedTrialService, security, anti-abuse, rate limit, activation delivery e canonical subscription.

### NFV1-P03-T03 — Provider webhook runtime

Quando Cakto for selecionada, resolver secret por boundary governada, compor receiver, autenticar assinatura, registrar inbox, traduzir evento canônico e acionar fulfillment/provisioning/activation.

Reconciliar com a decisão vigente do dono: pagamentos da FM centralizados no Command. O canal de lançamento deve receber eventos comerciais autenticados do Command, mantendo gateways como adapters no Command e reutilizando autoridades comerciais locais. Segurança do binding/contrato proposta em `NFV1_P03_T03_COMMAND_POLICY_PROPOSAL_2026-10-08.md`; T03-B01 resolvido: política integral aprovada explicitamente pelo dono em 2026-10-08 (POLICY_APPROVED_FOR_INTERNAL_IMPLEMENTATION); implementação interna e testes autorizados. Posteriormente, o dono autorizou especificamente o merge da PR #137 e a validação pós-merge; deploy permanece não autorizado. Não altera IDs ou ordem; não ativa Cakto por inferência.

### NFV1-P03-T04 — Purchase readiness

purchase_enabled deve permanecer falso se faltar pricing, release, checkout, receiver, canonical persistence, fulfillment, provisioning ou activation delivery.

Auditoria de retomada em 2026-10-08 confirmou gap de receiver/binding na oferta. T04-B01 registrado em `NFV1_P03_T04_PURCHASE_READINESS_POLICY_PROPOSAL_2026-10-08.md`: política proposta de revalidação governada e fail-closed, incluindo nova origem de acesso ao resolver de segredos. Política integral aprovada pelo dono em 2026-10-08 (POLICY_APPROVED_FOR_INTERNAL_IMPLEMENTATION); publicação dos três documentos e PR Draft autorizadas. Implementação/testes internos permitidos; merge/deploy/operação real não autorizados; certificação T04 pendente. IDs, ordem e critério original preservados.

**Certificação interna em 2026-10-08:** PR #139 MERGED por autorização específica; main `4c179ad59e61b66eaca3235488705d0d33316412`, árvore idêntica ao HEAD certificado. CI #698 (PR)/#699 (main) e Governance #119/#120 SUCCESS;41/41 etapas;1536 Python/PostgreSQL,14 frontend,28 Playwright PASS/zero FAIL/zero SKIP. Este registro prevalece sobre a pendência histórica acima. Checkpoint final no mesmo documento da política; continuidade T05 condicionada à integração/gates do fechamento documental. Não certifica Secret Manager, emissor Command, checkout ou delivery reais, staging, homologação ou produção. Deploy não autorizado.

### NFV1-P03-T05 — Lifecycle comercial

Cobrir sale, activation, renewal, late payment, pause, recovery, cancel, refund e chargeback.

Auditoria T05 em 2026-10-08: transições existem, mas renovação não avança período da assinatura; política comercial T05-B01 proposta em `NFV1_P03_T05_LIFECYCLE_POLICY_PROPOSAL_2026-10-08.md`. T05-B01 RESOLVIDO: conjunto integral aprovado explicitamente pelo dono (“Aprovo”) em 2026-10-08, POLICY_APPROVED_FOR_INTERNAL_IMPLEMENTATION. Período pago, carência, invoice deduplicada e quotas periódicas autorizados para implementação/testes internos. T05 em execução, não concluída; IDs/ordem/escopo preservados. Merge/deploy/operação real não autorizados.

**Certificação T05:** merge #141 autorizado especificamente pelo dono (“Aprovado”); main `b8b25fda37a6682bc57eb2349f132770e46b0362`, árvore idêntica à PR. CI #708 (PR)/#709 (main), Governance #129/#130 SUCCESS;41/41 etapas;1571 Python/PostgreSQL,14 frontend,28 Playwright PASS/zero FAIL/zero SKIP. Este registro prevalece sobre pendências históricas acima. Continuidade P4 condicionada à integração/gates do fechamento documental; deploy não autorizado.

## Gate

- [x] acquisition endpoint real registrado;
- [x] trial endpoint real registrado;
- [x] webhook somente quando configurado;
- [x] browser nunca define pagamento/tenant/entitlement;
- [x] replay não duplica org/OWNER/subscription;
- [x] CI verde.

**Gate de saída:** COMMERCIAL_RUNTIME_COMPOSED_INTERNAL

---

# P4 — CONTINUOUS WORKER RUNTIME

**Status inicial:** NOT_STARTED  
**Dependência:** P3

**Certificação interna em 2026-10-09:** DONE_CERTIFIED condicionada à integração/gates do fechamento T04. PR #149 MERGED, CI #725/#726 e Governance #146/#147 SUCCESS; checkpoint `checkpoints/NFV1_P04_T04_WORKER_CONTAINER_2026-10-09.md`. Processo/container real de CI certificado; assinatura/secret backend/delivery reais e staging permanecem P6/P5/P9/P11.

## Objetivo

Transformar Worker de probe em processo operacional contínuo governado.

## Tarefas

### NFV1-P04-T01 — Handler registry canônico

Identificar handlers existentes, compor registry explícito e não criar fila paralela.

Retomada em 2026-10-09: P3 fechada na PR #142, main `4c3838f0c35e728f36f9c15ac1c3f62c42cd35d2`, CI #711/Governance #132 SUCCESS. T01 em execução. Reutilizar SignedWebhookOutboxHandler, aprovação/destino duráveis, egress/transport existentes e a mesma outbox/UOW; registry explícito ligado ao entrypoint por dependências canônicas injetadas. Ausência de assinatura/configuração falha antes do poll; não inventar handlers fiscais/comerciais ou resolver externo P6. T02/T03/T04 não antecipadas; sem deploy.

Certificação interna T01 em 2026-10-09: PR #143 MERGED; HEAD `1d0dcc17b7d18016d5060ff2e3fd0c88aedd81b0`; main `d1007064c6997a0c303ae09e606e565e04ab1677`; árvore PR/main idêntica `dd82679dff6c59ee40dc14a96d6503ebc12122b2`. CI #713/run37879189354 (PR) e #714/run37880543365 (main), Governance #134/run37879189376 e #135/run37880543403 SUCCESS. PR/main:41/41 etapas,1587 Python/PostgreSQL,14 frontend,28 Playwright PASS,zero FAIL/zero SKIP;16 novos casos incluídos; warning TestClient existente. Inventário e registry canônico concluídos; nenhuma fila paralela. Fechamento documental aguarda integração/gates próprios; próxima tarefa T02 não iniciada. P4 ainda não concluída, dependência de assinatura real P6 e runtime/staging P5/P9/P11 não certificados.

### NFV1-P04-T02 — Outbox/inbox/background

Provar poll/dispatch, retry, backoff, idempotência, dead-letter, shutdown, restart e replay seguro.

Retomada T02 em 2026-10-09: main `8385be0ee80e434a922e9ad10b11a4f15c2188db`, PR #144 MERGED, CI #716/Governance #137 SUCCESS. T02 em execução por “Executar”. Matriz SQLite/PostgreSQL e comparação atômica de status/attempt na escrita da outbox; reutiliza inbox/auditoria/UOW/worker. Transporte at-least-once, deduplicação externa não presumida. Checkpoint `checkpoints/NFV1_P04_T02_WORKER_RECOVERY_2026-10-09.md`. T03/T04 não antecipadas; sem deploy.

Certificação interna T02 em 2026-10-09: PR #145 MERGED; HEAD `49201706c1b6ad80d128aaa788827b64ab1d63e7`; main `4e5657cfda9cd89d03fec1d3e2b1471f79b36b2b`; árvore PR/main idêntica `41f72f38660ac1c1d6611c7c99251d265deff0d3`. CI #717/run37883903575 (PR) e #718/run37885060792 (main), Governance #138/run37883903581 e #139/run37885060691 SUCCESS. PR/main:41/41 etapas;1605 Python/PostgreSQL,14 frontend,28 Playwright PASS,zero FAIL/zero SKIP;18 novos casos incluídos; um warning TestClient existente. Comparação atômica no UPDATE e matriz de recuperação aprovadas pelos gates. Este registro prevalece sobre T02 em execução acima; fechamento documental aguarda integração/gates próprios. Próxima T03 não iniciada. P4 não concluída; T03/T04, assinatura real P6 e staging P5/P9/P11 permanecem pendentes.

### NFV1-P04-T03 — Observabilidade do Worker

Medir backlog, jobs processados, falhas, retry, dead-letter e heartbeat/readiness.

Retomada T03 em 2026-10-09: main `ee0c14cf0979561bc20f655fd71819552f67bbdf`, PR #146 MERGED, CI #720/Governance #141 SUCCESS. T03 em execução por “Pode iniciar”. Reader agregado da outbox, gauges/contadores, heartbeat monotônico/readiness fresco e isolamento de callback do observer, reutilizando loop/UOW/metrics/logger. Checkpoint `checkpoints/NFV1_P04_T03_WORKER_OBSERVABILITY_2026-10-09.md`; sem exporter/endpoint novo ou deploy. T04/P9 não antecipadas.

Certificação interna T03 em 2026-10-09: PR #147 MERGED; HEAD `86d144e02c29a7a7881dd1a1afeaaa57b36e08ed`; main `f844aae44bbcc2a240071b269293a1c59f867c36`; árvore PR/main idêntica `561003d239901a6fbae83daa9587c627f89b493e`. CI #721/run37916736004 (PR) e #722/run37918229115 (main), Governance #142/run37916736047 e #143/run37918229137 SUCCESS. PR/main:41/41 etapas;1637 Python/PostgreSQL,14 frontend,28 Playwright PASS,zero FAIL/zero SKIP;32 novos casos incluídos; um warning TestClient preexistente. Backlog/estados/resultados/falhas/retry/dead-letter e heartbeat/readiness medidos na composição canônica; telemetry isolada de commits/processamento. Este registro prevalece sobre T03 em execução acima; fechamento documental aguarda integração/gates próprios. Próxima T04 não iniciada. P4 não concluída; container contínuo T04, assinatura real P6 e staging/monitoramento P5/P9/P11 permanecem pendentes. Sem exporter/endpoint/deploy ou operação real.

### NFV1-P04-T04 — Container

Provar processo contínuo, SIGTERM, non-root e health/runtime contract.

Retomada T04 em 2026-10-09: main `f1b8503cb8dd09325457907469ec5f049d9d5579`, PR #148 MERGED, CI #724/Governance #145 SUCCESS. T04 em execução por “Pode fazer”. Corrigir parada durante bootstrap; probe privado usa saúde canônica T03; provar PID1/non-root/continuidade/SIGTERM/drain/restart no container CI, preservando ONESHOT e falha sem handlers. Checkpoint `checkpoints/NFV1_P04_T04_WORKER_CONTAINER_2026-10-09.md`; sem deploy/segredo/handler sintético em produção. P5/P6/P9 não antecipadas.

Certificação interna T04 em 2026-10-09: PR #149 MERGED; HEAD `732265ed0e7bab21b48e735ea296a2e8a3af7576`; main `d9f4d1d8c7fd60f927b2f3d3ba8f421a72c9bf82`; árvore PR/main idêntica `d7cbdf8baf65013c4f8542ac390c9c581b01ef7b`. CI #725/run37935705861 (PR) e #726/run37938638870 (main), Governance #146/run37935705764 e #147/run37938638865 SUCCESS. PR/main:41/41 etapas;1666 Python/PostgreSQL,14 frontend,28 Playwright PASS,zero FAIL/zero SKIP;29 novos casos incluídos;um warning TestClient preexistente. Container real:SIGTERM exit0,readiness inválida durante drain,10 claimed concluídos+3 pending,restart13/13,um attempt/audit sem replay terminal. Este registro prevalece sobre T04 em execução acima; fechamento documental aguarda integração/gates próprios.23/59 concluídas; próxima P05-T01 não iniciada. Sem deploy ou operação externa.

## Gate

- [x] Worker permanece executando sem modo oneshot;
- [x] handler registry explícito;
- [x] retry/dead-letter certificado;
- [x] crash/restart testado;
- [x] side effects idempotentes;
- [x] CI verde.

Provas por critério no checkpoint T04: T01 registry; T02 recovery/CAS/inbox; T03 saúde/observabilidade; T04 processo/container. Idempotência certificada no estado interno; transporte at-least-once exige deduplicação do destinatário externo, não presumida. Gate interno condicionado à integração/gates deste fechamento; não certifica Worker staging0/1.

**Gate de saída:** CONTINUOUS_WORKER_CERTIFIED_INTERNAL

---

# P6 — EXTERNAL SECRET MANAGER ADAPTER

**Status inicial:** NOT_STARTED
**Dependências:** P1 + P2 + P3 + P4 certificados internamente; infraestrutura staging existente; autorizações específicas de provider/IAM e operação externa. P5 certificado não é predecessor.

Decisão de ordem aprovada pelo dono em 2026-10-09 (“Autorizado”): antecipar os quatro itens P6 antes de retomar P5. Seleção/conta/custo/IAM/credencial/provider real continuam sujeitos aos gates próprios. P6 não está iniciada ou certificada por este ajuste.

## Objetivo

Ligar ExternalSecretClient a um Secret Manager/Vault concreto sem alterar domínio.

## Tarefas

### NFV1-P06-T01 — Selecionar provider

Critérios: IAM, rotação, disponibilidade, auditoria, custo e recovery.

Execução do estudo T01 autorizada pelo dono em 2026-10-09 (“Pode executar”), após PR #152 integrada e main/CI certificados. Escopo congelado: auditar boundaries existentes, comparar fontes oficiais, preparar recomendação e política de identidade/rotação/recovery/custo para decisão humana, atualizar CURRENT/ledger/checkpoint e publicar PR Draft. T01 não implementa T02 nem provisiona conta/IAM/segredo/deploy. P6-T01-B01: aprovação específica da seleção e política sensível pendente; P6-T01-B02: identidade/bootstrap externo, conta/região/orçamento e evidência real ainda não confirmados. IDs/ordem/gates preservados;23/59 concluídas. Documento da decisão: `docs/NFV1_P06_T01_SECRET_PROVIDER_POLICY_PROPOSAL_2026-10-09.md`.

O dono respondeu “Autorizo” em 2026-10-09 à escolha Google Secret Manager, à política proposta como conjunto (incluindo bootstrap restrito ao staging para implementação interna) e à integração da PR #153. P6-T01-B01 RESOLVIDO: POLICY_APPROVED_FOR_INTERNAL_IMPLEMENTATION. PR #153 MERGED; main `0ad89d68ac7bb7975d8af1422ce07796eaf625ed`, árvore `b1e1ae3b692e2c325cdd9a2536ad84227ec5ee7e` idêntica ao HEAD certificado. CI PR #735/run37958319939 e Governance #156/run37958319968 SUCCESS;41/41 etapas,1673 Python/PostgreSQL,14 frontend,28 Playwright,zero FAIL/SKIP. Main CI #736/run37961104490/job113923850663 e Governance #157/run37961104464 SUCCESS;41/41 etapas,1673 Python/PostgreSQL,14 frontend,28 Playwright PASS/zero FAIL/zero SKIP;um warning TestClient preexistente. Backup/restore canônico PostgreSQL16 sintético e readiness PASS. Seleção/política aprovada e T01 DONE_CERTIFIED internamente, condicionada à integração/gates deste fechamento;24/59 concluídas; fase P6 e provider real não certificados. T02 não iniciada. Checkpoint `docs/checkpoints/NFV1_P06_T01_SELECTION_2026-10-09.md`. Registro posterior prevalece sobre a pendência histórica B01 acima; B02 impede operação externa, não estudo/implementação interna depois do gate T01.

### NFV1-P06-T02 — Implementar adapter de infraestrutura

Nenhuma regra de domínio no adapter.

Execução interna autorizada pelo dono (“Executar”) em2026-10-09 após PR154 MERGED e CI738/Governance159 SUCCESS. Implementar SDKGSM e bindings metadata-only na persistência/UOW canônica, preservar projeções ref:/sec_ e validar contexto antes de I/O;políticaT01 já aprovada. Migration17 aditiva/testes locais eCI sem operação externa. T02 emexecução,não concluída;checkpoint `docs/checkpoints/NFV1_P06_T02_GSM_ADAPTER_2026-10-09.md`;conta/IAM/credencial/deploy dependemB02/autorização própria.

**Certificação interna T02 em2026-10-09:** PR #155 MERGED; HEAD `5eb98614f4dfdc092871bb6e06c1efef7825e6ba`; main `8ad5a20e8ec954ef91f5e2c8f77a17ad09e8e62b`; árvore idêntica `5531ec7f0d7da61c59f92117b08f56807fae8715`. CI #739/run37973027312/job113964215052 (PR), #740/run37978308311/job113982097370 (main), Governance #160/run37973027313 e #161/run37978308448 SUCCESS. PR/main:41/41 etapas;1741 Python/PostgreSQL,14 frontend,28 Playwright PASS/zero FAIL/zero SKIP;um warning TestClient preexistente. Backup/restore PostgreSQL16 sintético, checksum e readiness PASS. Merge autorizado especificamente pelo dono; este registro supera a pendência histórica acima. Implementação concreta de infraestrutura sem regra de domínio, durável e fail-closed; testes sintéticos internos não comprovam cloud real. Checkpoint `docs/checkpoints/NFV1_P06_T02_GSM_ADAPTER_2026-10-09.md`. T02 DONE_CERTIFIED internamente, condicionado à integração/gates deste fechamento.25/59 concluídas;T03 não iniciada;B02 externo permanece;gateP6 eP5 bloqueados;sem deploy.

### NFV1-P06-T03 — Certificar escopo

Tenant, unidade, ambiente, provider, purpose, version e expiration.

**DONE_CERTIFIED interno em 2026-10-10:** PR #157 MERGED (`1f5ec590104c5819173196b7d6dc56e58a2f3a53`); CI #743 (PR) e #744 (main), Governance #164 e #165 SUCCESS. Pós-merge: 41/41 etapas, 1.937 Python/PostgreSQL, 14 frontend e 28 Playwright PASS, zero FAIL/zero SKIP. 196 novos casos de escopo, checkpoints e regressões em `tests/vault/test_p06_t03_scope_certification.py` e `docs/checkpoints/NFV1_P06_T03_SCOPE_CERTIFICATION_2026-10-10.md`. 26/59 tarefas concluídas internamente; próxima T04 não iniciada neste closeout. **P6-T01-B02 permanece BLOCKED_EXTERNAL**: conta/IAM/bootstrap/acesso efetivo Google Secret Manager não certificados. Gate externo P6 não cumprido; sem deploy, cloud real, credencial ou operação fiscal. PRODUCTION_APPROVED=NO; COMMERCIAL_LIVE=NO.

### NFV1-P06-T04 — Rotação e falha

Testar missing, revoked, expired, permission denied, backend unavailable e rotation.


**Fechamento interno T04 — 2026-10-10:** PR #159 MERGED; `main` `d2600c6a6604d9f3f8be3ea3642b78ebbf688832`; CI #747 (PR), #748 (main), Governance #168/#169 SUCCESS, pós-merge 41/41 etapas: 2.022 Python/PostgreSQL, 14 frontend e 28 Playwright PASS, zero FAIL/zero SKIP (um warning TestClient). 85 casos novos cobrindo as classes signature/certificate/csc/credentials, SQLite/PostgreSQL, falhas, rotação e concorrência. **NFV1-P06-T04 DONE_CERTIFIED_INTERNAL**; 27/59 tarefas concluídas após fechamento documental. Não confundir com `EXTERNAL_SECRET_BACKEND_CERTIFIED`: **gate P6 NOT MET** por P6-T01-B02 (conta/identidade/IAM/bootstrap e operação Google Secret Manager real pendentes). P5-T01 continua BLOCKED_EXTERNAL, não liberada para deploy. Sem segredo real, cloud I/O, gasto ou deploy.

## Gate

- [ ] zero secret raw em Git/log;
- [ ] staging/production rejeitam backend inseguro;
- [ ] audit trail sem material sensível;
- [ ] provider real testado.

**Gate de saída:** EXTERNAL_SECRET_BACKEND_CERTIFIED

---

## Antecipação governada — construção interna P09 antes de P05 (sem deploy)

**Escopo:** executar exclusivamente os contratos internos de tracing, métricas e alertas na mesma aplicação NFCore, reutilizando o runtime, os serviços e as autoridades existentes. Esta antecipação separa trabalho implementável da certificação de operação real. Não altera o gate final de P9 nem autoriza external exporter, Railway, secrets, SQL real, deploy, backup ou produção.

**Dependências internas de entrada:** P1..P4 e P6-T04 internamente certificados; exige auditoria do CURRENT antes de cada tarefa. T01 → T02 → T03 permanecem sequenciais. Os testes devem provar API, DB, chamadas externas e Worker em ambiente controlado. Ausência de qualquer prova impede marcar a tarefa concluída. Traces, dashboards e alertas *reais* continuam gates operacionais dependentes de P05 e P09-T04/T05.

**Justificativa/decisão a confirmar:** o dono determinou concluir a construção antes da publicação e solicitou prosseguir; a alteração exata de ordem depende de revisão e merge humano desta PR documental. P05-T01 mantém `BLOCKED_EXTERNAL` e não é encerrada por esta reorganização. Preservam-se todos os 59 IDs e o validador existente.

### NFV1-P09-T01 — Tracing

Ativar e provar traces de API, DB, chamadas externas e Worker.

### NFV1-P09-T02 — Métricas

HTTP/error/latency, commercial events, fulfillment, worker backlog, retries, dead-letter, provider errors, fiscal rejection, reconciliation e activation.

### NFV1-P09-T03 — Alerts

5xx, provider unavailable, queue backlog, dead-letter, certificate expiry, secret failure, DB, deployment e rejection rate.

# P5 — RECONCILIAÇÃO E CERTIFICAÇÃO DO STAGING

**Status inicial:** NOT_STARTED
**Dependências:** P1 + P2 + P3 + P4 + P6
**Ação externa controlada:** deploy

## Objetivo

Colocar API, Portal e Worker na mesma revisão imutável e certificar o ambiente real.

## Tarefas

### NFV1-P05-T01 — Pré-deploy

Main CI verde, SHA imutável, backup, migrations governadas, rollback baseline, secrets fora de Git e Postgres saudável.

Retomada superior autorizada em 2026-10-13: PR #176 MERGED, main
`59963946c876b5db1c89f3f7b3047e44c2a51d79`, Governance #254 SUCCESS;
CI #833/run38324737715 SUCCESS,41/41 etapas,2208 Python/PostgreSQL PASS.
Isolamento pré-claim existente deve ser preservado.
Operador informa CLI Google autenticado, Secret Manager habilitado, segredo
`nfcore-stg-pilot-webhook-signing` versão cloud 1 e grant secretAccessor restrito
à SA Worker nesse segredo; não é prova de resolução runtime/envelope/binding.
Escopo mínimo autorizado: fonte JSON sealed Railway carregada em memória no
bootstrap existente, metadados de identidade/rotação reconciliados com IAM,
procedimento único Windows sem exposição e configuração não secreta incompleta
explicitamente bloqueada por IDs/binding/destino reais. Sem credencial criada,
merge, mutation schema, migration ou deploy nesta candidata. Console e Commander
não são dependências; operações Google autenticadas ficam no CLI do operador.
Após GSM, preflight SQL somente leitura e integridade atual do backup existente;
não repetir restore PG18 certificado. P05 permanece BLOCKED_EXTERNAL e 27/59.


Retomada autorizada em 2026-10-12 pelo dono: CURRENT main
`cb3c640e2ddc16e02aa491874140beedc113540e`, PR #175 MERGED, CI #831 e
Governance #252 SUCCESS. Resolver isolamento antes do claim da outbox canônica
por host/tenant/unidade/ambiente fiscal/operação, sem fila ou schema novo.
Critério: jobs estrangeiros, inclusive leases expiradas, preservam status,
attempt, lease e auditoria; backlog reflete somente a partição autorizada.
Mapa de impacto: contrato/store outbox, UOW/worker/composition/entrypoint,
bootstrap GSM staging e testes SQLite/PostgreSQL. O piloto continua limitado a
uma partição; registry dinâmico multi-tenant não é certificado por esta correção.
Planejamento migrations 13..17 e Cakto 1..2 somente leitura; usar backup age já
restaurado em PG18, sem repetir restore certificado. Schema/migrations/publicação
exigem aprovação humana específica após gates. GSM real e SQL remoto bloqueados
nesta sessão por console GCP indisponível e cota Desktop Commander esgotada.

Execução T01 autorizada em 2026-10-09 (“Executar”), após PR #150 MERGED e CI main #728/Governance #149 SUCCESS. Escopo: auditoria somente leitura, plano de migration/rollback e correções mínimas dos scripts de restauração e captura do baseline antes da migration. Sem deploy T02, acesso novo a credenciais reais ou implementação P6.

Blockers T01: B01 backup concluído com recibo verificável não confirmado; B02 versões atuais/saúde SQL e compatibilidade de rollback não confirmadas; B03 correções de restore/checksum/SHA/baseline integradas na PR #151, com gates pós-merge em validação; B04 bootstrap real do Worker depende do adapter P6 e da composição canônica; decisão de ordem aprovada em 2026-10-09; B05 driver ainda confunde deployment SUCCESS com processo saudável/revisão exata (correção obrigatória antes de T02, com verificação em T03). Todos pertencem a T01 como pré-requisitos; não criam tarefa concorrente. Checkpoint `docs/checkpoints/NFV1_P05_T01_PREDEPLOY_2026-10-09.md`. Gate permanece bloqueado e 23/59 concluídas.

### NFV1-P05-T02 — Deploy reconciliado

Implantar o mesmo SHA em API, Portal e Worker.

### NFV1-P05-T03 — Smoke

Liveness, readiness, login, recovery, portal bootstrap, onboarding, worker e DB.

### NFV1-P05-T04 — E2E real

Login, unidade, configuração, jornada fiscal controlada, jornadas comerciais, RBAC, isolamento e recuperação.

### NFV1-P05-T05 — Rollback rehearsal

Provar rollback sem destruir estado canônico.

## Gate

- [ ] API SHA == Portal SHA == Worker SHA == SHA certificado;
- [ ] Worker running > 0;
- [ ] E2E verde;
- [ ] rollback provado;
- [ ] evidência persistida.

**Gate de saída:** STAGING_CURRENT_SHA_E2E_CERTIFIED

---

# P7 — FISCAL PROVIDER TRANSPORT REAL

**Status inicial:** NOT_STARTED  
**Dependências:** P1 + P6  
**Dependência externa:** provider/SEFAZ/prefeitura/credenciais.

## Objetivo

Implementar o primeiro transporte fiscal real reutilizável da launch matrix.

## Tarefas

### NFV1-P07-T01 — Definir launch matrix

Fixar documento, UF/município, provider, operações, homologação e produção.

### NFV1-P07-T02 — Adapter de transporte

Autenticação, timeout, request, normalization, rejection, delivery unknown, query/reconciliation e observabilidade.

### NFV1-P07-T03 — Signer/CSC/certificado

Somente referências e material efêmero.

### NFV1-P07-T04 — Contract tests

Provider real deve satisfazer contratos sem alterar Core.

## Gate

- [ ] fake/synthetic fora do caminho real;
- [ ] timeouts explícitos;
- [ ] delivery unknown reconciliável;
- [ ] credencial fora do domínio;
- [ ] launch matrix registrada.

**Gate de saída:** REAL_FISCAL_PROVIDER_ADAPTER_READY_FOR_HOMOLOGATION

---

# P8 — REAL COMMERCIAL CHANNEL VALIDATION

**Status inicial:** NOT_STARTED  
**Dependências:** P3 + P5 + P6  
**Dependência externa:** conta/KYC/provider.

## Objetivo

Executar ao menos um canal comercial real sem transferir autoridade ao provider.

## Tarefas

### NFV1-P08-T01 — Configurar provider aprovado

Se Cakto for selecionada: conta/KYC, produto, oferta, preço, webhook, secret e callback HTTPS.

### NFV1-P08-T02 — Compra controlada

~~~text
checkout
 -> pagamento controlado
 -> webhook autenticado
 -> canonical purchase
 -> subscription
 -> claim/provisioning
 -> OWNER
 -> activation
 -> login
~~~

### NFV1-P08-T03 — Lifecycle

Renewal, late, recovery, cancel, refund e chargeback quando suportados.

### NFV1-P08-T04 — Reconciliação

Detectar e corrigir drift provider x canonical state.

## Gate

- [ ] transação real evidenciada;
- [ ] no provider lock-in;
- [ ] replay seguro;
- [ ] callback HTTPS;
- [ ] secret governado;
- [ ] customer usable account entregue.

**Gate de saída:** COMMERCIAL_CHANNEL_READY

---

# P9 — OBSERVABILIDADE, BACKUP E OPERAÇÃO

**Status inicial:** NOT_STARTED  
**Dependência operacional:** P5  
**Construção interna T01→T03 proposta antes de P5**, na seção antecipada acima. **T04→T05 e o gate operacional permanecem após P5/P7/P8**, sem mascarar blockers. P6 é predecessor de P5.

## Objetivo

Transformar contratos internos de observabilidade e recovery em operação real.

## Tarefas

### NFV1-P09-T04 — Backup/restore operacional

Definir e provar retenção, frequência, RPO, RTO e restore rehearsal.

### NFV1-P09-T05 — Runbooks

Deploy, rollback, DB restore, provider incident, webhook incident, secret rotation, certificate expiry, compromised credential, commercial reconciliation e fiscal unknown outcome.

## Gate

- [ ] dashboards reais;
- [ ] alerts reais;
- [ ] tracing ativo;
- [ ] backup periódico;
- [ ] restore ensaiado;
- [ ] runbooks versionados.

**Gate de saída:** OPERATIONAL_READINESS_CERTIFIED

---

# P10 — HOMOLOGAÇÃO FISCAL OFICIAL E PILOTO

**Status inicial:** BLOCKED_EXTERNAL até P7 e insumos externos  
**Dependências:** P5 + P6 + P7 + P9

## Objetivo

Converter readiness interna em evidência fiscal externa real.

## Tarefas

### NFV1-P10-T01 — Credenciais oficiais

Certificado, CSC quando aplicável, provider credential e homologation environment por célula.

### NFV1-P10-T02 — Homologação oficial

Executar exatamente as operações da launch matrix.

### NFV1-P10-T03 — Evidence ledger

Registrar célula, provider, documento, operação, jurisdição, timestamp, evidence/protocolo e resultado.

### NFV1-P10-T04 — Controlled pilot

Allowlist, kill switch, tenant/unidade, escopo, monitoramento, reconciliação e incident procedure.

## Gate

- [ ] nenhuma célula generalizada;
- [ ] evidence externa real;
- [ ] pilot autorizado;
- [ ] kill switch testado;
- [ ] reconciliação concluída;
- [ ] zero blocker crítico.

**Gate de saída:** FISCAL_LAUNCH_MATRIX_HOMOLOGATED

---

# P11 — INFRAESTRUTURA DE PRODUÇÃO

**Status inicial:** NOT_STARTED  
**Dependências:** P5 + P6 + P8 + P9 + P10  
**Requer autorização humana específica.**

## Objetivo

Provisionar produção como evolução da mesma aplicação certificada.

## Tarefas

### NFV1-P11-T01 — Environment

Projeto/environment, PostgreSQL, API, Worker, Portal, Secret Manager, IAM e network.

### NFV1-P11-T02 — DNS/TLS

Domínio oficial, TLS, redirects, allowed hosts, CORS e trusted proxy.

### NFV1-P11-T03 — Observabilidade/backup

Aplicar os mesmos padrões certificados em staging.

### NFV1-P11-T04 — Promotion readiness

Somente revisão imutável já certificada.

## Gate

- [ ] infra separada;
- [ ] credenciais separadas de staging;
- [ ] DNS/TLS correto;
- [ ] DB/backup/monitoring;
- [ ] rollback baseline;
- [ ] nenhum deploy sem aprovação final.

**Gate de saída:** PRODUCTION_INFRA_READY_FOR_PROMOTION

---

# P12 — CERTIFICAÇÃO FINAL E GO/NO-GO

**Status inicial:** NOT_STARTED  
**Dependências:** P1-P11

### NFV1-P12-T01 — Certificar prontidão funcional

Executar e provar integralmente a matriz A antes de avançar.

## A. Prontidão funcional

- [ ] emissão;
- [ ] consulta;
- [ ] cancelamento;
- [ ] inutilização;
- [ ] reconciliação;
- [ ] documentos/archive;
- [ ] onboarding;
- [ ] recovery;
- [ ] worker;
- [ ] billing/subscription.

### NFV1-P12-T02 — Certificar paridade comercial

Executar e provar integralmente a matriz B antes de avançar.

## B. Paridade comercial

- [ ] pricing;
- [ ] release;
- [ ] checkout;
- [ ] purchase;
- [ ] trial, se fizer parte do lançamento;
- [ ] activation;
- [ ] cancel/refund;
- [ ] customer portal.

### NFV1-P12-T03 — Certificar prontidão técnica de produção

Executar e provar integralmente a matriz C antes de avançar.

## C. Prontidão técnica de produção

- [ ] auth;
- [ ] RBAC;
- [ ] tenant/unit;
- [ ] migrations;
- [ ] PostgreSQL;
- [ ] secrets;
- [ ] containers;
- [ ] CI;
- [ ] security scans;
- [ ] staging certified;
- [ ] exact revision.

### NFV1-P12-T04 — Certificar prontidão operacional

Executar e provar integralmente a matriz D antes de avançar.

## D. Prontidão operacional

- [ ] observability;
- [ ] alerts;
- [ ] tracing;
- [ ] backup;
- [ ] restore;
- [ ] runbooks;
- [ ] incident response;
- [ ] rollback.

### NFV1-P12-T05 — Certificar prontidão comercial

Executar e provar integralmente a matriz E antes de avançar.

## E. Prontidão comercial

- [ ] canal real;
- [ ] domínio/TLS;
- [ ] homologação fiscal da launch matrix;
- [ ] controlled pilot;
- [ ] suporte;
- [ ] pendências legais/LGPD resolvidas ou aprovadas;
- [ ] zero blocker crítico.

### NFV1-P12-T06 — Go/No-Go humano e promoção controlada

Somente após todas as matrizes um humano pode emitir:

PRODUCTION_APPROVED

Promoção:

~~~text
exact certified revision
 -> production preflight
 -> backup
 -> migration
 -> deploy
 -> health/readiness
 -> smoke
 -> monitored acceptance
 -> rollback ready
~~~

**Estado final permitido:** COMMERCIAL_LIVE, somente após evidência pós-promoção.

---

# 7. GATES TRANSVERSAIS — BLOQUEIO AUTOMÁTICO

Qualquer ocorrência bloqueia avanço:

- CI vermelho;
- teste removido/desabilitado para obter verde;
- segredo em Git/log/artifact;
- PII indevida;
- tenant spoofing;
- unit spoofing;
- cross-tenant leak;
- UI como autoridade;
- provider como tenant authority;
- browser declarando pagamento ou entitlement;
- migration sem governança;
- falta de idempotência em mutação crítica;
- retry sem controle;
- worker sem execução real;
- synthetic/fake em caminho declarado real;
- checkout ativo sem fulfillment/activation;
- homologação sem evidência oficial;
- produção fiscal sem aprovação;
- ambiente em SHA divergente na certificação;
- backup sem restore;
- deploy sem rollback;
- blocker crítico aberto;
- decisão humana obrigatória ausente.

---

# 8. TEST MATRIX PADRÃO POR BLOCO

Quando aplicável executar:

- Ruff;
- Mypy;
- unit tests;
- integration tests;
- auth;
- RBAC;
- tenant isolation;
- unit isolation;
- idempotency;
- migrations fresh;
- migrations upgrade;
- PostgreSQL;
- frontend lint;
- frontend typecheck;
- frontend tests;
- build;
- Playwright E2E;
- Docker/container;
- non-root;
- dependency audit;
- secret scan;
- security policy;
- health;
- readiness;
- Worker;
- backup/restore;
- smoke;
- observability;
- remote CI.

É proibido remover gate válido para obter verde.

---

# 9. TEMPLATE OBRIGATÓRIO DE CHECKPOINT

~~~markdown
# CHECKPOINT — <FASE / TAREFA>

Data:
Produto: FM NFCORE V1
Repository:
Main:
Main HEAD:
Branch:
Branch HEAD:
PR:
PR status:
CI PR:
CI main:

CURRENT:
TARGET:

Mudanças:
- ...

Autoridades reutilizadas:
- ...

Arquivos alterados:
- ...

Migrations:
- ...

Testes executados:
- ...

Evidências:
- ...

Security:
- ...

Tenant/Unit:
- ...

Staging:
- ...

External dependencies:
- ...

Blockers:
- ...

Riscos:
- ...

Pendências:
- ...

Gate de saída:
- PASS / FAIL

Próxima ação:
- ...
~~~

Sem checkpoint persistente, a fase não é considerada certificada.

---

# 10. LEDGER MESTRE

| Fase | Gate | Status inicial em 2026-10-05 | Evidência |
|---|---|---|---|
| P0 | CURRENT_RECONCILED_2026_10_05 | READY_TO_START | docs + Git/Railway CURRENT |
| P1 | FISCAL_RUNTIME_COMPOSED_AND_CERTIFIED_INTERNAL | READY_TO_START após P0 | code + tests + CI |
| P2 | PORTAL_COMMERCIAL_PARITY_CERTIFIED | NOT_STARTED | Web/API/RBAC/E2E |
| P3 | COMMERCIAL_RUNTIME_COMPOSED_INTERNAL | NOT_STARTED | acquisition/trial/webhook |
| P4 | CONTINUOUS_WORKER_CERTIFIED_INTERNAL | NOT_STARTED | running worker + retry/DLQ |
| P6 | EXTERNAL_SECRET_BACKEND_CERTIFIED | NOT_STARTED | provider real |
| P5 | STAGING_CURRENT_SHA_E2E_CERTIFIED | NOT_STARTED | same SHA + real E2E |
| P7 | REAL_FISCAL_PROVIDER_ADAPTER_READY_FOR_HOMOLOGATION | NOT_STARTED | adapter real |
| P8 | COMMERCIAL_CHANNEL_READY | NOT_STARTED | transaction real |
| P9 | OPERATIONAL_READINESS_CERTIFIED | NOT_STARTED | tracing/alerts/backup/runbooks |
| P10 | FISCAL_LAUNCH_MATRIX_HOMOLOGATED | BLOCKED_EXTERNAL | official evidence + pilot |
| P11 | PRODUCTION_INFRA_READY_FOR_PROMOTION | NOT_STARTED | production infrastructure |
| P12 | COMMERCIAL_LIVE | NOT_STARTED | final DoD + human Go/No-Go |

---

# 11. DEFINITION OF DONE DO NFCORE V1

NFCore V1 somente pode ser classificado como comercialmente concluído com prova de:

- jornadas reais do cliente;
- operações fiscais do launch scope;
- auth/RBAC/tenant/unit corretos;
- Worker operacional;
- dados/migrations governados;
- Web com paridade necessária;
- visual premium;
- billing/comercial;
- canal de venda real;
- CI verde;
- staging certificado no exact SHA;
- Secret Manager/Vault real;
- provider fiscal real;
- homologação oficial necessária;
- piloto controlado;
- produção correta;
- domínio/TLS;
- backup/recovery;
- observabilidade;
- runbooks;
- zero blocker crítico;
- Go/No-Go humano final.

---

# 12. AÇÕES NÃO AUTORIZADAS POR ESTE DOCUMENTO

Este cronograma não autoriza automaticamente:

- merge em main;
- deploy em produção;
- migration produtiva;
- DNS produtivo;
- alteração irreversível;
- segredo real em Git;
- ativação fiscal de produção;
- transação paga real fora de teste controlado aprovado;
- emissão fiscal real de produção;
- PRODUCTION_APPROVED.

Autorização deve ser específica quando necessária.

---

# 13. PRÓXIMA AÇÃO CANÔNICA

Após aprovação/merge deste cronograma:

~~~text
P0 — reconciliar CURRENT documental
 -> certificar
P1 — Production Fiscal Composition Root
 -> certificar
P2/P3 — Portal Parity + Commercial Runtime
 -> certificar
P4 — Continuous Worker
 -> certificar
P6 — External Secret Manager Adapter (antecipação aprovada em 2026-10-09)
 -> certificar
P5 — reconciliar staging no mesmo SHA
~~~

Nenhuma fase posterior deve ser usada para escapar de pendências de P0-P5. A antecipação P6 aprovada resolve a dependência de assinatura real do Worker e preserva todos os blockers de P5.

---

# 14. PADRÃO AUTOMATIZADO DE EXECUÇÃO

Este cronograma é executado sob o padrão persistente:

- `docs/standards/FM_AI_MASTER_PLAN_EXECUTION_STANDARD.md`;
- `docs/NFCORE_V1_EXECUTION_LEDGER.md`;
- `scripts/check_nfcore_plan.py`;
- `.github/workflows/nfcore-plan-governance.yml`;
- `.github/PULL_REQUEST_TEMPLATE.md`;
- `AGENTS.md`.

Regras adicionais:

1. o cronograma define escopo, dependências, critérios e gates;
2. o ledger registra estado e prova de cada tarefa `NFV1-Pxx-Tyy`;
3. o validador exige que cronograma e ledger tenham exatamente os mesmos IDs e ordem;
4. tarefa concluída exige PR, CI e commit/SHA como prova;
5. uma tarefa posterior não pode ser concluída enquanto houver tarefa anterior não concluída;
6. alteração de escopo exige atualizar cronograma e ledger antes da execução;
7. Git/GitHub, CI e runtime continuam superiores à documentação para determinar CURRENT técnico;
8. conversa pode autorizar decisões, mas não substitui atualização persistente do plano.

---

# 15. PRINCÍPIO FINAL

> O NFCore não será considerado concluído por possuir muito código, documentação, testes ou infraestrutura preparada. Será concluído somente quando a mesma aplicação, na mesma linha arquitetural, estiver integrada, testada, implantada, observável, homologada, operável e comercialmente comprovada.

## Decisão T07-B01 — 2026-10-08

Política de recuperação aprovada integralmente como POLICY_APPROVED_FOR_INTERNAL_IMPLEMENTATION. Implementação/testes e publicação da PR Draft autorizados. Reconstrução ativa; gates e integração continuam obrigatórios. T07/P2 não certificados; P3 não iniciada.

## Integração T07 e gate P2 interno — 2026-10-08

Integração/validação pós-merge autorizadas explicitamente pelo dono. PR #131
MERGED;HEAD7518662a188aba98c3d1b615ccb5ba3408286e41;main
3d7b4698629c312cdb5ee6b04791bf57d05e2179. CI #676/#677,Governance #97/#98
SUCCESS,1413 Python/PostgreSQL,14 frontend,28 Playwright PASS/zero SKIP/zero FAIL
em PR/main; revisão visual320/390/1280px concluída. T07/P2 internos certificados
condicionados ao merge/gates deste closeout; registro no ledger/checkpoint
NFV1_P02_T07_CLOSEOUT_2026-10-08.md. Próxima NFV1-P03-T01,não iniciada.
Nenhum deploy,credencial/provider real,fiscal oficial ou produção autorizado.

## Execução NFV1-P03-T01 — 2026-10-08

Dono autorizou implementação, testes e publicação Draft da aquisição first-party.
Primeira tarefa aberta do ledger: NFV1-P03-T01, em execução. Reutilizar serviço,
assinatura, rate limit, catálogo/release e persistência canônicos. Oferta bloqueada
sem aquisição autenticada composta; provas internas com PostgreSQL no CI.
T02..T05, integração externa, merge/deploy e transação real seguem seus gates.

## Integração NFV1-P03-T01 — 2026-10-08

Merge/validação pós-merge/fechamento autorizados explicitamente pelo dono.
PR #133 MERGED;HEAD0a1397328db3aa315433389c0aad858a2d097caa;main
e13dd86c1782f759f66d9369493735467496b8f7. CI #681/#682,Governance #102/#103
SUCCESS;1429 Python/PostgreSQL,14 frontend,28 Playwright PASS/zero FAIL/zero SKIP.
T01 interno certificado condicionado à integração/gates deste closeout;
próxima NFV1-P03-T02,não iniciada. Gate de fase P3 ainda não concluído.
Provider/secret/delivery operacionais,deploy e transação real não certificados.
Registro:docs/checkpoints/NFV1_P03_T01_CLOSEOUT_2026-10-08.md.


## Decisão de ordem P5/P6 — 2026-10-09

O dono autorizou integrar PR #151 e antecipar P6 antes de P5, respondendo “Autorizado” à proposta persistida em `docs/checkpoints/NFV1_P05_T01_PREDEPLOY_2026-10-09.md`. Os59 IDs foram preservados e apenas os quatro itens P6 foram movidos antes dos cinco itens P5. Cronograma/ledger mantêm a mesma ordem e o validador permanece inalterado. Dependências P6=P1..P4+infra existente+autorizações próprias;P5 acrescenta gate P6. Nenhuma checkbox foi promovida:23/59 concluídas. Próxima tarefa após integrar/certificar este registro: NFV1-P06-T01 — Selecionar provider. P5-T01 continua bloqueada por backup/SQL/compatibilidade/bootstrap/driver; somente a decisão de ordem foi resolvida. A autorização não inclui seleção de provider, gasto/conta, material real de credencial, deploy, migration externa, DNS, emissão ou produção. Checkpoint existente atualizado, sem plano concorrente.


## Decisão de execução e reconciliação — 2026-10-14/15

**CURRENT técnico superior aos retratos de 2026-10-05/10:** `main` inclui PR #185, merge `22a1fbf10e6a90704dcc2d63975cb29ed1373b26`; API e Worker no Railway staging estão 1/1, SUCCESS, mesmo SHA; Portal e PostgreSQL 1/1. O ledger recebeu as evidências detalhadas deste marco. Dados históricos no cabeçalho e checkpoints não devem ser utilizados para reinstalar serviços, repetir migration 17 ou recriar chaves GSM.

**Decisão do proprietário:** estabelecer dois marcos não intercambiáveis. Marco A: desenvolvimento, testes internos, segurança, operação estável e produto acessível na Web. Marco B: validação com contabilidade parceira e homologações oficiais exigidas, somente quando o produto estiver preparado e disponível. A falta de acesso futuro a parceiros/autoridades **não paralisa construção interna**; também não permite declarar autorização fiscal real, homologação oficial ou liberação comercial regulada sem prova. Dependências internas de segurança e testes técnicos continuam mandatórias. Qualquer alteração formal da ordem/critério das tarefas P10/P11/P12 requer revisão governada do cronograma e ledger na mesma PR, e não será inferida silenciosamente deste registro.

**Regra anti-retrabalho:** primeira tarefa aberta documental segue `NFV1-P09-T01 — Tracing`; antes de codificar, comparar o aceite com implementações existentes na `main`. P05 tem recuperação operacional comprovada, mas seus critérios completos por tarefa devem ser reconciliados separadamente; não confundir réplicas 1/1 com smoke, E2E ou ensaio de rollback. Os 59 IDs, sua ordem e estados [x] foram preservados nesta atualização. Fechar cada nova tarefa com provas persistidas em PR, CI, SHA e ambiente, sem depender do histórico do chat.


## Adendo de escopo da V1 — decisão do Diretor em 31/10/2026 (NFV1-BLD-09)

**Decisão posterior, prevalente exclusivamente no escopo cognitivo:** o Core Cognitivo Vertical consultivo **é obrigatório na V1 NFCore**, e a exclusão desse Core da V1 expressa no documento histórico CL02–CL06 não vale mais. **Não renumerar nem alterar os 59 IDs originais**, suas certificações, gates externos, NO-GO fiscal/comercial ou a ordem da homologação. O BLD-09 é bloco adicional de construção governada vinculado ao anexo BUILD-ONLY: [`NFCORE_V1_BUILD_INTEGRATION_EXECUTION_2026-10-18.md`](NFCORE_V1_BUILD_INTEGRATION_EXECUTION_2026-10-18.md); auditoria/contratos/tarefas e aceite em [`NFV1_BLD09_COGNITIVE_CORE_V1_DESIGN_2026-10-31.md`](NFV1_BLD09_COGNITIVE_CORE_V1_DESIGN_2026-10-31.md). Estado **PROPOSTO / PENDING (implementação não iniciada)**, não concluído; implementação, merge para produção, segredos, deploy e despesas dependem de gates e autorização próprios. Piloto operacional de 02/11 permanece independente.
