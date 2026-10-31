# AGENTS.md — FM Fiscal Core V2

> **PONTO DE RETOMADA ANTI-RETRABALHO (31/10/2026):** consultar primeiro `docs/checkpoints/NFV1_CROSS_REPO_ANTI_REWORK_2026-10-31.md`, `docs/NFCORE_V1_BUILD_INTEGRATION_LEDGER.md`, PRs atuais e CI/Governança no SHA da `main`. A seção abaixo contém snapshots históricos Railway; não tomar qualquer SHA, estado de PR ou implantação registrada em datas passadas como CURRENT. O repositório atual `nf-core-v001` é o mesmo repository ID do nome anterior `kordena-fiscal-engine-v2`. `production` é branch de promoção distinta, não equivale ao container implantado na Contabo; alterações de produção exigem aprovação específica.

## Autoridade

Este repositório implementa a evolução independente e multiproduto do motor fiscal brasileiro da FM Tecnologia.

O Fiscal Core não é autoridade do domínio de negócio de Kordena, Iron Fit, Vendedor IA, CampaIA ou qualquer consumidor. Ele recebe contratos fiscais neutros, executa regras e lifecycle fiscais e devolve resultados/eventos auditáveis.

## Estratégia de transição

1. O repositório `faabio3131/kordena-fiscal-engine` permanece baseline congelado durante a transição.
2. O baseline certificado de origem é `b336def47ad4f5188307102203f4e04b98406014`.
3. O V2 deve provar equivalência antes de refatoração multiproduto.
4. O fork é temporário. Depois do cutover certificado, o V2 vira a única arquitetura fiscal ativa e o original é preservado como histórico/auditoria.

## Regras obrigatórias

1. Nunca adicionar segredo, certificado real, senha, CSC, token, credencial, endpoint privado ou dado real de cliente.
2. Todo dado de exemplo deve ser sintético.
3. Alterações fiscais relevantes exigem teste correspondente.
4. Emissão deve ser idempotente por construção.
5. Numeração fiscal não pode usar estratégia concorrencialmente insegura como `MAX + 1`.
6. Regras tributárias devem possuir versão/vigência e ficar atrás do Tax Rule Engine.
7. Documento autorizado deve preservar snapshot histórico; cadastro atual não reescreve passado.
8. Adapters externos não podem inventar regra de negócio.
9. IA pode sugerir classificação, nunca alterar silenciosamente configuração fiscal de alto impacto.
10. Falhas de escopo, assinatura, schema, autorização, capability ou segredo são fail-closed.
11. Core não importa domínios privados dos SaaS consumidores.
12. Integração multiproduto exige `host_system_id`/namespace e binding governado de tenant/unidade.
13. Nenhum merge, deploy, promoção para produção ou cutover é automático.

## Disciplina de entrega

Para cada bloco V2:

- confirmar escopo em `docs/EXECUTION_TRACKER_V2.md`;
- implementar somente o bloco ativo e dependências mínimas;
- executar testes dirigidos;
- executar Ruff, Mypy strict e Pytest;
- revisar diff;
- registrar SHA, PR e CI;
- registrar riscos residuais;
- somente então alterar o estado para `CONCLUÍDO`.

Nenhuma etapa é concluída por declaração sem evidência.


## NFCore Commercial Launch — execução governada por plano mestre

### REGIME ATUAL APROVADO — BUILD-ONLY, CONSTRUIR + INTEGRAR PRIMEIRO (18/10/2026)

**Autorização explícita do proprietário:** concluir a construção e integração NFCore V1 **sem ficar repetindo P05, P02, backup/restore ou homologações já comprovadas**. Esta seção **prevalece sobre bloqueios de ordem históricos apenas para a trilha interna BUILD-ONLY**; o cronograma de 59 tarefas, seus checkboxes e os gates externos/produção **continuam válidos e não são modificados**.

**Ler antes de executar:** 
1. este `AGENTS.md`;
2. `docs/NFCORE_V1_BUILD_INTEGRATION_EXECUTION_2026-10-18.md` (anexo executivo, não segundo plano mestre);
3. `docs/NFCORE_V1_BUILD_INTEGRATION_LEDGER.md` (fila de construção);
4. cronograma mestre e ledger de 59 tarefas para escopo/gates posteriores;
5. GitHub CURRENT/PR/CI + diffs, runtime e checkpoints de evidência.

**Protocolo executável:** executar o primeiro `NFV1-BLD-xx` aberto e seus deltas reais; auditar todos os módulos **código→API→Web→DB/Worker** antes de programar, confrontar PRs abertas e merges, reconhecer o que está `ALREADY_INTEGRATED`. Se bloqueio externo/humano impedir ativação em staging, registrar bloqueio e continuar **somente** trabalho interno independente sem promover o bloco bloqueado ou pular conclusão. Não reiniciar fases certificadas.

**Autonomia de PR e merge — AUTORIZADA pelo proprietário para esta trilha:** criar branch/PR por alteração pequena, implementar, corrigir até todos os gates exigidos ficarem **SUCCESS no HEAD exato**, governança e CI verdes, diff conferido e risco classificado; colocar Ready e fazer **merge sem solicitar nova autorização**. Se check falhar, corrigir a **causa** e executar novamente; não retirar, desativar ou contornar testes/branch protection; só avançar quando pós-merge CI/Gov também estiver verde. A autorização não é carta branca para merge de PR legada ou de outras trilhas. Não confundir teste local verde com CI remota verde.

**Continuam exigindo decisão/autorização humana específica:** preço/plano/duração do trial, provider oficial, nova política sensível de segurança, uso ou criação de credencial/segredo real, conta ou gasto, migrations/alterações destrutivas em ambiente persistente, deploy e infraestrutura, DNS/domínio, mudança de visibilidade, pagamento real, emissão fiscal oficial, produção e irreversíveis. Não fazer deploy por consequência do merge.

**Limite desta fase:** não fazer homologação externa, certificação comercial/produção, P09-T04 backups recorrentes/RPO/RTO, P05-T05 rehearsal real de rollback, nem migrar ambiente definitivo por mera busca de checkbox. O backup+restore isolado histórico já tem prova. Usar somente testes dirigidos e CI que protegem o código enquanto ele é integrado; ensaios externos completos ficam após construção demonstrável. Nenhum dado de cliente real foi recebido nesta fase.

**Validação automatizada adicional:** `python3 scripts/check_nfcore_build_workstream.py` valida sequência/evidências estruturais BUILD; `python3 scripts/check_nfcore_plan.py` continua protegendo os 59 IDs originais. Nenhum deles prova por si só disponibilidade Web. Fechar PRs com SHA/CI/resultado, atualizar o ledger BUILD e apontar próximo trabalho.


Esta seção rege o trabalho do **FM NFCORE V1 — Commercial Launch** e complementa as regras históricas acima.

### Arquivos obrigatórios

Antes de executar qualquer bloco, leia integralmente:

1. `docs/NFCORE_V1_COMPLETION_MASTER_EXECUTION_SCHEDULE_2026-10-05.md`;
2. `docs/NFCORE_V1_EXECUTION_LEDGER.md`;
3. `docs/standards/FM_AI_MASTER_PLAN_EXECUTION_STANDARD.md`;
4. este `AGENTS.md`.

Git/GitHub, CI e runtime continuam sendo as fontes superiores para determinar o CURRENT técnico. O cronograma governa escopo/ordem/gates; o ledger governa estado/prova; o chat não substitui a persistência do plano.

### Disciplina obrigatória

1. Antes de qualquer coisa, reconfirmar `main`, HEAD, PRs abertas, CI e o ambiente afetado.
2. O plano precisa estar `APROVADO` ou `EM EXECUCAO`.
3. Executar somente a primeira tarefa não concluída do ledger, uma por vez.
4. Releia a tarefa no cronograma imediatamente antes de executá-la; não use memória do chat como substituto.
5. Uma PR de execução corresponde a uma única tarefa `NFV1-Pxx-Tyy`, exceto a PR inicial de bootstrap documental.
6. Concluído significa critério de aceite provado. Rode os testes, confira o resultado, obtenha CI/evidência e só então marque `[x]`.
7. O campo **Prova** de tarefa concluída deve registrar PR, CI e commit/SHA; integrações externas também exigem evidência de runtime.
8. Falha deve ser corrigida pela causa; nunca pular, apagar ou enfraquecer teste válido.
9. O que não foi provado é **não confirmado**. Fake/synthetic/mock não prova integração real.
10. Qualquer pendência descoberta deve ser resolvida, receber ID no cronograma/ledger, virar blocker ou ser rejeitada explicitamente com justificativa.
11. Alteração de escopo exige atualizar cronograma e ledger antes da execução.
12. Rode `python3 scripts/check_nfcore_plan.py` antes de abrir/atualizar a PR e antes de declarar o item certificável.

### Parada obrigatória para decisão humana

Parar e solicitar autorização específica antes de:

- decisão de produto/preço;
- mudança de segurança sensível;
- tratamento novo de dado pessoal;
- gasto ou conta real;
- segredo/certificado/credencial real;
- alteração de outro repositório;
- mudança de visibilidade;
- merge quando não autorizado;
- deploy;
- migration produtiva;
- DNS;
- produção fiscal;
- transação real não previamente aprovada;
- operação irreversível.

### Regra de continuidade

Ao retomar o projeto, nunca continue apenas do chat. Reabra o cronograma, o ledger e o último checkpoint persistente; depois reconfirme GitHub/CI/runtime e execute exatamente a próxima tarefa permitida.

### Continuidade NFCore Web — wiring de desenvolvimento, gate interno (2026-10-15)

- CURRENT base: `main=4f7d520ef66831edb56d8d68c60ca24cc17b51f4`; API, Portal e Worker sincronizados na Railway nessa revisão, com `live`/`ready` e controles 401 básicos comprovados.
- Diagnóstico real de `/runtime/profile`: `fiscal_operation_handlers_configured=[]`, checkout/acquisition/trial/receivers não compostos; domínio/portal/fulfillment/ativação preexistentes. NÃO reconstruir motor nem adicionar adapter sintético silenciosamente a staging.
- Branch de correção `feat/nfv1-web-dev-wiring-contract-gates`: `scripts/ci/check_nfv1_web_functional_profile.py` classifica separadamente shell pronto e caminhos de negócio conectados, a partir do perfil existente; testes sintéticos garantem regressão sem invocar fiscal/serviço externo. Usar `--require-all-paths` apenas para gate de paridade total e não confundir com health genérico.
- PENDENTE: composição efetiva de handlers fiscais de desenvolvimento e de ingressos comerciais governados, sem usar fake como homologação; E2E autenticado Portal→API→DB/Worker e prova de todas as superfícies na revisão publicada. Código deste branch não foi implantado nem incorporado à main.
- Ao retomar: verificar CI/Governança da branch e resolver falhas; auditar contratos de `CanonicalFiscalOperationPath` e `create_runtime_app` para conectar somente serviços existentes. Separar construção/testes internos de homologação externa futura; nenhuma alteração de credenciais, migrations ou novo deploy sem autorização específica.

### Atualização de execução segura — 2026-10-15

- A PR #190 revelou falha no Ruff, tratada com correção cirúrgica; novo HEAD deve passar CI e Governança próprios.
- O gate `check_nfv1_web_functional_profile.py` foi ajustado para não exigir simultaneamente os dois receivers de provedores comerciais opcionais (Cakto e Command). Conclusão de wiring exige pelo menos um ingresso de aquisição ou trial, checkout configurado e handlers fiscais, além do núcleo Web. Não transformar contrato do gate em evidência de jornada E2E.
- **Bloqueio factual de wiring fiscal Web:** `runtime.api::app` é composto sem `fiscal_operation_handlers`, ao passo que `CanonicalFiscalOperationPath` é fail-closed e `FakeFiscalOperationsGateway` está apenas nos testes. Não promover adapter sintético a staging/produção, nem criar handler fiscal fictício para pintar flag verde.
- **Bloqueio factual de wiring comercial:** `create_runtime_app` recebe security/receivers e starter explícitos; o entrypoint atual não os constrói automaticamente. Corrigir por composição governada e segredo configurável, não endpoint inseguro ou negócio duplicado.
- **PENDENTE:** instrumentar integração fiscal real de desenvolvimento (sem operação externa), comercial e E2E autenticado; sem credenciais/sessão de teste autorizadas para browser autenticado nesta etapa. Não alegar conclusão da construção ou dos fluxos.

### Implementação efetiva de ingressos comerciais de desenvolvimento — 2026-10-15

- Na PR #190: `runtime/development_commercial_ingress.py` fornece `WebhookSecurity` canônico para aquisição e trial SOMENTE quando `NFCORE_ENVIRONMENT=development|test`, com IDs e segredos HMAC explícitos via configuração (nenhum segredo padrão). Configuração incompleta falha fechada; staging/production não ativam essa composição. O entrypoint `runtime/api.py` injeta tais dependências existentes explicitamente, sem nova API, autenticação ou persistência.
- Testes `tests/runtime/test_nfv1_development_commercial_ingress.py` abrangem ausência de configuração, configuração incompleta, injeção explícita e isolamento de staging. **Isso NÃO ativa automaticamente checkout/acquisition nem trial em staging;** outras dependências existentes (PostgreSQL/composição, checkout e delivery) permanecem necessárias.
- Operações fiscais: `CanonicalFiscalOperationPath` só executa handlers explicitamente injetados; não ligar adapter sintético em staging nem declarar fiscal pronto. Falta integrar handler canônico com adapter aprovado para desenvolvimento e executar E2E autenticado com UOW/tenant/unidade.
- Sem merge, deploy, credenciais reais ou migrations nesta etapa. CI do HEAD mais recente deve ser inspecionada antes de qualquer certificação.

### Execução de código fiscal canônico — archive query (2026-10-15)

- Implementado `runtime/internal_archive_handler.py`: handler real `queryArchiveReference` consulta `FiscalArchiveStore.list_for_document(scope, reference)` com a `FiscalUnitOfWorkFactory` existente, retornando apenas metadados/digest e nenhuma peça de XML/conteúdo. Não chama SEFAZ, não simula autorização e não altera registros fiscais.
- `build_postgres_runtime_composition` registra o handler read-only no mesmo `CanonicalFiscalOperationPath` existente, preservando handlers explícitos e fail-closed dos demais comandos. `web/portal_api.py` habilita a operação com `DOCUMENT_QUERY`; `CanonicalPortalOperationExecutor` continua validando tenant/unidade/ambiente antes do lookup.
- Testes: SQLite durável com isolamento por unidade e entrada inválida `tests/runtime/test_nfv1_internal_archive_handler.py`; API de Portal com sessão AUDITOR e 403 para outra unidade `tests/web/test_portal_api.py`.
- Isto é integração interna real e parcial: emissão/cancelamento/inutilização e fluxo comercial final ainda dependem dos handlers/adapters de execução e checkout aprovados. CI do HEAD exige verificação; PR #190 Draft sem merge ou deploy.


## Protocolo de reconciliação antirretrabalho — obrigatório (2026-10-16)

**LER ANTES DE QUALQUER EXECUÇÃO:** `docs/checkpoints/NFV1_CURRENT_RECONCILIATION_ANTI_REWORK_2026-10-16.md`. É uma fotografia datada; GitHub e runtime atuais prevalecem. Este protocolo aplica-se a TODOS os agentes `.md`, revisores e executores do FM NFCORE V1.

1. Consultar ao vivo `main`/HEAD, PRs, CI+Governança do SHA exato, cronograma, ledger, checkpoints e ambiente de destino; se não for possível, declarar `CURRENT_NAO_VERIFICADO` e não alterar código nem checkbox.
2. Reconstruir a matriz por tarefa `ID → requisito de aceite → código/diff → testes → PR/merge SHA → CI pós-merge → runtime (quando aplicável)`. Sem elo obrigatório, resultado `EVIDENCIA_INSUFICIENTE`, não `DONE`.
3. Fazer busca antirretrabalho em `main` e PRs já mergeadas **antes** de programar; apenas delta faltante é elegível. Não repetir T07/P02 nem as métricas já incorporadas.
4. Distinguir `IMPLEMENTED_NOT_CERTIFIED`, `DONE_CERTIFIED_INTERNAL`, `DONE_CERTIFIED_OPERATIONAL`, `PENDING`, `BLOCKED_EXTERNAL` e `SUPERSEDED`. Não promover checkbox do ledger com CI verde isoladamente.
5. Quando ledger e código divergem, reconciliar uma única vez no checkpoint e registrar evidências; a próxima implementação fica condicionada à resolução da divergência. Nunca tratar nota histórica do AGENTS.md como CURRENT.
6. P09-T01/T02 e P05 são gates separados: tracing/métricas em código não homologam staging; deployment SUCCESS não comprova jornada do cliente. A prioridade comercial Web não autoriza deploy, migration, segredo real ou fiscal real.
7. Fechar cada PR com HEAD, gates PR e pós-merge, alterações, blockers e **próxima tarefa permitida** no repositório. A análise apenas no chat não vale como continuidade.
8. Executar `python3 scripts/check_nfcore_plan.py` e CI. **O validador verifica estrutura; não autentica GitHub ou Railway**. Os dois níveis de prova são obrigatórios.


## Checkpoint de execucao P09-T02 — 2026-10-16 (continuar, nao reiniciar)

- Fonte de verdade no inicio deste recorte: `main=95cd0a852aea001c7bde0a84e5e0c2b4ac111be6`; rever GitHub e CI antes de cada merge. PR #201 ainda aberta (correcao de overflow em `MetricsRegistry`), com CI #952 e Governance #373 SUCCESS no HEAD `d76e538e84db93315c0960a4835fd51d986c29e0`; PR #205 Draft documenta a matriz de aceite, nao certifica T01/T02.
- Worktree isolado no PC: `C:\nfcore-p09-t02-current`, branch `feat/nfv1-p09-t02-remaining-instrumentation-20261016`, baseada em main citada. Checkout historico `C:\nfcore-p05-migrations` em detached HEAD `65c58b6` permanece preservado.
- **Armadilha de ambiente confirmada:** `py -3 -m pytest` sem `PYTHONPATH` carregava `kordena_fiscal` de `C:\Users\faabi\nfcore-t04-work\src`, causando `ImportError` em `test_nfv1_p09_t02_http_metrics.py`. Reexecutar com `PYTHONPATH=C:\nfcore-p09-t02-current\src` resolveu: tres arquivos direcionados, 16 testes PASS. Nao alterar codigo para mascarar contaminacao de import.
- Uma alteracao inesperada em `.github/PULL_REQUEST_TEMPLATE.md` surgiu no worktree durante o checkout. Nao incorporar, descartar ou sobrescrever sem identificar origem; `git add` deve selecionar somente caminhos revisados.
- Instrumentacao CURRENT ja identificada em `runtime/observability.py` (Worker/queue), `runtime/api.py` (HTTP/dependency/activation), `web/app.py` (HTTP), `web/commercial_release.py` (offer), `runtime/commercial_observability.py` (eventos) e `product/cakto.py` (webhook/processing). Antes de adicionar counters, localizar producer + caminho de runtime + testes.
- Ausencias ainda nao certificadas: metricas de fulfillment, reconciliation, provider errors e fiscal rejection; diferenciar metric name presente apenas em teste de evento produtivo realmente instrumentado. P09-T01 tracing/exporter continua separadamente pendente; nenhuma checkbox promovida.
- P05 Worker/GSM e migration17 recuperados; T02 same-SHA staging documentado na PR #203. **Nao repetir deploy, credenciais, migrations, backup/restore ou bootstrap**. T01/T03/T04/T05 ainda possuem gates de prova distintos.
- Nao declarar T02 DONE sem testes/CI e evidencia para cada item do cronograma; sem merge em main, deploy ou operacoes externas sem aprovacao especifica.

- **Causa raiz adicional do template no Windows:** Git rastreia simultaneamente `.github/PULL_REQUEST_TEMPLATE.md` e `.github/pull_request_template.md`. NTFS case-insensitive faz colisao; restaurar um pode deixar outro como modificado. Diff inicial preservado em `C:\Users\faabi\Documents\nfcore-p09-template-unexpected-20261016.patch` (4385 bytes). Nao usar `git add -A`, nao renomear/excluir arquivos do repositorio neste gate; saneamento de conflito case-only exige PR propria e revisao de impacto.

### P09-T02 delta real de reconciliacao comercial — 2026-10-16

- Em `product/cakto.py`, `CaktoCommercialProcessor.reconcile()` passa a emitir `nfcore_cakto_reconciliation_total{outcome=drift|aligned}` somente apos retorno do bridge canonico, sem tenant/customer ID como label. Nao cria segunda autoridade comercial ou fiscal. Teste atualizado em `tests/product/test_web11_cakto.py` valida a amostra drift no caminho real SQLite/bridge.
- Reexecucao dirigida com `PYTHONPATH` do worktree correto: `tests/product/test_web11_cakto.py` mais tres suites P09-T02 = 25 PASS; Ruff dos dois arquivos PASS. Provas apenas locais, CI remoto e demais gates ainda necessarios. Nao confundir reconciliacao comercial Cakto com reconciliacao FISCAL, que segue aberta no cronograma.
- Aviso no Windows: `git diff --check` global inclui modificacao espuria do template case-only; fazer `git diff --check -- AGENTS.md src/kordena_fiscal/product/cakto.py tests/product/test_web11_cakto.py` e stage somente os tres caminhos. Conflito dos templates permanece pendente de saneamento separado.

### Retomada pela ordem do cronograma mestre — P09-T01 antes de T02 (2026-10-16)

- O `docs/NFCORE_V1_EXECUTION_LEDGER.md` marca P09-T01 `[ ] em execucao` e P09-T02 `[ ] pendente`, com dependencia explicita de T02 em T01; NAO promover T02 enquanto T01 nao estiver certificada. O delta Cakto da PR #206 e apenas candidata isolada, sem merge.
- P09-T01 ja possui `SafeTracer` e chamadas em `runtime/api.py`, `runtime/worker_composition.py`, `runtime/observability.py`; nao reconstruir. Executado no worktree `PYTHONPATH=C:\nfcore-p09-t02-current\src py -3 -m pytest -q tests/test_nfv1_p09_t01_runtime_trace_sink.py tests/runtime/test_p04_t03_worker_observability.py` com exit code 0 (alguns testes SKIP por dependencias/opcionais; nao converter SKIP em PASS).
- Gate faltante T01: demonstrar cobertura de spans de DB e dependencias externas e prova do sink/exporter real no staging, com correlacao segura e sem vazamento. Traces escritos em stdout nos testes locais nao bastam para certificacao de exporter remoto. Nao deployar apenas para produzir evidencia sem autorizacao.
- PR #206 HEAD `690a284718a84a2c7f3b4a2f4fb8a4c764f8043a`: Governance #385 SUCCESS e CI #964 ainda `in_progress` na ultima consulta. Verificar gates novamente antes de merge; nenhum merge autorizado por este registro.

### P09-T01 delta de tracing DB — 2026-10-16

- Achado reproduzivel: `runtime/api.py` emite operacao `db.readiness`, mas `StructuredLogTraceSink._ALLOWED_OPERATIONS` a omitia e serializava como `other`. Corrigida somente a allowlist fixa de operacoes, sem ampliar atributos livres, IDs, direitos ou dependencias.
- Teste novo `tests/test_nfv1_p09_t01_db_readiness_export.py` verifica que `db.readiness`/`error` e latencia permanecem visiveis no sink estruturado e que contexto/segredo nao aparecem. Suite nova + `tests/test_nfv1_p09_t01_runtime_trace_sink.py` passou, junto de Ruff dos arquivos alterados (exit 0).
- **Nao declarar P09-T01 concluida:** exporter real/staging, traces DB alem de readiness e chamadas externas permanecem sem prova operacional autenticada. Verificar CI/Governanca do HEAD remoto, manter T01 [ ] e T02 [ ]; nao fazer deploy para obter prova sem aprovacao.

### P09-T01 — Railway observability audit read-only (2026-10-16)

- Read-only Railway project `FM NFCORE Staging`, environment named `production` **within staging project**: API/Portal/Worker deployments SUCCESS at same source `2f3689838cfbec1c6d2ffac614cb0eb364d91633`. This does NOT mean commercial production.
- Railway `describe_service` API (`nfcore-api`) and Worker (`nfcore-worker`): `tracingEnabled=false`, `autoInstrumentationEnabled=false`, `autoInstrumentationActive=false`; no configured environment-variable names matching OTEL/TRACE/OBSERV/EXPORT/LOG identified. Railway native OpenTelemetry exporter is **not enabled**. Existing structured-log `SafeTracer` is separate from native Railway tracing, so native switch OFF does not prove application tracing ABSENT.
- Railway deploy logs search `runtime.trace` for both services yielded 0 entries; broad read displayed HTTP readiness/startup and Worker mostly empty log lines. Neither result certifies real span collection or lack of implementation. No authenticated end-to-end trace evidence with DB, external webhook, Worker and API in a configured destination.
- **Gate:** P09-T01 remains `[ ] EVIDENCIA_INSUFICIENTE` for staging exporter. Enabling Railway tracing on API requires redeploy; DO NOT call `set_service_tracing`, change variables, restart, migrate or deploy without specific approval. Preserve P05 runtime. First choose approved observability sink with retention/access/PII policy, confirm scope, and obtain explicit deploy permission when required.
- Corrections to P09-T01 and P09-T02 remain in PR #206 Draft, not deployed. Never use deployed SHA `2f368983` as evidence of corrections at branch HEAD. Verify exact PR CI and governance before integration.

### P09-T01 — Autorizacao e ativacao Railway Native Tracing (2026-10-16)

- Dono autorizou expressamente ativar tracing nativo da API e Worker no projeto `FM NFCORE Staging`; nenhuma autorizacao concedida para migration, credenciais fiscais, production commercial release ou merge.
- Auditoria preflight Railway: projeto `b84b290d-f3b4-46a1-9023-0b761cb96b0d`, environment interno Railway com nome `production` e ID `c9878b9b-62b2-4a97-b8ba-743c8a3e99ec` (o PROJETO e staging). Ambos servicos LIVE, sem patch staged, baseline source SHA `2f3689838cfbec1c6d2ffac614cb0eb364d91633`, tracing e autoinstrumentacao OFF.
- Acao autorizada executada: `set_service_tracing(tracingEnabled=true,autoInstrumentationEnabled=true)` na API `705bd719-f77b-4ade-a47c-4e6af63737d5` e no Worker `b3bde804-fa29-4c67-841d-7cda050c40e7`; ambas retornaram `tracingEnabled=true,autoInstrumentationEnabled=true,autoInstrumentationActive=true`.
- Railway iniciou deployments resultantes, API ID `8832e77c-70fc-41f9-bfec-25177342e3bd` e Worker ID `3634c897-8ce6-4f37-8b5f-98cd9b107adc`. Na primeira rechecagem ambos BUILDING. **Nao declarar sucesso de deploy, E2E, traces DB/externos ou T01 DONE ate confirmar deploy SUCCESS, health e traces reais no destino.**
- Revalidar estado do projeto e services; nao repetir a acao `set_service_tracing` se ja TRUE, nem criar credenciais, migrations ou novos deploys. Registrar SHA final, logs filtrados e limites de retencao/privacidade antes de promover checkbox.

### P09-T01 — Verificacao pos-ativacao Railway Native Tracing (2026-10-16)

- Apos ativacao autorizada, API deployment `8832e77c-70fc-41f9-bfec-25177342e3bd` **SUCCESS** e Worker deployment `3634c897-8ce6-4f37-8b5f-98cd9b107adc` **SUCCESS**, ambos no source SHA `95cd0a852aea001c7bde0a84e5e0c2b4ac111be6` de main. Portal preservado em SUCCESS com `2f3689838cfbec1c6d2ffac614cb0eb364d91633`, logo nao afirmar paridade same-SHA dos tres servicos depois da mudanca autorizada.
- Smoke real `GET https://nfcore-api-production.up.railway.app/health/ready` respondeu HTTP 200 e body `status=ready,reason=ready`, incluiu header `x-railway-trace-id`. Isso prova a resposta de readiness e correlacao do Railway edge, NAO garante todos os spans OTel de API/DB/external/Worker.
- Consulta `runtime.trace` nos novos deployments API e Worker retornou zero eventos no stream deploy; nao inferir ausencia de spans nativos em backend de tracing a partir de busca de logs estruturados. Destino, filtros, retencao e captura real em tracing UI ainda nao atestados.
- Estado formal P09-T01 = `IMPLEMENTED_NOT_CERTIFIED`/`EVIDENCIA_INSUFICIENTE` para end-to-end operacional; nao promover `[x]`. Nao executar outro deploy ou reconfiguracao apenas para perseguir log ausente. Proximo passo: prova de spans representativos API, DB, external e Worker no destino aprovado, e permissao humana para outros testes que provoquem efeitos reais.

### P09-T01 — Prova real do trace backend Railway (2026-10-16)

- Inspecao do destino nativo com `Railway.list_traces` (janela ~14:25–15:25Z) encontrou **2 traces reais** `/health/ready` no projeto FM NFCORE Staging, com 4 spans cada e 0 erros. Trace auditado `1a2648690b15179af77322a0bd2ede2c`: `edge.request` (SERVER), `edge_rules.evaluate` (INTERNAL), `upstream.request` (CLIENT), `origin_proxy.request` (SERVER). Componentes SOMENTE `edge`/`proxy`, nenhum span `service`.
- `Railway.get_tracing_coverage`: API `nfcore-api` = `spanCount=0`, Worker `nfcore-worker` = `spanCount=0`, sistemas/scopes vazios na janela. Tracing Railway e autoInstrumentation Active nos dois, mas isto NAO comprova instrumentacao interna.
- Auditoria CURRENT main `95cd0a852aea001c7bde0a84e5e0c2b4ac111be6`: `SafeTracer` usa `StructuredLogTraceSink` (logs de evento `runtime.trace`, sem OTLP) ou `NullTraceSink`; `pyproject.toml` nao declarou dependencias OpenTelemetry. PR #206 Draft contem uma allowlist corretiva DB ainda nao mergeada/deployada. **Causa provavel:** falta ligacao real do adapter de spans da aplicacao ao exporter OTLP, nao simples opcao de tracings do Railway; essa classificacao e HIPOTESE ate validacao via deploy governado.
- **P09-T01 EVIDENCIA_PARCIAL, NAO CERTIFICADA:** edge/proxy confirmados; API/DB/external/Worker spans internos ausentes na janela medida. Proxima implementacao aprovada somente apos mapa de impacto: adaptador OTel seguro sobre `SafeTracer` existente, export de spans tipados de baixa cardinalidade, falha nao autoritativa, teste de export e retencao, sem segunda autoridade nem credenciais hardcoded; validar por CI e solicitar autorizacao antes de integrar/deployar. Nao repetir ativacao Railway.

### Decisao do dono — priorizar fechamento interno antes de homologacao externa (2026-10-16)

- Nao exigir contador, cliente piloto, credenciais/certificados oficiais, SEFAZ, prefeitura ou provider fiscal REAL para continuar a construcao do NFCore V1. Homologacoes de terceiros ficam classificadas `BLOCKED_EXTERNAL` ate que o produto esteja internamente completo e pronto para apresentacao/teste real.
- Seguir `docs/NFCORE_V1_COMPLETION_MASTER_EXECUTION_SCHEDULE_2026-10-05.md` e ledger na ordem, executando integralmente codigo, APIs, composicao, PostgreSQL, Worker, Web/UI, RBAC/tenant, seguranca, testes locais/CI e operabilidade possiveis sem dependencia externa; nao mascarar criterios internos como externos.
- P09-T01: concluir adaptador OTLP e instrumentacao interna existente por testes controlados locais/de staging sem dados reais de terceiros; nao bloquear desenvolvimento por ausencia de piloto fiscal. A prova de homologacao fiscal externa nao faz parte deste gate de construcao. Nao declarar spans end-to-end certificados onde nao houver evidencias.
- Manter aprovacao humana especifica para merge, deploy, migrations reais, credenciais reais e operacoes irreversiveis. Atualizar AGENTS.md, checkpoint e ledger com evidencias, bloqueios e proximo bloco em cada marco.

### P09-T01 — reconciliacao/implementacao interna API tracing (2026-10-16)

- CURRENT conferido: main `95cd0a852aea001c7bde0a84e5e0c2b4ac111be6`, branch da PR #206 baseada em main, `SafeTracer`/`StructuredLogTraceSink` canônicos; Worker usa sink estruturado, mas API criava por padrao `SafeTracer()` com `NullTraceSink`. Corrigido apenas `runtime/api.py`: criar `runtime_logger` primeiro e usar `SafeTracer(StructuredLogTraceSink(runtime_logger))` se tracer nao for injetado; dependencia/injecao explicita continua prevalecendo, sem segunda autoridade.
- Teste novo `tests/test_nfv1_p09_t01_api_default_trace_sink.py` verifica evento `runtime.trace` e ausencia de token no sink quando dependencias canônicas estao instaladas. Na maquina Windows atual a coleta foi `SKIP` declarado (ausente `google.cloud.secretmanager_v1`), NAO PASS. Suite anterior de tracing/DB passou 7 testes, Ruff dos arquivos editados PASS; testes E2E da API em CI completo precisam confirmar funcionalidade. Nao mascarar o SKIP nem substituir GSM.
- Esta alteracao produz log estruturado seguro da API; NAO constitui exporter OTLP e NAO prova spans da aplicacao no Railway. O adaptador OpenTelemetry, cobertura API/DB/external/Worker, CI do HEAD, staging e gates P09-T01 continuam pendentes. Nao promover ledger/checkbox. Conflito case-only de templates no Windows permanece protegido/nao incluido.

### P09-T01 — implementacao candidata do exportador OTLP governado (2026-10-16)

- Preflight: `main=95cd0a852aea001c7bde0a84e5e0c2b4ac111be6`, PR #206 isolada; Railway tracing nativo ligado e traces edge/proxy comprovados, mas cobertura de spans de servico API/Worker era zero. Cronograma/ledger ainda apontam P09-T01 como primeira tarefa pendente.
- Adicionado `runtime/otel_trace_sink.py`: `OtelTraceSink` projeta exclusivamente operacao e outcome de vocabulos fixos, tempo; ignora IDs/contexto e todos os atributos arbitrarios. `build_trace_sink` preserva `StructuredLogTraceSink` ja existente, agrega exportacao OTLP apenas com `OTEL_EXPORTER_OTLP_ENDPOINT` explicito e bibliotecas instaladas, usa `BatchSpanProcessor`, degrada a logs sem interromper fiscal se indisponivel. `SafeTracer` continua a unica autoridade de redacao e falha nao autoritativa; nenhuma segunda API, tenant ou persistencia.
- Composicoes existentes `runtime/api.py`, `runtime/worker_composition.py` e webhook handler passam a construir mesmo sink; injeções explicitas prevalecem. `pyproject.toml` adiciona grupo `telemetry`, e Dockerfiles API/Worker instalam a dependencia em builds FUTUROS, sem deploy agora. Testes deterministicamente validam projecao segura, labels limitadas, tempo e ocultacao de segredos.
- Primeira suite direcionada com testes do novo adapter/trace/DB/API/Cakto terminou sem falha de pytest, com 1 SKIP conhecido (GSM ausente no PC Windows); Ruff encontrou import nao usado, corrigido; Mypy direcionado em andamento. Gates remotos, SDK runtime com exporter real, CI e Railway spans internos ainda NAO certificados. Esta candidata nao esta em main nem staging.
- Manter PR em Draft e nao promover P09-T01 ou T02; proximo gate: fechar typecheck, CI remoto, seguranca de endpoint OTLP/retencao e testes de exporter com SDK real; merge/deploy exigem autorizacao.

- Gates finais deste delta: `ruff check` dos tres modulos + teste OTLP PASS; `mypy --follow-imports=silent` dos tres modulos alterados PASS; `mypy` sem isolamento falhou em `vault/google_secret_manager.py` por `google.cloud` sem marcadores de tipos no ambiente Windows (dependencia preexistente, NAO certificada); `check_nfcore_plan.py` PASS com 59 tarefas, P09-T01 ainda proxima. Suites direcionadas OTLP+tracing+DB+API+Cakto executadas sem testes falhando, com um teste SKIP por ausencia de GSM local. Nao contabilizar SKIP como PASS.
- O adaptador e um candidato seguro testado com tracer fake, nao foi provado ainda com OpenTelemetry SDK/exporter REAL, nem em Railway, nem em E2E com DB/externo/Worker. CI remota do HEAD e gate de merge continuam necessarios; manter PR Draft.

### P09-T01 — SDK OpenTelemetry real validado localmente (2026-10-16)

- Reconciliação CURRENT: main `95cd0a852aea001c7bde0a84e5e0c2b4ac111be6`; PR #206 Draft no HEAD de início `90733d6ee514beb2d2a7f881dc8fc987e113932e`. Governança remota #394 SUCCESS; CI #973 ainda `in_progress` na verificação — não promover certificação.
- Instalado SDK de teste OpenTelemetry `1.45.1` e exporter OTLP HTTP correspondente no Python local. Isso NÃO instala na produção ou Railway nem prova rede externa OTLP.
- Teste de regressão `tests/test_nfv1_p09_t01_otlp_sdk_real.py` usa `TracerProvider`, `SimpleSpanProcessor` e `InMemorySpanExporter` reais: confirmou span `external.webhook`, outcome `error`, duração `400000000 ns` e nenhuma label com correlation/customer/token/authorization. Suite SDK real + testes do sink anterior: **3 PASS**, Ruff do novo teste PASS.
- A primeira tentativa de coleta encontrou import incorreto de `InMemorySpanExporter`; ajustado para `opentelemetry.sdk.trace.export.in_memory_span_exporter`. Não esconder falha original; teste subsequente aprovado.
- Ainda pendentes antes de merge: CI #973 e novos gates do HEAD atualizado, typecheck total, teste do `BatchSpanProcessor` + `OTLPSpanExporter` com transporte real controlado, construção dos containers e prova de exportação em staging. P09-T01 permanece `[ ]`, P09-T02 não antecipada. Nenhum merge, deploy ou migration autorizado neste registro.

### P09-T01 — Gate OTLP/HTTP real controlado e reconciliacao (2026-10-16)

- GitHub CURRENT rechecado antes da execução: main `95cd0a852aea001c7bde0a84e5e0c2b4ac111be6`, branch PR #206 `ddf011d400fc3996006a53bf73b8f75b36e85c8c`; `fetch_commit_workflow_runs` não encontrou gates para esse HEAD. Não assumir CI verde nem reutilizar CI anterior cancelada.
- Novo teste `tests/test_nfv1_p09_t01_otlp_http_real.py` com **SDK OpenTelemetry real** e `OTLPSpanExporter`, receptor HTTP local `127.0.0.1` sem rede externa: exportou POST `/v1/traces` e protobuf `ExportTraceServiceRequest`; confirmou `worker.dispatch`, `nfcore.outcome=succeeded`, duração 125ms e nenhuma presença de identificadores/segredos arbitrários. Suite com outros dois testes OTLP: **4 PASS**; Ruff inicialmente encontrou 1 linha longa, corrigida; Ruff final PASS.
- Verificação de container: `docker --version` indisponível na máquina Windows atual. **Build Docker não executado**, portanto não declarar imagens certificadas. SDK local foi instalado fora do Railway; não ocorreu deploy. Validador cronograma mestre PASS, 59 tarefas, P09-T01 permanece primeira pendente.
- Falta provar: build Docker real API/Worker, CI/Governança para HEAD exato, configurações de transporte OTLP (endpoint/segredos/egress), exportação efetiva de spans internos API/DB/externo/Worker no Railway após integração autorizada. P09-T01 não marcada como concluída; P09-T02 não avançar sem reconciliar dependência. Preservar P05 e PR Draft sem merge/deploy.

### P09-T01 — CI PR #206 diagnosticada e corrigida (2026-10-16)

- CI real da PR #206 HEAD `d57b71e28b45d92a6d072fe1733f1cfffb45f9ce`: GitHub Actions quality job `117076238847`, run `38931465590`, falhou em `Pytest` porque `tests/test_nfv1_p09_t01_api_default_trace_sink.py` importava `create_app` de `runtime.api` (ali importado da camada `web.app`) e passava `logger=`, argumento nao suportado. Governanca `execution-plan` PASS. Ruff/Mypy do job PASS antes da falha.
- Correcao estritamente no teste: usar `create_runtime_app(logger=logger)` da autoridade de composicao runtime (sem alterar regra de negocio, API ou seguranca). Ruff local PASS; teste de OTLP HTTP real PASS e teste da composicao API SKIP explicitamente por dependencia GSM ausente no Windows local; **CI remota deve exercitar esse teste com dependencias completas**, nao declarar PASS com SKIP local.
- Nao integrar PR #206 ate rerun completo de quality, Docker, CI/Governanca HEAD exato 100% verde. Cronograma master/ledger permanecem P09-T01 primeiro item, P09-T02 em sequencia; nenhuma etapa P05 repetida. Template com colisao Windows case-only preservado fora do commit.

### Checkpoint pós-PR #206 — 2026-10-16

- **CURRENT GitHub:** `main=904587334bdd830a41c260e0f545f3d6083e8bfc`; PR #206 MERGED (não integrar novamente). Governança pós-merge Railway/GitHub `38937043756` SUCCESS, CI `38937043499` IN_PROGRESS na última consulta, sem concluir gate.
- **Reconciliação:** `docs/NFV1_P09_T01_T02_POST206_RECONCILIATION_2026-10-16.md` contém matriz por produtor real da P09-T02 e separação comercial Cakto x fiscal. Não duplicar instrumentação existente: HTTP, commercial events, worker backlog/retry/dead-letter, Cakto reconciliação e activation. Auditar lacunas fulfillment/provider errors/fiscal rejection/reconciliation fiscal sem inventar implementação.
- **Governança:** ledger e cronograma seguem com P09-T01 como primeira tarefa aberta; P09-T02 formalmente depende de certificação T01. O exportador OTLP está na `main`, mas não está comprovado implantado no staging; traces edge não equivalem a traces internos. Não promover `[x]`; não repetir P05. Registrar CI concluída apenas após evidência no HEAD exato.
- **Ação da branch:** reconciliação documental isolada. Sem alteração de runtime, credenciais, migração, deploy ou merge automático.

### Auditoria adicional P09-T02 (2026-10-16)

A busca de produtores reais confirmou ausência de instrumentação específica em `CommercialFulfillmentService.process`, ausência de usos de produção dos enums `PROVISIONING`/`PROVIDER_DRIFT`/`FAILURE`, e nenhuma métrica dedicada encontrada para rejeição e reconciliação fiscal. `nfcore_provider_errors_total` só foi localizado em teste sintético da registry. A matriz detalhada está em `docs/NFV1_P09_T01_T02_POST206_RECONCILIATION_2026-10-16.md`. Não declarar T02 concluída; implementar sobre autoridade determinística, não criar segundo runtime. CI #206 pós-merge e #207 consultadas durante a auditoria, ambas ainda `in_progress` na última consulta disponível.

### Execução funcional P09-T02 — fulfillment (2026-10-16)

- Implementado contador canônico `nfcore_commercial_fulfillment_total` em `application/commercial_fulfillment.py`, labels `outcome=succeeded|replay`, emitido nos pontos de retorno após estado confirmado/replay, com falha da telemetria não autoritativa. `runtime/composition.py` recebe o `MetricsRegistry` opcional e o injeta no serviço; `runtime/api.py` cria registro ANTES da composição e compartilha o mesmo objeto exposto por `app.state.nfcore_metrics`. Sem segunda registry, API, autenticação ou persistência.
- Novo teste `tests/application/test_nfv1_p09_t02_fulfillment_metrics.py` verifica um evento novo + replay idempotente com labels sem PII. Suite dirigida de fulfillment: 8 PASS; Ruff PASS; Mypy dos três módulos com `--follow-imports=silent` PASS; validador cronograma 59 IDs PASS.
- **P09-T02 não certificada:** provider errors, fiscal rejection e fiscal reconciliation continuam gaps de implementação; métrica de fulfillment requer CI remota e prova integrada. Nenhum deploy nem merge desta branch. **CI pós-merge PR #206 `38937043499` SUCCESS** conferida agora, Governança pós-merge `38937043756` SUCCESS; qualidade da PR #207 em execução e governança PASS.

### P09-T02 — CI da PR #207 corrigida (2026-10-16)

- Gate real PR #207 HEAD `3a03a25` FAIL, run `38939269899`, job `117102623244`, Pytest interrompido na coleta: `ModuleNotFoundError: No module named 'tests'` no novo teste de fulfillment. Corrigido import entre módulos de teste para resolução local pelo pytest sem tocar na autoridade comercial. Suite local de 8 testes PASS, Ruff corrigido PASS, validador do plano 59 IDs PASS.
- Auditoria de fiscal: `application/service.py` registra `IssuanceAttemptStatus.REJECTED` como disposição de replay; não confundir replay com nova rejeição. `gateway/authorization.py` é autoridade de resultado de provedor; métricas somente ao redor do resultado canônico persistido ou transporte conforme responsabilidade. P09-T01 operacional segue bloqueada por spans staging não comprovados; não promover status.

### P09-T02 — Reconciliação fiscal instrumentada (2026-10-16)

- No serviço canônico `FiscalApplicationService.reconcile_operation`, adicionado contador `nfcore_fiscal_reconciliation_total` **após** persistência e commit, com `outcome` derivado exclusivamente de `ReconciliationStatus` (enum), sem tenant/document/provider IDs nem payload. `runtime/composition.py` compartilha o `MetricsRegistry` opcional da API com o mesmo serviço, sem segunda autoridade de telemetria. Se a métrica falhar, não modifica estado fiscal. A reconciliação comercial Cakto permanece separada.
- Testes existentes de reconciliação/fulfillment 11 PASS; Ruff PASS; Mypy direcionado PASS; cronograma 59 IDs PASS. Sem teste específico novo para a métrica fiscal ainda, nem CI deste novo HEAD; **não certificada**. P09-T01 staging spans ainda sem prova; provider errors e fiscal rejection seguem abertas.

### P09-T02 — Produtores fiscais reais instrumentados (2026-10-16)

- `issuance/nfce.py` — no orquestrador determinístico existente, adicionados contadores opcionais `nfcore_provider_errors_total{outcome=error}` ao capturar exceção do gateway e `nfcore_fiscal_rejections_total{outcome=rejected}` apenas após `mark_rejected`. Nenhuma mensagem de erro, protocolo, CNPJ/tenant, código de rejeição ou ID é usado como label. A exceção original continua sendo propagada, decisões fiscais não mudam. A instrumentação exige injeção explícita do `MetricsRegistry`; NÃO presumir que todos os handlers de produção a recebem nem alegar cobertura global de providers.
- `tests/issuance/test_nfce_orchestration.py` ampliado com casos de rejeição e exceção do gateway. Suite de NFC-e + teste específico da reconciliação fiscal: 10 PASS; Ruff de fontes e testes PASS. A falha de gateway representada no teste é sintética, não homologação externa. `nfcore_fiscal_reconciliation_total` já adicionado ao `FiscalApplicationService` após commit e ligado à registry no composition root.
- Permanecem gates: CI completa da PR #207 no HEAD atual; provar wiring de métricas dos handlers de NF-e/NFS-e efetivamente configurados; tracing serviço real staging P09-T01; autorização específica para deploy/secret e demais controles da organização. Não converter `IMPLEMENTED_NOT_CERTIFIED` em `[x]` prematuramente.


### Execução retomada P09-T03 — 2026-10-16

- Branch isolada a partir da `main=e4ffd584`: `feat/nfv1-p09-t03-internal-alert-rules-20261016`, sem tocar na PR documental #208.
- Novo avaliador determinístico `runtime/alert_rules.py` lê `MetricSample` da `MetricsRegistry` canônica e produz candidatos de alertas de HTTP 5xx, provider errors, worker backlog, dead-letter, fiscal rejection e falha de ciclo. Sem side effect, envio externo, tenant ID/PII, segredos ou rota paralela. Série ausente não é tratada como saudável.
- `tests/runtime/test_nfv1_p09_t03_alert_rules.py`: 2 PASS; Ruff PASS; `scripts/check_nfcore_plan.py` 59 IDs PASS. São **candidatos e thresholds de demonstração**, não política operacional homologada: faltam fontes de expiração de certificado, secret failure, DB, deployment, denominador de rejection rate; conexão a um ciclo de avaliação, integração e roteamento de notificações. Não marcar P09-T03 `[x]`.
- Regra de continuidade: não usar testes externos/contabilidade como bloqueio de construção. Não confundir esse incremento candidato com alertas ativos em staging.

### P09-T03 — correção de contadores vs gauges (2026-10-16)

- Correção interna no avaliador `alert_rules.py`: contadores acumulativos exigem dois snapshots e um delta não negativo, evitando reemitir alerta sobre erros históricos. Série nova, ausente ou resetada não é computada sem baseline válido; gauge de backlog usa valor presente. Nenhuma telemetria externa, segredo, tenant label, pager ou envio foi incluído.
- Tests `tests/runtime/test_nfv1_p09_t03_alert_rules.py`: 2 PASS com delta, reset e ausência de baseline; Ruff PASS e Mypy direcionado PASS. Esta etapa ainda NÃO inclui política de roteamento, certificados, segredo, DB, deploy, rejection rate com denominador ou avaliação em runtime, então P09-T03 continua `IMPLEMENTED_NOT_CERTIFIED`.
- A CI anterior da PR #209 falhou em `tests/runtime/test_p04_t04_worker_container.py::test_real_continuous_idle_process_signal_exit_and_restart[2]`, timeout do subprocesso após 10s; não desabilitar o teste. Confirmar CI no novo HEAD e investigar se reproduzir antes de merge.

### P09-T03 — sinais operacionais e ciclo de avaliação (2026-10-16)

- `InternalAlertMonitor.poll()` passa a avaliar a mesma `MetricsRegistry`, com baseline por coleta e sem efeitos externos. `OperationalSignals` recebe observações explícitas (expiração de certificado em dias, secret resolution, DB readiness, deploy health); `None` significa desconhecido, nunca `OK`. Nenhuma credencial ou certificado real é consultado pelo monitor.
- `fiscal_rejection_rate()` exige ambos os contadores canônicos `nfcore_fiscal_rejections_total` e `nfcore_fiscal_authorizations_finalized_total`, cada um em dois snapshots e com denominador positivo. Na falta de produtor `nfcore_fiscal_authorizations_finalized_total` integrado, a taxa **não dispara nem pode ser alegada ativa**. Evita inventar taxa por usar tentativas como denominador não equivalente.
- Testes dirigidos novos de sinais, missingness, rate, reset e poll: 5 PASS; Ruff PASS; Mypy PASS. Ainda faltam conectores das fontes reais em execução, exposição governada de alertas e entrega/ack/dedup; P09-T03 `IMPLEMENTED_NOT_CERTIFIED`. A PR #209 permanece sem merge ou deploy.

### P09-T03 — incremento operacional / integrações internas (2026-10-16)

- `InternalAlertMonitor` conectado à instância existente de `MetricsRegistry` no composition root da API, acionado nos próprios caminhos `/health/ready` e `/internal/metrics`, sem criar nova API ou instância autoritativa. Métricas mantém campo `metrics`; adiciona `alert_candidates` restrito a códigos, severidade e números. Não faz notificações externas.
- `OperationalSignals` representa exclusivamente observações presentes de validade de certificado, resposta da autoridade de segredos, health do banco e saúde de deploy. `None` significa desconhecido; **somente readiness DB foi conectado diretamente ao runtime API**. Fontes periódicas reais de certificado, secret manager e Railway deployment ainda não estão conectadas — não declarar alarme ativo para esses itens.
- `nfcore_fiscal_authorizations_finalized_total` agora é emitido pelo orquestrador **NFC-e** depois de `mark_authorized` ou `mark_rejected`, com `outcome` controlado. `fiscal_rejection_rate()` exige delta positivo desse denominador real e numerator NFC-e. Não representar toda NF-e/NFS-e como coberta.
- A autoridade preexistente `observability/alerts.py` (`AlertRegistry`, dedup e `OperationalAlertEvaluator`) foi identificada: novos candidatos podem ser publicados por `publish_alert_candidates` passando `ObservabilityContext` confiável, reutilizando o registro canônico, sem segunda persistência ou sistema de alertas. Nenhuma origem de tenant é inferida de HTTP desautorizado.
- Suite dirigida alerta/API/NFC-e: **15 PASS e 1 SKIP local (GSM ausente)**, Ruff PASS, Mypy de 3 fontes PASS. CI Linux deve provar teste API efetivo e regressão completa. P09-T03 segue `IMPLEMENTED_NOT_CERTIFIED`, sem deploy/merge.

### P09-T03 — avaliação no ciclo canônico do Worker (2026-10-16)

- O monitor de alertas foi conectado ao `_TracingWorkerObserver` da composição contínua, após `cycle_completed` e `cycle_failed`, aproveitando a mesma `MetricsRegistry` e sem interferir com claim/retentativas/outbox. `ProductionWorkerComposition.alert_monitor` torna o último conjunto de candidatos inspecionável sem expor um novo endpoint de Worker.
- `InternalAlertMonitor.latest` é atualizado apenas por `poll()`. Qualquer falha do monitor é isolada do ciclo fiscal. Teste com baseline real comprova alerta `worker_dead_letter` apenas quando há incremento, não em leituras repetidas, além de falha da telemetria não autoritativa. 8 PASS nos testes dirigidos P09-T03, Ruff e Mypy direcionados PASS.
- Avaliação API e Worker processam métricas **distintas por serviço**; não consolidar em um único tenant ou supor visibilidade de Worker via API. O Core só projeta candidatos; alertas ativos por tenant permanecem governados por `AlertRegistry` com contexto confiável. Homologação com terceiros e fontes de deployment real continuam separadas.

### P09-T03 — adapters de fontes canônicas (2026-10-16)

- `certificate_expiry_signal`: usa apenas `CertificateReference.expires_at` da autoridade de assinatura, depois de confirmar `ExecutionScope` tenant/unidade; não lê PFX ou material privado. `secret_audit_signal`: usa exclusivamente o outcome do `SecretAuditEvent` produzido pelo `SecretResolver`, sem expor IDs, tenant ou valor do segredo. `railway_deployment_signal`: converte apenas estados explícitos autenticados (`SUCCESS`, `FAILED`, `CRASHED`); `DEPLOYING`/desconhecido permanecem `None`. São adapters testados de payloads confiáveis, **não criam sondas ou credenciais externas**.
- Os eventos de origem dependem de invocação pela autoridade concreta, e deploy Railway depende de observações do plano de operação/Command; não declarar monitoramento contínuo de certificado/segredo/deploy apenas pela existência desses adapters. As integrações não ativadas seguem `NOT_CONNECTED`, distinta de homologação fiscal.
- Suite P09-T03 adapters + Worker + Core: **10 PASS**, Ruff PASS e Mypy direcionado PASS. Evitar duplicar `AlertRegistry` V2-13 ou inventar estado de saúde. A PR #209 segue Draft/sem merge.

### CHECKPOINT STAGING — PR #207 merge/deploy (2026-10-16)

- **GitHub CURRENT:** PR #207 MERGED, `main=e4ffd584c4bc66632e80d1ab1448cdb67cd914ea`, pré-merge CI #984 SUCCESS e Governança #405 SUCCESS. Pós-merge Governança `38943329740` SUCCESS; CI pós-merge `38943329765` ainda em execução na última consulta.
- **Railway autorizado (projeto explicitamente STAGING):** `FM NFCORE Staging` id `b84b290d-f3b4-46a1-9023-0b761cb96b0d`, environment interno `production` id `c9878b9b-62b2-4a97-b8ba-743c8a3e99ec` **NÃO É PRODUÇÃO COMERCIAL**. Deploys apenas API `273731b9-00e2-44dd-b10e-99b058fec7d6` e Worker `a4f48d68-3fe5-449a-9bac-37df6869b77a`, ambos SUCCESS no exato commit `e4ffd584`; Portal não alterado. Sem migrations, ativação fiscal real ou credenciais novas.
- **Prova operacional staging:** `GET https://nfcore-api-production.up.railway.app/health/ready` HTTP 200 `status=ready`, `reason=ready`. Railway tracing coverage após deploy: API 2 spans internos `nfcore.runtime` e Worker 100 spans internos `nfcore.runtime` na janela observada (valores dependem da janela). Traces exemplares: API `db.readiness` trace `4f425bf28767c21b9f456e4fb787594d`, scope `nfcore.runtime`, `nfcore.outcome=ok`, deployment API confirmado; Worker `db.outbox_counts` trace `e376fc117457dd5f7b32a49d02c09a28`, scope `nfcore.runtime`, `nfcore.outcome=ok`, deployment Worker confirmado; Worker também exporta `worker.cycle`. Requisição `e5961630e4483efb7217d2c7d0ee8446` correlaciona edge/proxy + spans HTTP SERVER da API pelo tracer nativo.
- **Classificação rigorosa:** lacuna anterior "nenhum span interno API/Worker" agora RESOLVIDA. Ainda **NÃO COMPROVADOS** spans explícitos de chamada externa do webhook nem E2E operacional de cada provedor fiscal; `SafeTracer` emite spans de operações por trace independente, e não foi certificada árvore distribuída completa para todas as operações. `get_tracing_coverage.systems=[]` nos spans manuais dessa amostra; não declarar DB CLIENT instrumentado pelo driver. P09-T01 NÃO recebe `[x]` sem todos critérios, P09-T02 NÃO recebe `[x]` por cobertura parcial dos providers/CI pós-merge pendente.
- **Gate seguinte:** confirmar CI pós-merge #38943329765; matriz P09-T01/T02 item por item, sem repetir P05, antes de promoção de estados. Não criar outro deploy, secret ou migration neste checkpoint.

### DECISÃO APROVADA — concluir produto interno antes da homologação fiscal externa (2026-10-16)

- Determinação expressa do proprietário: **continuar o desenvolvimento e entregar o NFCore funcional para testes de campo**, sem esperar contabilidade, certificação/homologação oficial, certificados reais, credenciais SEFAZ/prefeituras/providers, execução fiscal real ou operação externa de terceiros. Essas provas ficam `BLOCKED_EXTERNAL` / `PENDING_FIELD_VALIDATION`, sem falsear `CERTIFIED` ou marcar `[x]` por simulação.
- **Gate de engenharia mantido:** código CURRENT, contrato canônico, segurança, RBAC/tenant, testes unitários/integrados/simuladores determinísticos, Ruff/Mypy, frontend, E2E local, Docker, CI, observabilidade interna e builds. Falhas internas não passam a `BLOCKED_EXTERNAL`; devem ser corrigidas antes da próxima fase.
- **Escopo da decisão:** testes reais fiscais/contabilidade e dependências de terceiros apenas; testes internos e smoke do staging controlado **continuam obrigatórios** quando independem dessas credenciais. A ausência de chamadas externas fiscais reais NÃO é blocker para implementar P09-T03 e fases internas seguintes; documentar dívida de homologação separadamente. Tracing externo real não deve ser alegado nem confundido com instrumentação interna provada no staging.
- **Estado:** PR #207 MERGED `e4ffd584c4bc66632e80d1ab1448cdb67cd914ea`; CI pós-merge `38943329765` SUCCESS, governança SUCCESS, API/Worker Railway staging SUCCESS, readiness HTTP 200 e spans reais de API/Worker. PR #208 de checkpoint documental ainda Draft/CI em andamento. Próxima ação: reconciliar critérios P09-T01/T02 em duas linhas (entrega interna comprovada vs validação externa diferida) e avançar no primeiro bloco interno elegível do cronograma; não mudar a ordem de 59 tarefas sem registrar justificativa.
- **Autorizações preservadas:** esta diretriz NÃO autoriza produção comercial, ativação fiscal real, migração produtiva, criação de segredo/credencial real, DNS/cutover ou deploy/merge não especificamente autorizado.

### RECONCILIAÇÃO DE ACEITE INTERNO P09-T01/T02 — 2026-10-16

**Decisão aprovada:** testes fiscais reais e homologação com contabilidade serão executados depois da entrega interna do produto, registrados `PENDING_EXTERNAL_HOMOLOGATION`; isso não bloqueia P09-T03 ou novos blocos internos. A decisão não dispensa teste técnico, controle de tenant, auth, segurança, CI ou prontidão Web.

**P09-T01, EVIDÊNCIA INTERNA:** PR #206 integrada (`9045873`), CI pós-merge e Governança verdes; SDK OTLP e transporte HTTP/protobuf local provados; API e Worker Railway Staging implantados no `e4ffd584` (PR #207), ambos SUCCESS; API `GET /health/ready` 200. Railway confirmou spans próprios `http.request`, `db.readiness`, `worker.cycle`, `db.outbox_counts` (scope `nfcore.runtime`), não apenas edge. Instrumentação `external.webhook` existe no wrapper canônico da Worker. Ausência de prova de chamada externa oficial e de árvore distribuída completa fica `PENDING_EXTERNAL_HOMOLOGATION`/lacuna operacional específica, sem atribuir sucesso fictício.

**P09-T02, EVIDÊNCIA INTERNA:** `nfcore_http_requests_total`, latência, `nfcore_commercial_events_total`, fulfillment, activation, `nfcore_worker_backlog_jobs`, retry/dead-letter, métrica de erro de gateway NFC-e, rejeição e reconciliação fiscal produzidas nos componentes canônicos; implementações integradas na PR #207 (`e4ffd584`); CI pós-merge #38943329765 SUCCESS, Governança SUCCESS. Testes dirigidos reexecutados em Windows com `PYTHONPATH=src`: **11 PASS** para OTLP sink/SDK, DB readiness, webhook, HTTP, reconciliação fiscal e fulfillment. Cobertura de todos os providers fiscais e operação com credenciais/certificados oficiais permanece `PENDING_EXTERNAL_HOMOLOGATION` ou cobertura ainda não comprovada; não confundir handler opcional com produção fiscal real.

**Classificação formal:** engenharia interna T01/T02 com evidências de implementação/testes/staging; pendências externas segregadas, porém os checkboxes do cronograma **não foram alterados nesta PR documental**, pois o aceite original exige provas de external calls e todos os producers. É necessária uma decisão expressa de governança para reinterpretar o checkbox global como `INTERNAL_COMPLETE_EXTERNAL_PENDING`; essa decisão do proprietário é a separação de entregas, não certificação fictícia. Próximo bloco de código interno: PR #209 — P09-T03 Alerts, independente de contabilidade.

### GATE DE CHAMADA EXTERNA CONTROLADA P09-T01 — 2026-10-16

- Novo teste `tests/test_nfv1_p09_t01_external_trace_controlled.py` exercita o adaptador canônico `_TracedWebhookTransport` com porta externa *mockada*, sem sair para internet nem usar certificados reais: erro de conexão é preservado; existe exatamente um trace `external.webhook`, `outcome=error`, atributos vazios; a chamada do delegate acontece somente uma vez. **1 PASS**, Ruff PASS, validador 59 IDs PASS.
- Isso fecha a *prova interna controlada de emissão de span para chamada externa*; NÃO significa webhook entregue em endpoint real, provider homologado nem trace ponta a ponta com certificado. Resultado interno de tracing somado a SDK OTLP, DB e Worker já demonstrados; separar `INTERNAL_EVIDENCE_COMPLETE` de `EXTERNAL_HOMOLOGATION_PENDING` sem alterar checkboxes globais pelo simples teste.

### FECHAMENTO DO BLOCO INTERNO P09-T01/T02 — DECISÃO DE ACEITE 2026-10-16

**NFV1-P09-T01 — `INTERNAL_COMPLETE` (nível construção/validação controlada).** API HTTP spans, DB readiness, Worker cycle/DB outbox, export OTLP com SDK real e prova local de transporte OTLP, testes de external.webhook com mock seguro e staging API+Worker no SHA correto: evidências suficientes para o *escopo interno*. **`EXTERNAL_HOMOLOGATION_PENDING`**: rastreamento distribuído com integrações reais, certificados/providers oficiais e dados de campo. Não declarar provider homologado.

**NFV1-P09-T02 — `INTERNAL_COMPLETE` (nível construção/validação controlada).** Produtores existentes de HTTP/error/latency, commercial events, fulfillment, worker backlog/retries/dead-letter, erro de gateway NFC-e, rejeição NFC-e, reconciliação fiscal/Cakto e activation; 31 testes dirigidos PASS cobrindo subset de contratos T01/T02; CI da PR #207 pré/pós-merge SUCCESS. **`EXTERNAL_HOMOLOGATION_PENDING`**: cobertura de cada integração fiscal real configurada em campo e aferição de volumes/limiares em tráfego verdadeiro. Não afirmar certificação operacional de toda família fiscal/provider sem runtime correspondente.

**Regra de status:** `INTERNAL_COMPLETE` não equivale a `PRODUCTION_APPROVED`, `EXTERNAL_CERTIFIED` ou check global `[x]`; testes reais permanecem em registro externo separado. O próximo bloco interno é P09-T03, já aberto na PR #209; ele deve seguir sem reabrir P09-T01/T02, salvo regressão comprovada. A PR #208 ainda é draft e sua CI no HEAD exato precisa concluir verde antes do merge autorizado.
