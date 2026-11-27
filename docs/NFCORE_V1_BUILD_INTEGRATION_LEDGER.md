> **CURRENT — 26/11/2026 — T20 DONE_CERTIFIED_INTERNAL (escopo interno/sandbox); fechamento documental em revisão.** [PR #628](https://github.com/faabio3131/nf-core-v001/pull/628) MERGED em `943ca9d90b44a57a7869942b9397f2b542e04cfd`, HEAD auditado/autorizado `32e805f356d778bd41f59249daf46af627a39e38`, árvore idêntica `b9b98b769bb2d7c4c8e2811cfaa5d2810d7cbe14`. [Gemini R2](https://drive.google.com/file/d/1SNQGoDVU_55QVMYk-NGkwoAAtWmvYsSx/view) APROVADO PARA SOLICITAR MERGE (0 P0/P1/P2, 3 P3 novos não bloqueantes). CI pré-merge #45912018413, governança #45912018406 e T2 efetiva fora de Draft #45916142009 SUCCESS. [CI pós-merge #45916210955](https://github.com/faabio3131/nf-core-v001/actions/runs/45916210955) e [governança #45916210883](https://github.com/faabio3131/nf-core-v001/actions/runs/45916210883) SUCCESS no SHA real, evento push/main: 44/44 etapas, 7.277 Python PASS, 1 SKIP fora T20, 30 frontend PASS, 90 Playwright PASS, zero falhas; Ruff/Mypy (491 fontes), segurança, containers, SBOM, backup/restore e readiness aprovados. Skip `tests/runtime/test_p02_t02_fiscal_surfaces.py:389` (runtime production composition requires PostgreSQL); aviso Node 20 não bloqueante. CI concluída 21h42 BRT. T01–T20 tecnicamente certificadas no escopo implementado (20/51 entregas internas, 33 T + 18 ERP; não é prontidão comercial). A próxima tarefa é o gate interno obrigatório [#625](https://github.com/faabio3131/nf-core-v001/issues/625), cinco refinamentos T18/T19; executar após integração e CI própria desta reconciliação. T21 bloqueada até #625 resolvida e certificada; também provar exclusão da oportunidade documental `nfcore.accounting-dossier/v1` de totais econômicos. T22 bloqueada; ERP somente após T22, folha T23–T33 após ERP-15 e H01–H06 após fechamento interno. Preservar 59 IDs históricos, BLD-00–08, 18 etapas ERP, #613/#616, #593 e DoD literal Master v4.1. O XLSX Master original permanece preservado; sincronização do snapshot XLSX segue pendente (não é gate autônomo). [Issue #626](https://github.com/faabio3131/nf-core-v001/issues/626) preserva evidências e será encerrada somente após CI/governança pós-merge documental. Limites T20: apenas sandbox opt-in, sem assinatura automática, reconhecimento de crédito, homologação externa, efeito fiscal real ou validação visual Microsoft Excel; browser E2E usa transporte simulado e HTTP/PG reais são testados separadamente. Sem deploy ou alteração de produção. Os registros datados anteriores são históricos, não CURRENT.

> **CONTINUIDADE CENTRAL — histórico T19 (26/11/2026):** T19 #624 integrada em `75542dd18d7a1521a33017f80395e24285c39fe4` e certificada no escopo interno; [CI pós-merge #45746332104](https://github.com/faabio3131/nf-core-v001/actions/runs/45746332104) e governança #45746332101 SUCCESS. T20 #626 foi integrada e certificada no escopo interno pela PR #628; a próxima tarefa é #625 após fechamento documental. Consulte o [cronograma da Central](NFCORE_CENTRAL_ECONOMIA_FISCAL_EXECUTION_SCHEDULE.md), [handoff T19](NFCORE_T19_RECOVERY_LIFECYCLE_HANDOFF.md) e [handoff T20](NFCORE_T20_ACCOUNTING_DOSSIER_HANDOFF.md). #625 permanece gate interno obrigatório pré-T21; #613/#616 preservadas. Os checkpoints antigos abaixo não mudam esse CURRENT. Os 59 IDs/checkboxes, critérios do mestre, gates BUILD/produção e Master v4.1 permanecem inalterados.

> **Entrega incremental 19/11/2026 — REC-03:** verificação OCSP offline complementar à LCR, CertID exato, resposta GOOD válida, assinatura da AC emissora ou responder delegado com EKU e revogação verificadas, mount existente opt-in. Nenhum endpoint externo ativado; materiais oficiais/identidade, LTV e certificação permanecem abertos. Código/testes no mesmo commit sobre `8cc67ababe091db76cf85b04d9636995aebf0f62`, sem execução de testes, nova CI, PR ou deploy. Fonte: RFC 6960. Dossiê `docs/operations/NFCORE_NATIONAL_RECEIPT_TRUST_SIGNER_PINS.md`.

> **Entrega incremental 19/11/2026 — REC-03:** verificação criptográfica do DPS antes de POST, vínculo com fingerprint do A1 do Vault e verificação do arquivo histórico usando seu instante de observação somente para a assinatura DPS. Signatário oficial da NFS-e continua sujeito à confiança atual; não equivale a LTV/OCSP. Mudança e testes no mesmo commit desta nota sobre `22a0c7da9d2f8b334d61ed606882cbbd64e764a1`, testes não executados. Sem nova CI, PR, promoção ou deploy. Dossiê: `docs/operations/NFCORE_NATIONAL_DPS_DISPATCH_EVIDENCE.md`.

> **Entrega incremental 19/11/2026 — REC-04:** contrato de deduções ampliado às espécies NFSeMun, NFNFS, nDocFisc e nDoc do XSD de fevereiro e docFiscalOutro/docOutro do NT009, com identificação de fornecedor, escolha por perfil, fingerprint/archive e reserva por identidade e hash contra alias na mesma unidade/emitente. Código e testes no mesmo commit desta nota, sobre `04305538178a097fdccd56273201c5257b39aea8`; testes não executados por ordem de construção. Política revisada e legitimidade dos comprovantes originais continuam obrigatórias; não promover REC-04/SP22/MG20 ou homologação a DONE. Detalhes em `docs/operations/NFCORE_REVIEWED_DOCUMENTARY_DEDUCTIONS.md`. Próxima dependência: integridade criptográfica e legado, lacunas municipais e gates de aceitação. Sem nova CI, PR, deploy ou expansão.

> **CURRENT complementar — 19/11/2026:** branch `work/nfcore-closeout-20261119`, HEAD de engenharia `2224b3d0d6fca49029afa4fd41b194f65ac6562a`. As dez entregas registradas por commit em [cronograma executivo REC](audit/NFCORE_RECONCILIATION_CLOSEOUT_SCHEDULE_2026-11-17.md), [pendências CURRENT](audit/NFCORE_PENDING_REGISTER_CURRENT_2026-11-17.md) e [ledger de PRs](audit/NFCORE_PR_RECONCILIATION_LEDGER_CURRENT.md) reconciliam os avanços fiscais/municipais/Web/IRON desde 17/11. Incluem deduções documentais, reserva durável de comprovantes, DPS histórico, correção GISS, PKI e composição de release. Seis PRs Draft; zero runs na branch consolidada. Sem novo teste executado, EGM, promoção main/production, deploy ou aceite fiscal. Preservados os 59 IDs e seus checkboxes, critérios, ordem e independência dos gates BUILD/produção. As notas anteriores são históricas; não reutilizar CI de outro SHA. Não considerar SP22/MG20 completos.

---

> **ÍNDICE CURRENT — 17/11/2026:** o histórico BUILD-ONLY abaixo não é uma fotografia atual da candidata fiscal/Web. Para PRs abertas, integração #468/#498, falha temporal da CI, lacunas FIS-03/BH/SP-22/MG e gates Contabo, consultar [cronograma de reconciliação](audit/NFCORE_RECONCILIATION_CLOSEOUT_SCHEDULE_2026-11-17.md) e [inventário único](audit/NFCORE_PENDING_REGISTER_CURRENT_2026-11-17.md). Preservar os critérios/estados BUILD-ONLY sem promover por reflexo qualquer item do plano mestre de 59 IDs ou homologação fiscal.

# FM NFCORE V1 — Ledger da trilha BUILD-ONLY

> **Decisão de escopo 25/11/2026 — issue #620:** [Trilha ERP (18 etapas, gate ERP-15)](NFCORE_V1_UNIVERSAL_ERP_INTEGRATION_EXECUTION_SCHEDULE.md) é parte obrigatória da construção V1; ERP (18 etapas, gate ERP-15) estão PROGRAMADAS / NÃO INICIADAS, com execução após T22 certificada e antes da folha T23–T33. As evidências e travas próprias estão no anexo, sem alterar os IDs/estados históricos deste ledger. Nenhuma homologação externa presumida, nenhuma conclusão, merge ou deploy implícito.

> Revisão v4.1 (25/11/2026, parecer técnico): 18 entregas ERP internas (ERP-12 substituída por ERP-12A/B/C; ERP-16 exportação contábil obrigatória). ERP-12 permanece agrupador histórico, não conta como tarefa adicional. Ordem: ERP-01–11 → ERP-12A → ERP-12B → ERP-12C → ERP-16 → ERP-13 → ERP-14 → ERP-15. Marketplace incorporado ao ERP-02. T01–T18 certificadas tecnicamente no escopo interno da Central; T18 #619 integrada em `e8ded78f3b3c5bd484b8d35b1904f0db7c61f317`, HEAD auditado `b2d682da66f62fcbe50c8b2465f1e5e1e8182c0a`, CI pós-merge #45696838699 SUCCESS (7.215 Python PASS, 1 skip, 87 E2E, 44/44 etapas) e governança #45696838637 SUCCESS. Atualização factual de 26/11/2026: #621 integrada e certificada; T19 #624 integrada em `75542dd18d7a1521a33017f80395e24285c39fe4`, árvore idêntica ao HEAD auditado `970701f600574a86e143ef01ebede8e7cc611488`, CI pós-merge #45746332104 e governança #45746332101 SUCCESS. T19 certificada no escopo interno; T20 #626 foi integrada e certificada no escopo interno pela PR #628; fechamento documental e #625 precedem T21. #625 permanece aberta como gate interno obrigatório pré-T21/Portal/produção; #613/#616 preservadas. Não rebaixar status certificados. T22 continua gate de início da implementação ERP; durante T18–T22 só preparação não invasiva (inventário documental, leitura de contratos, desenho de fixtures), sem iniciar tarefa formal, modificar branches concorrentes ou integrar código. Desde ERP-01–07, usar Bling como referência prática e testes de contrato desde o início; ERP-08 mantém seu gate formal após ERP-07. T23 exige T22 e ERP-15; H01 exige T33 e ERP-15. 51 entregas internas (33 T + 18 ERP) e 6 externas na planilha, sem renumerar os 59 IDs históricos de outro escopo mestre.

**Estado:** EM_EXECUCAO (trilha subordinada ao cronograma mestre de 59 IDs).
**Decisão:** autorização explícita do proprietário em 18/10/2026 para construir/corrigir autonomamente e **mergear PRs BUILD-ONLY 100% verdes**, preservando decisões humanas para credenciais, custos, preço, segurança nova, deploy, produção e atos irreversíveis.
**Cronograma de escopo:** `docs/NFCORE_V1_BUILD_INTEGRATION_EXECUTION_2026-10-18.md` — anexo, **não substitui** `docs/NFCORE_V1_EXECUTION_LEDGER.md`.
**CURRENT de continuidade (02/11/2026):** trilha BUILD é **secundária à construção fiscal RTC-04**, não é o próximo bloco a iniciar. `main@2e388071af68c63d63cdbf258b58c7fe4113f7d5`, CI #1466/Gov #897 SUCCESS. BLD-00/01/02 DONE internamente; BLD-03 já possui formulário/serviço de trial (#234/#235/#260/#279/#292); BLD-04 possui aquisição/checkout/fulfillment/Command (#281/#285/#293); BLD-06 possui infraestrutura de Worker e PG isolado (#294/#295); BLD-05..08 dependem de delta de contrato/prova/ambiente específicos, e não de reconstrução. Evidência parcial não equivale a certificação comercial ou implantação.
**Trabalhos abertos, não escolher como retomada fiscal:** #297 correção comercial histórica (176 commits atrás da `main` no último compare), #298 integração comercial opt-in, #299 decisão documental de planos, #313 teste documental RTC e #314 patch BLD-04, todos não integrados; #302 preflight Contabo e #296 release NO-GO de `production` também não são elegíveis para merge/deploy nesta trilha. Confirmar novamente o HEAD/estado antes de tratá-los. **Próxima ação principal: RTC-04 (Reforma Tributária / Simples Nacional), após PR #312, conforme cronograma RTC.**
**Histórico BUILD de 31/10/2026:** as instruções antigas abaixo são registros de seu momento, não CURRENT. PR #279 e #281 já foram integradas e não devem voltar à fila. Não criar segundo trial, checkout, API, tenant, Worker nem formulário.
**Snapshot histórico substituído:** em 27/10 a main era `aa04c8b2b63384880e3d6a98f41771b2f0415c8f` e o próximo era iniciar BLD-03; tal instrução não deve disparar reconstrução após o merge #260.

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
- **Estado:** IN_PROGRESS
- **Depende de:** BLD-00 e interfaces de identidade BLD-01; código interno pode avançar se sessão admin/config comercial bloquearem operações
- **CURRENT:** 31/10/2026 — `portal/trial.*`, ingresso Web, catálogo/antiabuso e serviços canônicos estão integrados via #234/#235/#260; `main=d68c62d9`, CI/Gov pós-merge SUCCESS. **Não recriar UI/API/trial service.** PR #279 foi MERGED em `9564406e2c2af6cee99266301309f045dbbd878a` para exigir decisão canônica de liberação comercial; CI pós-merge #41198490385 e Governança #41198490371 SUCCESS; não inferir publicação em Contabo. PR #237 foi FECHADA sem merge: teste de concorrência já reaproveitado com schema isolado na main, evitando `DROP SCHEMA public CASCADE` do teste antigo. Oferta real, preço/duração, admin binding e Web publicada seguem sem comprovação de prontidão.
- **Target e aceite:** seção `NFV1-BLD-03` do anexo de execução.
- **Evidência final:** PENDENTE (fechamento BLD-03 ainda exige revisão/CI/merge apropriado da #279 e demais gates). Evidência parcial: PR #260 MERGED, `main=d68c62d9c7e90581ad5efd387927f83c40a59ba2`, CI #41167507102/Gov #41167507147 SUCCESS. Ver checkpoint cruzado de 31/10.
- **Pendência / decisão humana:** se surgir, registrar o bloqueio exato com decisão necessária, sem gerar novo serviço, preço ou credencial.

### NFV1-BLD-04 — Comercial interno e integração Command
- **Estado:** BLOCKED_HUMAN_ACTION
- **Depende de:** BLD-03 contratos, ou interfaces canônicas já verificadas; não ativar pagamentos
- **CURRENT:** Pricing/release e aquisição/fulfillment internos existem; #281 (testes HTTP autenticados do FM Command) MERGED em `5d894ffcf34c8a9ee6d66876ee35c2c9273ee32a` após CI pré-merge #41168608800 e Governança #41168608803 SUCCESS. Os gates registrados neste parágrafo pertencem ao snapshot de 31/10; não afirmam o status CURRENT. Checar eventual evidência de CI pós-merge se necessária ao aceite. Este incremento não encerra BLD-04: catálogo/release/checkout runtime sem readiness e E2E comercial integral ainda exigem evidência. Backend multi-tenant é autoridade; simular somente entrada de provedor em testes.
- **Target e aceite:** seção `NFV1-BLD-04` do anexo de execução.
- **Evidência final:** PENDENTE para fechamento integral de BLD-04. Evidência parcial: #281 merge `5d894ffcf34c8a9ee6d66876ee35c2c9273ee32a`, CI da PR #41168608800 e Gov #41168608803 SUCCESS; pós-merge em andamento. Não confundir testes de contrato com a cadeia inteira.
- **Pendência / decisão humana:** a ativação comercial real depende de aprovação de planos/checkout, credenciais, publicação e pagamentos; isso bloqueia o ACEITE integral do bloco, não sua implementação interna já existente. Deltas internos específicos ainda podem ser executados de forma independente, sem recomeçar. Classificação BLOCKED_HUMAN_ACTION atende à ordem estrutural do ledger e não equivale a trabalho não iniciado.

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
- **CURRENT:** Worker, PostgreSQL, outbox, retries, idempotência e recuperação preexistem; PRs #294/#295 foram integradas com isolamento do teste de claim e composição opt-in do Worker, sem ativação produtiva. Falta prova E2E específica e configuração externa, não reconstrução do Worker.
- **Target e aceite:** seção `NFV1-BLD-06` do anexo de execução.
- **Evidência final:** PENDENTE (registrar PR + HEAD + merge SHA + CI/Gov PR e main + prova funcional apropriada).
- **Pendência / decisão humana:** se surgir, registrar o bloqueio exato com decisão necessária, sem gerar novo serviço, preço ou credencial.

### NFV1-BLD-07 — Conectar site novo e jornada NFCore
- **Estado:** PENDING
- **Depende de:** BLD-03 ingresso seguro e catálogo quando aprovado; separar canal interno de liberação pública
- **CURRENT:** site canônico `faabio3131/fm-site-novo` PR #10 integrou acesso ao Portal; PR #12 contém proposta de trial/CTA e exigia reconciliação no último checkpoint cruzado (31/10). Este ledger não certifica o HEAD atual de outro repositório nem publicação de oferta; verificar antes de implementar.
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


### BLD-03 — correção do gate PostgreSQL da PR #260 (28/10/2026)

Main `e751ffb368828ea3387b0f49eeab5e467e2ce4ba`: CI #1198/Gov #621 SUCCESS.
PR #249 já integrada com a correção de preflight; não republicar ou reauditar.
Na PR #260, CI #1202 (`40609828877`) teve 2570 PASS/3 SKIP e uma falha:
o teste isolado de concorrência convertia a URI em conninfo textual, rejeitado
pelo contrato de PostgresFiscalDatabase antes de testar qualquer admissão.
A correção preserva a URI e codifica search_path na query como os testes
duráveis existentes; mantém host local, schema único, concorrência 3/12,
hash do IP e negação por tabela ausente. Cleanup agora cobre falha no
construtor. Contrato de produção e assertivas não foram relaxados.

Nova CI completa no HEAD corrigido é obrigatória; sem aprovação por SKIP local.
BLD-03 permanece IN_PROGRESS. Merge retido pelo vínculo main→auto-deploy
do Portal documentado no fechamento BLD-02; não houve alteração Railway,
deploy solicitado, credencial, preço, trial_days ou migration persistente.

A mesma montagem de DSN foi corrigida no harness PostgreSQL do E2E de trial,
que só executa após Pytest na CI; preserva a mesma prova browser e schema único.

> **2026-11-19 — REC-04 — incremento de evidência documental (base `d38c872dba2c`).** Nesta entrega: bytes originais previamente revisados, em diretório de política por escopo `<sale_policy_key>.evidence/<sha256>.bin`, máximo 2 MiB por arquivo/16 MiB por decisão, verificação do SHA-256 na resolução/instalação, retenção no arquivo fiscal canônico na mesma UoW da reserva e revalidação na recuperação. Sem segunda persistência ou aceitação de upload do navegador como autoridade. Requer provisionamento autorizado dos documentos e revisão fiscal; não equivale à comprovação de autenticidade/aceitação externa. Testes escritos, não executados; sem CI, merge ou deploy; REC-04 segue aberto até certificação normativa e operacional.


## CURRENT reconciliado em 19/11/2026 — 59 IDs + SP-22/MG-20 + Cajamar

[Reconciliação individual do código CURRENT](audit/NFCORE_CURRENT_RECONCILIATION_59_TASKS_42_MUNICIPALITIES_2026-11-19.md), auditoria commit `f97ba0aacc5d11b6af7cf786f99b3184e80a7d39`, SHA de engenharia auditado `79bee7c64e3b2e984fb9517d190d2ca6b128a573`. Preservados IDs/ordem e provas históricas. As dimensões de engenharia, certificação, operação e dependências externas são independentes. Não reimplementar por checklist antigo. Cajamar é célula adicional; corrigidas jurisdição do candidato de substituição e montagem Contabo, permanecem GAP-CAJ-01/02/03. Inventário inicial individualizado, não auditoria exaustiva das operações. Nenhuma CI, merge ou deploy nesta rodada.


## CURRENT 19/11/2026 — delta de Cajamar após reconciliação 59/43

**SHA de engenharia:** `0cdd034a293696e376aafd70923a42bfe7dced0f`, ver `docs/operations/CAJAMAR_GEISWEB_RUNTIME_PROVISIONING.md`. Preservadas emissão/consulta de lote/cancelamento/XML e autoridade canônica. GAP-CAJ-01 avançou: intent durável, códigos incertos fail-closed e ConsultaNfse por nota original conectada a Portal/arquivo (`5430c180`, `c3c80feb`, `b129fe6e`, `b52ab1eb`). Sem status oficial inequívoco no manual público, confirmação final de cancelamento incerto depende de contrato/prova autenticada adicional; consulta não muda lifecycle. GAP-CAJ-02: revisão humana agora arquivada, sem simular substituição; integração da confirmação municipal exige formato/contrato comprovado. GAP-CAJ-03: indisponibilidade de impressão oficial em homologação documentada e refletida no Portal; PDF municipal não fabricado (`0cdd034a`). Testes novos escritos, ainda não executados. **IMPLEMENTED_NOT_CERTIFIED** no escopo entregue; não declarar Cajamar nem NFCore completo. Sem CI, merge ou deploy. Não reabrir construção existente sem evidência de regressão.
