# FM NFCORE V1 — Ledger da trilha BUILD-ONLY

**Estado:** EM_EXECUCAO (trilha subordinada ao cronograma mestre de 59 IDs).  
**Decisão:** autorização explícita do proprietário em 18/10/2026 para construir/corrigir autonomamente e **mergear PRs BUILD-ONLY 100% verdes**, preservando decisões humanas para credenciais, custos, preço, segurança nova, deploy, produção e atos irreversíveis.  
**Cronograma de escopo:** `docs/NFCORE_V1_BUILD_INTEGRATION_EXECUTION_2026-10-18.md` — anexo, **não substitui** `docs/NFCORE_V1_EXECUTION_LEDGER.md`.  
**Próximo bloco executável:** `NFV1-BLD-03`.  
**Última reconciliação:** main `aa04c8b2b63384880e3d6a98f41771b2f0415c8f`; PRs #253/#254/#255/#258 integradas com CI e Governança pré/pós-merge SUCCESS. BLD-02 DONE no escopo BUILD interno; prova completa em `docs/checkpoints/NFV1_BLD02_INTERNAL_CLOSEOUT_2026-10-27.md`. Próximo BLD-03; publicação e homologação continuam em gates separados.

## Semântica de estado e prova

- `PENDING`: não iniciada/sem prova completa.
- `IN_PROGRESS`: existe PR ativa ou trabalho de auditoria efetivo, no máximo 1 bloco principal simultâneo.
- `BLOCKED_HUMAN_ACTION`: falta sessão/decisão específica; continua aberta e pode permitir **somente** tarefas internas independentes explicitadas.
- `BLOCKED_EXTERNAL`: depende de infraestrutura/terceiro, não pode virar PASS sem evidência.
- `DONE`: somente após PR(s) mergidas, `CI+Gov SUCCESS` no SHA exato, CI/Gov pós-merge SUCCESS, verificação de delta funcional e aceite definido no anexo; refs obrigatórias.
- `ALREADY_INTEGRATED`: implementação já existente e aceita com **PR/SHA/CI reais do CURRENT**; encerra bloco sem repetição de código, com evidência específica.
- `CONSTRUCTION_AND_WEB_INTEGRATION_COMPLETE` só é permitido após todos os blocos terminados e execução Web na revisão liberada. Merge de código não equivale a deploy.

Cada `Evidência` abaixo é levantamento de baseline, **não certificação do bloco**. Registrar PR, SHA e CI por item concluído. Alterações de site devem citar PR em `fm-site-novo`. Se uma PR falhar, consertar a causa no mesmo bloco. Nenhum avanço por checkpoint inventado.

## Blocos (ordem de execução)

### NFV1-BLD-00 — Inventário integral de paridade
- **Estado:** DONE
- **Depende de:** docs/NFCORE_V1_BUILD_INTEGRATION_EXECUTION_2026-10-18.md §4 BLD-00
- **CURRENT:** main 44cddbabb4e91b55dcc730e6976fcc2ce7f00d75 CI #1054/Gov #475 SUCCESS; checkpoint NFV1_WEB_PARITY_AND_FUNCTIONAL_INTEGRATION_2026-10-18.md histórico. Falta auditoria **completa de todas as ações** no CURRENT e matriz de gaps.
- **Target e aceite:** seção `NFV1-BLD-00` do anexo de execução.
- **Evidência final:** PR #226, HEAD `f42bc2f0916c0385b752d240028023979f9fa182`, CI #1062 SUCCESS / Gov #483 SUCCESS; merge SHA `b15527e725213c3c1cb848692306a95dd7c240df`, CI #1063 SUCCESS / Gov #484 SUCCESS (mesmo SHA); matriz `docs/checkpoints/NFV1_BLD00_CURRENT_FUNCTIONAL_PARITY_2026-10-19.md`, 26 áreas navegacionais, 2 ações especiais, gaps e limites de evidência explícitos. Sem deploy/produção/homologação.
- **Pendência / decisão humana:** se surgir, registrar o bloqueio exato com decisão necessária, sem gerar novo serviço, preço ou credencial.

### NFV1-BLD-01 — Identidade, onboarding e Portal operacional
- **Estado:** DONE
- **Depende de:** BLD-00 certificado (PR #226/#227).
- **CURRENT:** Sessão/login/logout, recuperação/ativação, onboarding e múltiplas unidades, usuário/OWNER e RBAC/CSRF/tenant já implementados no Portal e APIs canônicos, conforme testes dirigidos e matriz BLD-00. Sem segundo login. Deltas corrigidos nas PRs #228 (confirmação de usuários), #229 (respostas assíncronas antigas na navegação) e #230 (ação fiscal condicionada ao escopo autorizado).
- **Target e aceite:** seção `NFV1-BLD-01` do anexo de execução. Conclusão refere-se ao BUILD interno integrado, não a deploy, browser E2E atual de todos os papéis ou homologação externa.
- **Evidência final:** PR #228 merge SHA `74089d694b50f4809810e34e9fed6899a68c37e1`, CI #1067/Gov #488 e CI pós-merge #1068/Gov #489 SUCCESS; PR #229 merge SHA `8e07fa534d7fb488930b9e07e174363036635d53`, CI #1069/Gov #490 e CI pós-merge #1070/Gov #491 SUCCESS; PR #230 HEAD `e292a1b6f6d2a7bac2ac16fef706292045a37656`, merge SHA `caf9c8278c469d1b87aa15b49c73f824d2eda430`, CI #1071/Gov #492 e CI pós-merge #1072/Gov #493 SUCCESS. Provas: `tests/frontend/portal_contract.test.js`, `tests/e2e/portal.spec.js`, `tests/web/test_human_auth_routes.py`, `tests/runtime/test_p02_t04_users_rbac.py`, `tests/web/test_portal_api.py`, `docs/checkpoints/NFV1_BLD00_CURRENT_FUNCTIONAL_PARITY_2026-10-19.md`. Navegação Web publicada na revisão mais recente ainda não demonstrada; BLD-08 guarda essa evidência.
- **Pendência / decisão humana:** nenhuma nova para concluir este bloco de BUILD interno; deploy, testes reais no browser/staging e homologação ficam em seus gates próprios.

### NFV1-BLD-02 — Paridade fiscal Web e executores internos
- **Estado:** DONE
- **Depende de:** BLD-00 e BLD-01
- **CURRENT:** Construção interna integrada: consultas/arquivo, preparação NF-e/NFC-e/NFS-e, emissão e recuperação duráveis, cancelamento vinculado ao documento, inutilização/evidência, projeções de erros/pendências e configurações governadas. Portal usa autoridades existentes e bloqueia dependências ausentes. Publicação Web e homologação externa não certificadas.
- **Target e aceite:** seção NFV1-BLD-02 do anexo; ações internas com estado real ou bloqueio explícito. DONE é exclusivamente BUILD interno, não produção fiscal nem conclusão global das 59 tarefas.
- **Evidência final:** PR #253/#254/#255/#258; HEAD final 84e3345f284d653756ae046233a0137fde51cd50, merge aa04c8b2b63384880e3d6a98f41771b2f0415c8f; CI SUCCESS (40530810061), Governança SUCCESS (40530809955), CI pós-merge SUCCESS (40533251021), Governança pós-merge SUCCESS (40533250901). 2563 Python PASS/3 SKIP, 36 E2E PASS e 18 frontend PASS na candidata. Matriz por capacidade e demais SHAs em docs/checkpoints/NFV1_BLD02_INTERNAL_CLOSEOUT_2026-10-27.md; #256/#257 substituídas pela integração consolidada.
- **Pendência / decisão humana:** Provider/jurisdição, credenciais/certificados, transporte oficial e homologação permanecem externos/BLD-05. Publicação autorizada e demonstração do staging pertencem a BLD-08. Timeout/evento pendente exige evidência confiável, nunca reenvio ou protocolo inventado. Contrato legado sem document_id não recebe a certificação de lifecycle da jornada Web.

### NFV1-BLD-03 — Trial first-party no NFCore e site estático
- **Estado:** PENDING
- **Depende de:** BLD-00 e interfaces de identidade BLD-01; código interno pode avançar se sessão admin/config comercial bloquearem operações
- **CURRENT:** GovernedTrialService, ingresso público protegido, catálogo e antiabuso PostgreSQL já existem no código auditado. Página de cadastro na aplicação NFCore é o próximo delta Web; binding admin, configuração comercial/origens e Web publicada não estão certificados. Auditar PR #237 antes de reaproveitar testes; não reconstruir serviços nem inventar plano/preço/duração.
- **Target e aceite:** seção `NFV1-BLD-03` do anexo de execução.
- **Evidência final:** PENDENTE (registrar PR + HEAD + merge SHA + CI/Gov PR e main + prova funcional apropriada).
- **Pendência / decisão humana:** se surgir, registrar o bloqueio exato com decisão necessária, sem gerar novo serviço, preço ou credencial.

### NFV1-BLD-04 — Comercial interno e integração Command
- **Estado:** PENDING
- **Depende de:** BLD-03 contratos, ou interfaces canônicas já verificadas; não ativar pagamentos
- **CURRENT:** Pricing/release e aquisição/fulfillment internos existentes; catálogo/release/checkout de runtime sem readiness. Backend multi-tenant é autoridade; simular somente entrada de provedor em testes.
- **Target e aceite:** seção `NFV1-BLD-04` do anexo de execução.
- **Evidência final:** PENDENTE (registrar PR + HEAD + merge SHA + CI/Gov PR e main + prova funcional apropriada).
- **Pendência / decisão humana:** se surgir, registrar o bloqueio exato com decisão necessária, sem gerar novo serviço, preço ou credencial.

### NFV1-BLD-05 — Fiscal adapter/contratos para homologação futura
- **Estado:** PENDING
- **Depende de:** BLD-02 + scope de adapter revisado
- **CURRENT:** Provider transport real não está configurado. Não criar fake em runtime. Aprovação humana necessária para provedor/jurisdição específicos, porém infraestrutura neutra pode avançar.
- **Target e aceite:** seção `NFV1-BLD-05` do anexo de execução.
- **Evidência final:** PENDENTE (registrar PR + HEAD + merge SHA + CI/Gov PR e main + prova funcional apropriada).
- **Pendência / decisão humana:** se surgir, registrar o bloqueio exato com decisão necessária, sem gerar novo serviço, preço ou credencial.

### NFV1-BLD-06 — Persistência e Worker das jornadas Web
- **Estado:** PENDING
- **Depende de:** BLD-02/BLD-04/BLD-05 contratos relevantes
- **CURRENT:** Worker staging online e DB existem, mas prova de outbox externo não é construção interna. Reusar Worker, idempotência e recovery existentes; corrigir somente wiring faltante.
- **Target e aceite:** seção `NFV1-BLD-06` do anexo de execução.
- **Evidência final:** PENDENTE (registrar PR + HEAD + merge SHA + CI/Gov PR e main + prova funcional apropriada).
- **Pendência / decisão humana:** se surgir, registrar o bloqueio exato com decisão necessária, sem gerar novo serviço, preço ou credencial.

### NFV1-BLD-07 — Conectar site novo e jornada NFCore
- **Estado:** PENDING
- **Depende de:** BLD-03 ingresso seguro e catálogo quando aprovado; separar canal interno de liberação pública
- **CURRENT:** Site novo faabio3131/fm-site-novo PR #10 integrou acesso Portal. Trial Web comercial ainda não disponível; Next.js PR #33 legada fechada SEM merge.
- **Target e aceite:** seção `NFV1-BLD-07` do anexo de execução.
- **Evidência final:** PENDENTE (registrar PR + HEAD + merge SHA + CI/Gov PR e main + prova funcional apropriada).
- **Pendência / decisão humana:** se surgir, registrar o bloqueio exato com decisão necessária, sem gerar novo serviço, preço ou credencial.

### NFV1-BLD-08 — Aceite de construção e entrega demonstrável na Web
- **Estado:** PENDING
- **Depende de:** BLD-00 a BLD-07 sem lacunas de código/wiring não resolvidas
- **CURRENT:** Sem prova de CONSTRUCTION_AND_WEB_INTEGRATION_COMPLETE. CI green isolada não prova todas as superfícies disponíveis.
- **Target e aceite:** seção `NFV1-BLD-08` do anexo de execução.
- **Evidência final:** PENDENTE (registrar PR + HEAD + merge SHA + CI/Gov PR e main + prova funcional apropriada).
- **Pendência / decisão humana:** se surgir, registrar o bloqueio exato com decisão necessária, sem gerar novo serviço, preço ou credencial.

## Checkpoint permanente de execução

Para cada PR BUILD usar este registro, preenchido **depois** das provas:

```text
Data UTC:
Bloco:
Base main / SHA:
Autoridade reutilizada:
Current -> Target (delta concreto):
Branch / HEAD:
PR:
Testes dirigidos e resultado:
CI PR / Governança PR (mesmo SHA):
Aprovação automática de merge aplicável? [sim/não + motivo]:
Merge SHA:
CI main / Governança main:
Estado no staging (se houve deploy autorizado):
Evidência Web/API/PostgreSQL:
Pendências internas / externas / decisões humanas:
Próximo bloco:
```

## Backlog de homologação e produção: preservado, não confundido

P05-T03/T04/T05 **provas operacionais adicionais**, P08 canal de pagamento real, P09-T04 rotina periódica/retention/RPO/RTO de produção, P09-T05 runbooks finais, P10 homologação oficial, P11 infra definitiva, P12 certificação/Go-No-Go. Backup/restauração isolados **já realizados** em 12/10/2026; não reexecutar só para satisfazer checklist. Nenhum cliente real ou produção comercial ativa neste estágio.

### BLD-02 — emissão preparada com autoridade durável (26/10/2026)

Base confirmada: `364bd2822222db596173e822aadc62bb4c2733b4`, CI #1158 e
Governança #579 SUCCESS. Escopo BUILD-ONLY: ligar requests já preparados de
NF-e/NFC-e/NFS-e aos gateways existentes com claim transacional antes do I/O,
resultado terminal acoplado à tentativa correta e recuperação sem reenvio
após timeout/crash. `FiscalApplicationService` e `CanonicalFiscalOperationPath`
continuam sendo autoridades únicas. Handler opt-in exige resolver confiável
para documento preparado; payload Web não fornece XML/resultado/credencial.
A chave HTTP/UUID do intent permanece distinta da chave fiscal canônica.

Estado: IMPLEMENTED_NOT_CERTIFIED; BLD-02 permanece IN_PROGRESS. Testes dirigidos
iniciais: 21 PASS; teste PostgreSQL depende do serviço descartável de CI.
Ruff e Mypy de 225 fontes PASS no levantamento local. PR #245 aberta em Draft; CI do HEAD final pendente.
Sem migration, deploy, mudança de production ou provider real. Permanecem
pendentes a composição da preparação/assinatura por família, UI de emissão,
reconciliação de evidência externa confiável e certificação integral BLD-02.
Não confundir este caminho de emissão preparada com a jornada V1 concluída.


### BLD-02 — preparação NFC-e durável e pedido recuperável (26/10/2026)

Gate da PR #245 confirmado: HEAD `4d1c7ab0f701bfc4af6fa21501983b0f526eedb5`,
CI #1162/Gov #584 SUCCESS; merge `cf1896c07b3be952678f5ced34988133513467a7`,
CI pós-merge [#1163](https://github.com/faabio3131/nf-core-v001/actions/runs/40371609336)
e Gov #585 SUCCESS. Substitui o estado provisório do checkpoint anterior.

Incremento em `feat/nfv1-bld02-preparation-recovery-20261026`: o orquestrador NFC-e
existente aceita a autoridade persistente, reserva numeração nela e conserva as
transições de validação/assinatura. Pedido XML assinado e READY_TO_TRANSMIT são
gravados atomicamente no arquivo fiscal existente; o resolver recupera o pedido
por escopo após reinício. Retenção vem da composição, sem política legal inventada.
Artefato preparado usa OTHER, nunca AUTHORIZED_XML antes de autorização.

20 testes de orquestração PASS, incluindo reinício em autorizado/rejeitado/pendente,
crash antes do envio, timeout sem reenvio, isolamento e rollback de arquivo+lifecycle.
Ruff global e Mypy de 225 fontes PASS; validadores de plano/BUILD PASS.
CI remota deste incremento ainda pendente; BLD-02 permanece IN_PROGRESS.
Sem migration/deploy/provedor real. Faltam preparação completa das outras famílias,
composição/UI e reconciliação confiável de resultados; números reservados antes de
falha de preparação não são reutilizados automaticamente. Próximo delta: recuperar
resultado por consulta validada ao provedor, sem retransmissão.

### BLD-02 — reconciliação de autorização por consulta validada (26/10/2026)

Incremento dependente da preparação da PR #246, mantido em branch isolada
`feat/nfv1-bld02-provider-reconciliation-20261026`; integração condicionada aos
gates pré/pós-merge da predecessora e aos gates deste HEAD.
`FiscalApplicationService` recupera o pedido arquivado, consulta exclusivamente
`FiscalOperationsClient` configurado e grava evidência normalizada + autorização
+ tentativa na mesma UOW. Pendente/não encontrado/cancelado sem protocolo de
cancelamento não concluem nem reenviam emissão. Resultado terminal concorrente
não é sobrescrito. Handler canônico de reconciliação aceita somente referência;
nenhum resultado, XML ou seleção de provedor vem do navegador.

Testes dirigidos: 52 PASS/1 SKIP local (PostgreSQL), incluindo resposta incompatível,
timeout, rollback de evidência e concorrência de resultado terminal. Teste
PostgreSQL isolado existente ampliado para arquivo e recuperação por consulta;
prova efetiva depende da CI. Ruff e Mypy global/validadores de plano e BUILD PASS.
Estado IMPLEMENTED_NOT_CERTIFIED; BLD-02 IN_PROGRESS. Sem deploy/migration real,
credencial, decisão de provider ou emissão oficial. Próximo delta interno:
formulários de emissão preparada/reconciliação no Portal e composição explícita.

### BLD-02 — Portal para documentos preparados (26/10/2026)

PR #246 integrada: HEAD `30fae0e760002217744ba5a605dbd7d21c984ecc`, CI #1164/Gov
#586 SUCCESS; 2483 Python PASS/3 SKIP e 31 E2E PASS. Merge
`4bb9616ad6b03415f47ff6b8f456a7e740d67f2c`, pós-merge #1165 iniciado. Suíte
completa local também terminou sem falhas. PR #247 de reconciliação em Draft,
HEAD `e1bda2cb4c909d5cafdc28c094c1c8bcba098df8`, CI #1166 em execução;
Governança #589 SUCCESS. Nenhum deploy.

Incremento Portal dependente da #247: emissão preparada/reconciliação recebem
campo document_id e ocultam JSON; mantêm escopo autorizado, CSRF, intent e chave
HTTP originais. Recibo continua distinto de confirmação fiscal; resultado deve
ser consultado na projeção durável de Emissões. Teste browser adiciona jornada
real local HTTP/auth/intent/SQLite/reconciliação; só fronteira provider é sintética.
Teste HTTP local executado com sucesso até lifecycle autorizado. Testes frontend
18 PASS, lint/typecheck/build e Ruff/validadores PASS. Chromium local indisponível
por download inválido; E2E completo obrigatório na CI, sem desabilitação de testes.
BLD-02 continua IN_PROGRESS e integração exige gates das predecessoras e do HEAD.
### BLD-02 — preparação compartilhada NF-e/NFC-e e identidade NFS-e (26/10/2026)

Gate da #246 confirmado: merge `4bb9616ad6b03415f47ff6b8f456a7e740d67f2c`, CI
pós-merge #1165/Gov #588 SUCCESS. PR #247 integrada após CI #1166/Gov #589
SUCCESS, merge `f262ecade6b45da3267a3b4742bca3a1714f8acd`; pós-merge #1168 em
execução e Gov #591 SUCCESS. Portal #248, HEAD
`2b7af5ac827f0518b9e96209f7c097225a70a6dc`, CI #1167 em execução/Gov #590 SUCCESS.

Incremento na mesma autoridade de preparação: NF-e/modelo55 e NFC-e/modelo65
usam uma sequência comum de validação, numeração, assinatura e persistência,
com comandos e entradas que rejeitam família incompatível antes de efeitos.
Nomes públicos NFC-e preservados; numeração continua particionada por modelo.
NF-e usa propósito de assinatura nfe_xml e o pedido recuperado passa no envelope
NF-e existente. Nenhum XML builder/schema/provider fictício foi ligado ao runtime.

Lacuna concreta corrigida em NFS-e: identidade/fingerprint e vínculo do emitente
passam a incluir host_namespace, conforme contrato existente das outras famílias.
Hashes legados sem namespace preservados por regressão com valores conhecidos.
Identidades NFS-e com namespace mudam; não há migração automática de registros.
Isso não implementa nem certifica transporte/preparação municipal NFS-e.

Testes dirigidos issuance/XML/autorização durável: 79 PASS/1 SKIP PostgreSQL local;
37 casos de orquestração, incluindo modelo55 e isolamento de família/numeração.
Ruff global, Mypy 225 fontes e validadores plano/BUILD PASS. CI completa pendente.
BLD-02 IN_PROGRESS; merge exige gates anteriores e do HEAD. Próximos deltas:
preparação/recuperação NFS-e e composição explicitamente configurada; nenhuma
homologação, emissão oficial, deploy ou migration produtiva foi autorizada aqui.

Complemento do incremento compartilhado: `build_provider_operation_handlers`
reutiliza os handlers de emissão preparada e reconciliação quando recebe
explicitamente aplicação durável, gateway XML e retenção. Configuração parcial
falha fechada; uso antigo somente com cliente mantém consulta/cancelamento/
inutilização. Teste atravessa o mesmo OperationPath e a mesma persistência para
emitir pendente, reconciliar e repetir sem novo envio. Suite dirigida ampliada:
86 PASS/1 SKIP local; Ruff/Mypy PASS. A CI #1169 anterior ficou SUCCESS, mas este
acréscimo exige nova CI no novo HEAD antes de merge.

Gate #247 confirmado: pós-merge #1168/Gov #591 SUCCESS no merge
`f262ecade6b45da3267a3b4742bca3a1714f8acd`. #248 integrada após CI #1167/Gov #590
SUCCESS; merge `2f60be6d8ba6c9496e1cb1316c3cb047019acd42`, pós-merge pendente.
Estado continua IN_PROGRESS; nenhuma promoção fictícia do BLD-02 ou BLD-08.

Correção adicional por falha reproduzida no HTTP: uma referência preparada
inexistente retornava 200 no prepare, 500 no resume e 409 na repetição, deixando
um intent sem execução real preso. Preflight read-only nos handlers canônicos
agora valida permissão/escopo/referência antes de persistir o intent. Erro
normalizado INVALID_PREPARED_DOCUMENT (400), sem revelar outro escopo; correção
do campo pode prosseguir. UI descarta somente a tentativa de prepare rejeitada
com 400; falha de rede ou intent já existente conserva a identidade original.

Quatro regressões HTTP reais locais cobrem referência inexistente, outras
unidades/tenants, permissão antes da leitura e correção até autorização durável.
Suite dirigida HTTP/runtime: 45 PASS/15 SKIP PostgreSQL local; frontend 18 PASS,
lint/typecheck/build e Ruff/Mypy globais PASS. E2E de reconciliação ampliado com
referência inválida seguida da correção. HEAD anterior não certifica este delta;
exige nova CI completa antes de merge. Pós-merge #248 confirmado: #1170/Gov #593
SUCCESS no SHA `2f60be6d8ba6c9496e1cb1316c3cb047019acd42`. BLD-02 segue aberto.

### BLD-02 — preparação e recuperação durável NFS-e (27/10/2026)

Base `9d33e531b1885b42c817720d1786616cebd1b722`, com PR #249 integrada e
CI pós-merge #1179/Gov #602 SUCCESS. Incremento em construção na branch
`feat/nfv1-bld02-nfse-preparation-20261027`: pedido canônico NFS-e passa a ser
reservado, validado, arquivado e levado a READY_TO_TRANSMIT na mesma UOW, antes
de qualquer I/O externo. O artefato usa codec JSON estrito, conteúdo endereçado,
recalcula idempotência/fingerprint ao recuperar e não inclui segredo, resposta
de provedor nem falsa autorização.

`FiscalApplicationService` recupera exatamente um pedido preparado após reinício,
preserva namespace/tenant/unidade/ambiente e rejeita escopo divergente. A factory
canônica aceita gateway NFS-e explicitamente configurado e seleciona o transporte
pelo tipo validado do pedido; configuração parcial permanece fail-closed. Retry
de autorização pendente não reenvia o pedido. Nenhum município/provider foi
selecionado e nenhuma emissão externa, credencial, migration ou deploy ocorreu.

O mesmo incremento adiciona contrato `NfseQueryClient` estritamente read-only.
Após timeout/pending, a reconciliação consulta o pedido arquivado, valida escopo,
documento, idempotência e fingerprint e grava a evidência normalizada junto da
transição terminal. AUTHORIZED e REJECTED finalizam lifecycle e tentativa na
mesma UOW; PENDING permanece TRANSMITTING e nunca provoca reenvio. Resposta
incompatível ou resultado terminal concorrente falham fechado.

Testes dirigidos de NFS-e, emissão durável e wiring passaram com um SKIP PostgreSQL
local esperado; Ruff PASS, Mypy PASS em 224 fontes e validadores plano/BUILD PASS.
CI/Governança do HEAD remoto ainda obrigatórias. BLD-02 permanece IN_PROGRESS:
um adapter municipal/nacional concreto continua dependendo de decisão humana e
homologação futura; cancelamento/inutilização/consulta genéricos continuam
disponíveis somente quando `FiscalOperationsClient` real é explicitamente composto.

### BLD-02 — fechamento Web das operações fiscais internas (27/10/2026)

O diálogo governado do Portal deixou de exigir edição de payload JSON para as
operações fiscais do launch scope. Consulta e cancelamento agora coletam chave de
acesso em formato fiscal; cancelamento também exige protocolo de autorização e
justificativa. Inutilização recebe modelo, série, faixa e justificativa tipados,
além do formulário dedicado já existente. Emissão e reconciliação continuam
aceitando somente a referência de um documento preparado pelo backend.

O navegador segue sem autoridade de tenant, papel ou resultado fiscal: unidade e
ambiente vêm do escopo autorizado, mutações preservam CSRF, intent durável e chave
de idempotência, e o backend continua validando todos os contratos. A interface
não habilita operação sem permissão e executor compostos, nem interpreta recibo
HTTP/fila como protocolo oficial. Não houve provider, credencial, deploy ou
ativação de produção.

Provas locais deste delta: contrato frontend 18 PASS; handlers de consulta,
cancelamento, inutilização, wiring e NFS-e 20 PASS; Node syntax, Ruff global,
Mypy em 226 fontes e diff check PASS. Lint/typecheck/build/E2E frontend completos
dependem da instalação Node feita pela CI; nenhuma ausência local será tratada
como aprovação. O HEAD remoto atualizado ainda precisa de CI e Governança verdes.

### BLD-02 — continuidade integrada e retorno fiscal visível (27/10/2026)

PR #253 integrada: HEAD `d4aa0bb88c9545d8303942bb799b11a39a9516b9`, CI #1183
(`40518036563`) e Gov #606 (`40518036451`) SUCCESS. Merge
`e338ef40345d84a535d9e8bc8b31037f5ff59412`, CI #1184 (`40520535686`) e Gov #607
(`40520535562`) SUCCESS. NFS-e preparada/recuperável e formulários fiscais
tipados estão integrados; 32 E2E passaram na CI. Homologação externa não inferida.

PR #254 integrada: HEAD `e7156bd8df81072cacfd5188e07d56917ff3f1e0`, CI #1185
(`40521826969`) e Gov #608 (`40521826836`) SUCCESS. Merge
`4b258afe19af8b532c3a8afc8543bfb1568d11dd`. O preflight agora rejeita NFS-e
sem gateway/cliente de consulta antes de persistir o intent; regressões provam
que não há dispatch nem mudança do lifecycle. Governança pós-merge
`40524003091` SUCCESS; CI `40524003195` em andamento nesta escrita.

Delta seguinte identificado no Portal: consulta recebia resposta canônica, mas
a descartava ao fechar o diálogo. O resultado passa a exibir status, chave e
protocolo opcional como texto, sem interpretar HTML ou inferir autorização a
partir de um recibo. Mutações exibem confirmação de registro interno, distinta
de confirmação fiscal. Resposta atrasada não altera a navegação mais recente.

Lint/typecheck/build e 18 testes frontend PASS; validadores plano/BUILD PASS.
Três regressões browser cobrem consulta autorizada, pendente e não encontrada,
ausência de protocolo e texto não interpretado como markup. Execução browser
local bloqueada por download inválido do Chromium; exige E2E remoto SUCCESS.
BLD-02 permanece IN_PROGRESS. Não houve deploy solicitado, migration, provider
selecionado ou operação fiscal real. Próximo passo: CI deste delta e revisão
final da matriz BLD-02, antes de promover estado ou iniciar BLD-03.

### BLD-02 — aceite interno confirmado (27/10/2026)

Este registro prevalece sobre os checkpoints anteriores em andamento: PR #258 consolidou #256/#257, merge aa04c8b2b63384880e3d6a98f41771b2f0415c8f, CI/Governança pré e pós-merge SUCCESS. Matriz completa em docs/checkpoints/NFV1_BLD02_INTERNAL_CLOSEOUT_2026-10-27.md. Ambas as revisões intermediárias foram encerradas como substituídas, com histórico preservado. BLD-02 DONE interno; primeiro bloco aberto BLD-03. As 59 tarefas globais não foram alteradas. Nenhum deploy, credencial ou operação fiscal oficial foi solicitado.

- **Bloqueio de integração do fechamento:** a Railway confirmou auto-deploy do Portal após #258. Novos merges aguardam resolução autorizada do vínculo main→deploy, conforme AGENTS.md. Detalhes e proposta no checkpoint de fechamento; nenhuma infraestrutura alterada.
