# Central de Economia Fiscal — execução T01–T22

> **CURRENT — 26/11/2026 — T20 DONE_CERTIFIED_INTERNAL (escopo interno/sandbox); fechamento documental em revisão.** [PR #628](https://github.com/faabio3131/nf-core-v001/pull/628) MERGED em `943ca9d90b44a57a7869942b9397f2b542e04cfd`, HEAD auditado/autorizado `32e805f356d778bd41f59249daf46af627a39e38`, árvore idêntica `b9b98b769bb2d7c4c8e2811cfaa5d2810d7cbe14`. [Gemini R2](https://drive.google.com/file/d/1SNQGoDVU_55QVMYk-NGkwoAAtWmvYsSx/view) APROVADO PARA SOLICITAR MERGE (0 P0/P1/P2, 3 P3 novos não bloqueantes). CI pré-merge #45912018413, governança #45912018406 e T2 efetiva fora de Draft #45916142009 SUCCESS. [CI pós-merge #45916210955](https://github.com/faabio3131/nf-core-v001/actions/runs/45916210955) e [governança #45916210883](https://github.com/faabio3131/nf-core-v001/actions/runs/45916210883) SUCCESS no SHA real, evento push/main: 44/44 etapas, 7.277 Python PASS, 1 SKIP fora T20, 30 frontend PASS, 90 Playwright PASS, zero falhas; Ruff/Mypy (491 fontes), segurança, containers, SBOM, backup/restore e readiness aprovados. Skip `tests/runtime/test_p02_t02_fiscal_surfaces.py:389` (runtime production composition requires PostgreSQL); aviso Node 20 não bloqueante. CI concluída 21h42 BRT. T01–T20 tecnicamente certificadas no escopo implementado (20/51 entregas internas, 33 T + 18 ERP; não é prontidão comercial). A próxima tarefa é o gate interno obrigatório [#625](https://github.com/faabio3131/nf-core-v001/issues/625), cinco refinamentos T18/T19; executar após integração e CI própria desta reconciliação. T21 bloqueada até #625 resolvida e certificada; também provar exclusão da oportunidade documental `nfcore.accounting-dossier/v1` de totais econômicos. T22 bloqueada; ERP somente após T22, folha T23–T33 após ERP-15 e H01–H06 após fechamento interno. Preservar 59 IDs históricos, BLD-00–08, 18 etapas ERP, #613/#616, #593 e DoD literal Master v4.1. O XLSX Master original permanece preservado; sincronização do snapshot XLSX segue pendente (não é gate autônomo). [Issue #626](https://github.com/faabio3131/nf-core-v001/issues/626) preserva evidências e será encerrada somente após CI/governança pós-merge documental. Limites T20: apenas sandbox opt-in, sem assinatura automática, reconhecimento de crédito, homologação externa, efeito fiscal real ou validação visual Microsoft Excel; browser E2E usa transporte simulado e HTTP/PG reais são testados separadamente. Sem deploy ou alteração de produção. Os registros datados anteriores são históricos, não CURRENT.

## Diretriz do diretor em 24/11/2026 — construção do SaaS e expansão nacional

A prioridade é concluir o SaaS e comprovar que suas jornadas funcionam de ponta a ponta no escopo implementado. A engenharia avança na sequência do cronograma, com os testes, a revisão, a integração e a certificação de cada bloco. A ausência de cobertura de uma UF, município, modalidade ou competência não bloqueia a construção nem a passagem à próxima tarefa após o aceite técnico do bloco atual.

A cobertura territorial cresce conforme a programação de expansão. Registrar as lacunas para futura curadoria, com jurisdição, modalidade, competência e evidência pendente. Quando a plataforma estiver internamente pronta e funcionando, o foco passa a ser a expansão nacional sobre a mesma arquitetura.

No radar, uma lacuna deve aparecer como cobertura indisponível ou base insuficiente. Uma regra sem comprovação continua excluída da estimativa e do cálculo naquele escopo. Para a T10, cadastrar um primeiro incentivo municipal real ou concluir a curadoria estadual da [#593](https://github.com/faabio3131/nf-core-v001/issues/593) não é pré-requisito para integrar o motor nem para iniciar a T11 após os gates de integração. A [#594](https://github.com/faabio3131/nf-core-v001/issues/594) acompanha a entrega técnica.

## Diretriz do proprietário — integração universal com ERPs (25/11/2026)

O NFCore deve ser plataforma fiscal e tributária independente, com conectores receptivos, avançados, parametrizáveis e reutilizáveis para ERPs/SaaS. A construção e certificação internas independem de clientes, tokens e homologação externa. Documentar lacunas de contratos e nunca inventar operações. Reutilizar o Core e as autoridades canônicas.

A [issue #620](https://github.com/faabio3131/nf-core-v001/issues/620) e a [Trilha ERP (18 etapas, gate ERP-15)](NFCORE_V1_UNIVERSAL_ERP_INTEGRATION_EXECUTION_SCHEDULE.md) acrescentam uma entrega obrigatória da V1 **após T22 certificada e antes de T23–T33 (folha completa)**. Não renumerar T01–T33 ou H01–H06; acrescentar a dependência ERP-15 para início da folha e fechamento interno anterior à homologação externa. A T18 foi integrada pela PR #619 e certificada tecnicamente; esta reconciliação é exclusivamente documental. Todas as etapas ERP estão PROGRAMADAS / NÃO INICIADAS. Nenhuma promoção ou operação externa autorizada.

> Revisão v4.1 (25/11/2026, parecer técnico): 18 entregas ERP internas (ERP-12 substituída por ERP-12A/B/C; ERP-16 exportação contábil obrigatória). ERP-12 permanece agrupador histórico, não conta como tarefa adicional. Ordem: ERP-01–11 → ERP-12A → ERP-12B → ERP-12C → ERP-16 → ERP-13 → ERP-14 → ERP-15. Marketplace incorporado ao ERP-02. T01–T18 certificadas tecnicamente no escopo interno da Central; T18 #619 integrada em `e8ded78f3b3c5bd484b8d35b1904f0db7c61f317`, HEAD auditado `b2d682da66f62fcbe50c8b2465f1e5e1e8182c0a`, CI pós-merge #45696838699 SUCCESS (7.215 Python PASS, 1 skip, 87 E2E, 44/44 etapas) e governança #45696838637 SUCCESS. Atualização factual de 26/11/2026: #621 integrada e certificada; T19 #624 integrada em `75542dd18d7a1521a33017f80395e24285c39fe4`, árvore idêntica ao HEAD auditado `970701f600574a86e143ef01ebede8e7cc611488`, CI pós-merge #45746332104 e governança #45746332101 SUCCESS. T19 certificada no escopo interno; T20 #626 foi integrada e certificada no escopo interno pela PR #628; fechamento documental e #625 precedem T21. #625 permanece aberta como gate interno obrigatório pré-T21/Portal/produção; #613/#616 preservadas. Não rebaixar status certificados. T22 continua gate de início da implementação ERP; durante T18–T22 só preparação não invasiva (inventário documental, leitura de contratos, desenho de fixtures), sem iniciar tarefa formal, modificar branches concorrentes ou integrar código. Desde ERP-01–07, usar Bling como referência prática e testes de contrato desde o início; ERP-08 mantém seu gate formal após ERP-07. T23 exige T22 e ERP-15; H01 exige T33 e ERP-15. 51 entregas internas (33 T + 18 ERP) e 6 externas na planilha, sem renumerar os 59 IDs históricos de outro escopo mestre.

## HISTÓRICO — certificação pós-merge T19 e liberação T20 (26/11/2026)

**T19 CERTIFICADA TECNICAMENTE NO ESCOPO INTERNO.** PR #624 integrada por autorização expressa do proprietário em `75542dd18d7a1521a33017f80395e24285c39fe4`, HEAD auditado `970701f600574a86e143ef01ebede8e7cc611488`, árvore idêntica `a78100476b06dc44192773eab9f73cb55f244290`. Parecer Gemini R2 aprovado (P0/P1/P2=0); CI pré-merge #45739710170, governança #45739710243 e T2 efetiva #45745759948 SUCCESS. [CI pós-merge #45746332104](https://github.com/faabio3131/nf-core-v001/actions/runs/45746332104) SUCCESS (44/44 etapas; 7.245 Python PASS, 1 SKIP fora T19; 30 frontend e 87 Playwright PASS); [governança #45746332101](https://github.com/faabio3131/nf-core-v001/actions/runs/45746332101) SUCCESS. [Handoff e limites T19](NFCORE_T19_RECOVERY_LIFECYCLE_HANDOFF.md).

**T20 — Gerador de Dossiê Contábil PDF/Excel/XML: próxima tarefa, NÃO INICIADA.** A autorização atual abrange a atualização documental e sua liberação. A liberação efetiva (READY_TO_START) exige integração desta reconciliação e CI/governança próprias SUCCESS; os SHAs finais, a PR documental e as execuções ficam registrados na [issue #626](https://github.com/faabio3131/nf-core-v001/issues/626). [Handoff T20](NFCORE_T20_ACCOUNTING_DOSSIER_HANDOFF.md): DoD literal recuperado de `NFCore_Cronograma_Master_v4_1_ERP_Universal.xlsx`, aba `Trilha1_Construcao_Interna`, ID T20. Pacote PDF + Excel + XMLs de prova com base legal, memória de cálculo e parecer estruturado; exportação em 1 clique, pronto para revisão e assinatura do contador sem edição manual. Inventariar CURRENT e congelar implementação antes de código.

Encerrar #622/#623 após o gate documental, com evidência; preservar #625 aberta. Seus cinco P3 são engenharia interna obrigatória antes da T21/Portal/produção, sem bloquear a T20 documental após fechamento certificado da T19. #613/#616 e curadoria #593 continuam independentes. Master v4.1, 18 entregas ERP, dependências T22/ERP-15/T23/H01 e 59 IDs históricos preservados. Nenhuma promoção de produção, deploy, reconhecimento de crédito ou operação fiscal real.

Os registros datados abaixo documentam revisões anteriores; os bloqueios de T19/T20 neles descritos foram superados somente nos limites do CURRENT acima.

## HISTÓRICO — T19 em correção pós-auditoria independente

T18 #618 CLOSED; documentação #621 MERGED na main ea9349539c14c51b1efb26a95548b1d2ab316a65, CI pós-merge #45704884105 SUCCESS (44/44, 7215 Python PASS, 1 SKIP, 87 Playwright), governança #45704883938 SUCCESS. T19 #623 em construção na branch feat/nfcore-economy-t19-recovery-lifecycle. Handoff docs/NFCORE_T19_RECOVERY_LIFECYCLE_HANDOFF.md. Sem merge T19 sem CI exata e auditoria independente/autorizações; T20 bloqueada. Preservar Master v4.1 e #613/#616/#622. Sem deploy, reconhecimento ou efeito fiscal real.

CI #45728411909 no HEAD anterior 3e1472ff: 7.234 Python PASS, 2 FAIL T19, 1 SKIP; Ruff/Mypy/governança SUCCESS; gates posteriores não executados. Correções de expiração de sessão no teste e preservação de exceção de domínio publicadas na candidata #624; nova CI exata e Gemini pendentes. Ver handoff T19; sem certificação ou alteração de ordem.

## HISTÓRICO — correção pós-auditoria Gemini (25/11/2026)

Parecer independente do HEAD 93bb2d9e180d4e0cbebe16b2951208e502ec7408, árvore aacc5c5b1e36627467c63f8d662ef13226a0cfd8: REPROVADO, P0=0/P1=1/P2=3/P3=4. CI #45730534528 SUCCESS (44/44, 7236 Python PASS, 1 SKIP fora T19, 87 Playwright), governança #45730534536 SUCCESS; não substituem auditoria. [Parecer original](https://drive.google.com/file/d/1c6frBHtAurD8dcEbylAoMtDd5ooroYtP/view). Auditor relatou leitura integral e simulações independentes, não execução Pytest/PostgreSQL ou recálculo binário independente.

Correções candidatas: P1-01 restringe ICMS escritural à compensação administrativa simulada sem SELIC, restituição somente indébito federal PIS/Cofins suportado, validação no domínio/serviço/replay; P2-01 valida capacidade prospectiva de casos/eventos e lançamentos antes de postar, sob lock e savepoint existentes, preservando replay e leitura; P2-02 homologação de compensação sem prazo/alerta, deferimento de restituição mantém acompanhamento; P2-03 acrescenta regressões de fronteiras e CLI subprocess com sessão PostgreSQL e MFA real sintético (sem mock do gate). P3-03 normaliza detecção de prefixo e rejeita variante não canônica. Nenhuma regra nova de crédito real, migration, workflow ou segunda autoridade.

P3-01 resíduo de centavos e P3-02 revaloração mensal/encerramento de restituição deferida exigem decisão contábil/fiscal explícita e testes de conservação; não ajustar artificialmente centavos nem simular indeferimento para contornar revaloração. P3-04 contenção global SHARE NOWAIT requer benchmark e solução governada antes de T21/Portal e operação real. Registrar/acompanhar os três riscos residuais na issue #623, com gate obrigatório antes da exposição comercial; não declarar cobertura externa. Limites finitos protegem integridade e leitura, mas exigem estratégia de escala antes de Portal. Correções implementadas, ainda NÃO CERTIFICADAS: execução focal local/PostgreSQL não comprovada; exigir CI integral no novo HEAD, rodada 02 Gemini, completude T2 efetiva, autorização de merge específica, CI pós-merge e fechamento. T20 bloqueada até certificação da T19. Master v4.1, #613/#616/#622, main e production preservados.

## Histórico — ponto de retomada em 24/11/2026

A [PR #592](https://github.com/faabio3131/nf-core-v001/pull/592) integrou as sete PRs de T01–T09 na `main` pelo commit `f19122a8b158a3910271890a74a3f4f66a7d5852`. O responsável pelo projeto autorizou o merge após reavaliação técnica pelo agente. A árvore integrada é idêntica à da revisão `85ed8703`. [CI da revisão](https://github.com/faabio3131/nf-core-v001/actions/runs/45313958431) · [CI do merge](https://github.com/faabio3131/nf-core-v001/actions/runs/45316804802).

**T10 entregue e integrada.** A #596 foi mergeada em 24/11/2026 na main `8f48f5af241e02315800055477b8aeca1450b5b7`. A [CI pós-merge](https://github.com/faabio3131/nf-core-v001/actions/runs/45381597371) aprovou 6.979 testes Python e 82 E2E, com um teste Python ignorado. Registro na #594.

**T11 integrada.** PR #598 mergeada em `7e1d797a40c444db90a18eb66506d9fa5d025bf3`; CI pós-merge #45394058836 SUCCESS (6.991 Python PASS, 1 SKIP, 83 E2E PASS), governança #45394058967 SUCCESS. O escopo da planilha inclui IRPJ, adicional, CSLL, PIS/Cofins cumulativo e não cumulativo e IVA Dual. Consultar a [issue #597](https://github.com/faabio3131/nf-core-v001/issues/597) para PR, HEAD e CI, e o [handoff de engenharia](NFCORE_T11_SIMULATION_HANDOFF.md) para o recorte, reprodução e fontes de referência. T12 posteriormente integrada e certificada, conforme registro seguinte.

**T12 ENTREGUE — 24/11/2026.** PR #600 integrada em `db75317f26b8a56b23b2d6f0266befc629db2bd1`; CI pós-merge #45414580213 SUCCESS (44/44 etapas, 7.032 Python PASS, 1 SKIP de ambiente, 84 E2E), governança #45414580325 SUCCESS. Reauditoria Gemini no HEAD `adadaeadfd31151cbe1aa52356b7a0e130218e70`: todos os P1/P2 anteriores resolvidos, zero P0/P1/P2 novos; refinamentos P3 na #601. Issue #599 fechada. Tree integrada idêntica à revisada. Handoff T12 atualizado.

**T13 ENTREGUE — 24/11/2026.** PR #603 integrada em 1d675ae9384c15d1b79012c4f07d3ef20ab501c4; CI pós-merge #45434601978 SUCCESS (44/44, 7.034 Python PASS, 1 SKIP de ambiente, 85 E2E), governança #45434601658 SUCCESS. Gemini aprovou HEAD 1d2e9defbb4353be836807672b2876d7be4bf514, zero P0/P1; refinamentos P2/P3 #604. [Handoff T13](NFCORE_T13_ACCOUNTING_REVIEW_HANDOFF.md). Issue #602: fechamento após reconciliação documental.

**T14 ENTREGUE — 24/11/2026.** PR #606 integrada na main 9435cd0165b477c853d34354a02dafaf0afb2833, árvore idêntica ao HEAD ca8655b3b17ae86c8f639976cabbf695fc2afbb2 aprovado pelo Gemini (0 P0/P1/P2; 3 P3 na #607). CI pós-merge #45467529956 tentativa 2 SUCCESS (44/44, 7.052 Python PASS, 1 SKIP de ambiente, 86 E2E), governança #45467532344 SUCCESS. Primeira tentativa interrompida por HTTP 429 Maven Central na geração RFB V0073; resolvida por reexecução sem alteração de código. Issue #605 CLOSED. #604 P2-01/02 resolvidos, P3 preservados. [Handoff T14](NFCORE_T14_AUTHORIZED_ISSUANCE_HANDOFF.md).

**T15 entregue.** A PR #609 integrou a T15 na main `c4026bb0b4a5e47c523a674bc70408ecd602698a`. A revisão Gemini de `335498d776ea4c5efbc8a03db3e12e24a9c98ac1` e o merge têm a mesma árvore `4a8ea62672e9199e9d44fe5df4213af335f77476`. A CI pós-merge #45504585819 passou nas 44 etapas (7.092 testes Python aprovados, 1 skip, 87 Playwright aprovados). Governança #45504585565 e completude efetiva #45517996984 aprovadas. O parecer registrou zero P0/P1, dois P2 e dois P3 acompanhados na #610. [Handoff T15](NFCORE_T15_HISTORICAL_AUDIT_HANDOFF.md).

**T16 entregue.** T16 integrada pela PR #612 no commit `6f138449e0e8c51e51fcbde896618614721c78b1`. O HEAD aprovado pelo Gemini, `267b0b0306fde9dabd1750694b084d62cd86d66c`, e o merge têm a mesma árvore `062ca0f5b6e0c82cb08e4f969c5fd5546c93589d`. CI pós-merge #45527493411 aprovada na tentativa 2 (44/44 etapas, 7.151 testes Python aprovados, 1 skip e 87 Playwright aprovados). A primeira tentativa recebeu HTTP 429 do Maven Central. Governança pós-merge #45527493836 e completude efetiva pré-merge #45527067399 aprovadas. Parecer independente sem P0/P1. Os três P2 e dois P3 permanecem na #613. [Handoff T16](NFCORE_T16_UNUSED_CREDITS_HANDOFF.md).

**T17 entregue e certificada — 25/11/2026.** T17 integrada pela PR #615 na main `1b802189b144bd3dc4eca4bb66be90e2b92adfb1`, com autorização expressa do proprietário no HEAD auditado `660b86e26ad82b914caf323f51905a0011451ab6`. Árvores Git idênticas `d2582048ee67508c1a9aefc1d75ee32932e51014`. CI pré-merge #45533679231 SUCCESS (44/44, 7.177 Python PASS, 1 SKIP fora da T17, 87 E2E PASS), governança #45533679277 SUCCESS e completude efetiva fora de Draft #45614859660 SUCCESS. Gemini: aprovado para solicitar merge, zero P0/P1; 3 P2 e 3 P3 na #616. Governança pós-merge #45615039934 SUCCESS. CI pós-merge [#45615039868](https://github.com/faabio3131/nf-core-v001/actions/runs/45615039868) SUCCESS no SHA integrado (44/44 etapas, 7.177 Python PASS, 1 SKIP fora de T17 e 87 Playwright E2E PASS). **T17 INTEGRADA E CERTIFICADA NO ESCOPO INTERNO EM 25/11/2026.** T18 tecnicamente liberada após reconciliação documental, sem início de implementação nesta PR. A advertência de depreciação de Node.js 20 não impediu a CI. Production inalterada; sem deploy, operação fiscal, reconhecimento, restituição ou compensação. #613 e #616 preservadas. [Handoff T17](NFCORE_T17_RECOVERY_HANDOFF.md).

**T18 integrada e certificada tecnicamente — 25/11/2026.** T18 #619 integrada por autorização expressa do proprietário no HEAD `b2d682da66f62fcbe50c8b2465f1e5e1e8182c0a`; main `e8ded78f3b3c5bd484b8d35b1904f0db7c61f317`; árvore auditada e integrada idêntica `bf9ca5cf99c6cb6676a85b84f5bfb8e96055cbb0`. CI pré-merge #45687246955 SUCCESS, governança #45687246913 SUCCESS, completude efetiva #45696419876 SUCCESS. [Parecer Gemini rodada 02](https://drive.google.com/file/d/1NNdAKH7F3tPxJXkB4xUY3AHILwBbC4Jt/view): 7/7 achados originais resolvidos, P0/P1/P2=0, 3 P3 não bloqueantes na #622. CI pós-merge [#45696838699](https://github.com/faabio3131/nf-core-v001/actions/runs/45696838699) SUCCESS (44/44 etapas, 7.215 Python PASS, 1 skip fora de T18, 87 Playwright E2E PASS); governança #45696838637 SUCCESS. Aviso Node.js 20 não bloqueante. **T18 CERTIFICADA TECNICAMENTE NO ESCOPO INTERNO EM 25/11/2026.** #618 permanece aberta até integração autorizada e CI pós-merge desta reconciliação documental #621. T19 próxima, ainda bloqueada por esse gate documental; não iniciar implementação antecipada. Production `a5989e523c871c288bc2388c9508c1738082bb9a` preservada, sem deploy, reconhecimento real de crédito ou operação fiscal externa. #613, #616, #622 preservadas. [Handoff T18](NFCORE_T18_CREDIT_LEDGER_HANDOFF.md).

Checkpoint histórico da correção: **T18 em correção pós-auditoria — #618.** Gemini reprovou o HEAD 17e368a2 (P1=1, P2=3, P3=3). Nova CI e reauditoria obrigatórias; nenhum merge autorizado. T17 encerrada após integração documental #617 na main `6b1f940bcad984a5800abcaa7c0104a58e169491`; CI pós-merge #45651616041 e governança #45651615956 SUCCESS. T18: conta-corrente por tributo, principal/SELIC e saldos disponível/reservado/compensado/estornado; partidas dobradas, histórico integral e reconciliação sem saldo negativo. [Handoff T18](NFCORE_T18_CREDIT_LEDGER_HANDOFF.md). T19 aguarda certificação e integração autorizada.

**Curadoria fiscal — [#593](https://github.com/faabio3131/nf-core-v001/issues/593).** O acompanhamento documental de AP, PA, RR e SE segue até 07/12/2026. Por modalidade e competência, registrar vigência, vínculo com registro e depósito quando aplicáveis e parecer independente. Até lá, as quatro candidatas seguem excluídas da importação e do cálculo. Essa pendência permite avançar na construção da T10. A expansão do catálogo de operações da T06 segue sujeita a revisão fiscal de cada nova regra.

Fonte: NFCore_Cronograma_Master_v3_Trilhas_Com_Trava.xlsx, Trilha 1, linhas 6–27.
A folha T23–T33, a Trilha 2 H01–H06 e a reformulação Enterprise não integram esta rodada. A futura oitava tela é a Central de Economia Fiscal; T21 exige interface funcional antes do redesign. Nenhuma tarefa é ENTREGUE sem DoD, data e evidência.

| ID | Entrega | Estado |
|---|---|---|
| T01 | Modelagem de dados, oportunidades, benefícios, ledger, dossiês, RLS | DoD interno aprovado — 44 PASS, 0 SKIP/FAIL (44678481529, 570170f3) |
| T02 | Contrato Core Cognitivo | ENTREGUE — DoD interno aprovado em 20/11/2026; 308 PASS, 0 SKIP/FAIL; 24 casos focais (44718504072, d53a2c62) |
| T03 | Sentinela Normativa e anistias/REFIS | ENTREGUE — DoD interno aprovado em 20/11/2026; 525 PASS, 0 SKIP/FAIL; 6 casos focais (44720120616, 6a0cf5be) |
| T04 | Motor Simples e Fator R | ENTREGUE — DoD interno aprovado em 20/11/2026; 114 casos focais PASS, 831 PASS na regressão, 0 FAIL, 1 SKIP externo RTC (44722887552, 8dc7c482) |
| T05 | Diagnóstico e otimizador Fator R | Engenharia integrada na #592 |
| T06 | Classificador de receitas segregáveis | Engenharia integrada no escopo revisado. Ampliação do catálogo por operação em aberto |
| T07 | Apuração/PGDAS segregada | Apuração consultiva integrada na #592 |
| T08 | Catálogo federal | Catálogo consultivo integrado na #592, com seleção temporal e autoridade da T07 para IBS/CBS |
| T09 | Catálogo estadual 27 UFs | Motor de triagem integrado. Curadoria e revisão independente acompanhadas na #593 |
| T10 | Benefícios municipais e radar unificado | ENTREGUE — #596 integrada, CI pós-merge 45381597371 |
| T11 | Simulação Presumido/Real e IVA | ENTREGUE — #598, CI pós-merge 45394058836 |
| T12 | Comparador multi-regime | ENTREGUE — #600, CI pós-merge #45414580213 SUCCESS e Gemini aprovado |
| T13 | Aprovação contábil auditável | ENTREGUE — #603, CI pós-merge #45434601978 SUCCESS e Gemini aprovado |
| T14 | Aplicação autorizada emissão | ENTREGUE — #606, CI pós-merge #45467529956 tentativa 2 SUCCESS e Gemini aprovado |
| T15 | Auditoria histórica 60 meses | ENTREGUE — #609, CI pós-merge #45504585819 |
| T16 | Créditos não aproveitados | ENTREGUE — #612, CI pós-merge #45527493411 |
| T17 | Recuperação/prescrição/SELIC | ENTREGUE — #615; CI pós-merge #45615039868 SUCCESS |
| T18 | Ledger partidas dobradas | ENTREGUE / CERTIFICADA TECNICAMENTE — #619, CI pós-merge #45696838699 SUCCESS; fechamento documental #621 |
| T19 | Restituição/compensação | ENTREGUE / CERTIFICADA NO ESCOPO INTERNO — #624; merge 75542dd1, CI pós-merge #45746332104 e governança #45746332101 SUCCESS; fechamento documental nesta reconciliação |
| T20 | Gerador de Dossiê Contábil PDF/Excel/XML | DONE_CERTIFIED_INTERNAL — PR #628 MERGED `943ca9d9`; CI pós-merge #45916210955, governança #45916210883 SUCCESS; fechamento documental em revisão |
| T21 | Interface Central vinculada a APIs reais | Bloqueada — requer T20 certificada e os cinco refinamentos internos #625 resolvidos |
| T22 | E2E interno seis blocos | Bloqueado |

## Histórico das entregas e decisões anteriores

Os registros datados abaixo descrevem o estado em cada revisão. Para retomar a execução, consulte o ponto de retomada no início deste documento.

## T01 — incremento 20/11/2026
Base 52568a3df46dc6cf608a22c7b9971266ce71cbef; migração MFA v24 está em PR #586 concorrente. Construído esquema aditivo de cinco tabelas com chaves e FKs completas por host/tenant/unidade/ambiente, RLS FORCE, políticas de SELECT/INSERT, índices, montantes em centavos e versões imutáveis. Acrescentado repositório PostgreSQL inicial para snapshots e teste de migração isolada, papel sem BYPASSRLS, isolamento, imutabilidade e rollback. A numeração/integração na autoridade canônica de migrations e configuração do papel runtime restrito ainda precisam ser feitas após conciliação da v24; não existe execução DDL de produção. Ledger é somente estrutura inicial, não motor de partidas dobradas T18. T01 permanece EM CONSTRUÇÃO, não certificado. T13/T14 preservados na branch feat/nfcore-fiscal-benefits-20261120 (1a839b3bf51f9920c79b3d1f4ef7e099e10c24c5), sem merge antecipado.

Persistência de inserção e leitura escopada acrescentada para as cinco entidades, com validação de referências, centavos e digest. Teste PostgreSQL ampliado para toda a cadeia e para referência cruzada impossível entre empresas. Execução não comprovada.

Repositório endurecido: leitura e gravação exigem transação escopada ativa, reuso após encerramento e chamada direta recusados; projeções conferem digest, entradas passam pelas mesmas primitivas SQL e teste de rollback explícito adicionado. Estado continua EM EXECUÇÃO; teste PostgreSQL não executado.

### Integração canônica T01
Migração aditiva v25 na mesma autoridade PostgreSQL, opt-in por NFCORE_ECONOMY_ENABLED=true. Base de integração inclui a candidata MFA v24 (#586, SHA bc95d9460494958d091f7cee8afc1f3d7d768e57) sem alterar a branch do MFA nem promover produção. Papel restrito explicitamente configurado em NFCORE_ECONOMY_RUNTIME_ROLE, com SELECT/INSERT apenas; SET LOCAL ROLE e RLS FORCE por transação. Guardas de migração e readiness atualizados, preservando v23/v24 quando a Central estiver desabilitada. Teste usa PostgresFiscalDatabase.initialize() em schema isolado, aplica v25, exercita repositório canônico e isolamento. Execução e revisão ainda não comprovadas; T01 não entregue.

Vinculação final de schema e segurança: readiness confere RLS e predicados de escopo exatos; atualização opcional v24 posterior a v25 é prevista; JSON fiscal rejeita operações com floats e valores imprecisos; testes abrangem todos os quatro eixos de partição. A CI integral será executada sobre o HEAD candidato, sem alteração de workflows ou promoção. T01 não pode receber status ENTREGUE sem execução verde real.

### Operação e aceite do T01
O schema v25 é aditivo e opt-in. O provisionamento do papel PostgreSQL deve anteceder a migração, em ambiente de sandbox/staging autorizado: papel dedicado NOLOGIN, NOSUPERUSER, NOBYPASSRLS, NOCREATEROLE e NOCREATEDB, não proprietário das tabelas; a conta do serviço deve poder assumir esse papel por SET LOCAL ROLE. A autoridade migration_guard concede USAGE/SELECT/INSERT somente quando NFCORE_ECONOMY_ENABLED=true e NFCORE_ECONOMY_RUNTIME_ROLE está definido. O papel do aplicativo não deve ser exposto a clientes, AI ou SQL arbitrário. O desligamento de feature não remove a migração; schema posterior com flag desligada falha fechado. Nenhum segredo registrado. A readiness testa predicados, RLS FORCE e índices válidos; regressão real testa alteração proposital de policy e índice somente no PostgreSQL isolado da suíte. T01 continua em execução até o teste real passar; T02 não iniciada.

## T02 — contrato cognitivo estruturado (20/11/2026)
T01 DoD comprovado: https://github.com/faabio3131/nf-core-v001/actions/runs/44678481529 (44 PASS, zero skip/fail, SHA 570170f3). A CI integral anterior passou Python mas falhou no E2E de layout herdado do MFA; não houve promoção.
T02: `nfcore.cognitive.economy/v1`; três capabilities (Opportunity Radar, Credit Recovery, Tax Simulation). API de aconselhamento e schema JSON autenticados; avaliação e referências vinculadas ao snapshot/regra e competência, hashes e fonte legal oficial/revisada obrigatórios. Valores somente estimados pelo motor, aprovação/realização nulas; sem mutação. O modelo seleciona ações consultivas de vocabulário fechado, usando o orçamento, auditoria e guardrails existentes. Dados incompletos não geram candidatos. T03 e T04+ produzirão catálogo, regras e resultados reais; nenhuma elegibilidade ou recuperação é simulada pelo T02. Revisão fiscal real das normas pertence aos pacotes posteriores.

### Certificação T02 — 20/11/2026
- HEAD de código certificado: `d53a2c62d54a252eda1baa6e64f4a8d1ba0183cc`; PR #587 (draft, sem merge).
- DoD do Cronograma Master v3: schema JSON versionado para oportunidades/créditos, citação legal obrigatória e testes de contrato sem regressão. **APROVADO internamente.**
- Evidência: https://github.com/faabio3131/nf-core-v001/actions/runs/44718504072 — SUCCESS; 308 passed, 1 warning, 0 skipped/failures; 24 casos focais. Ruff PASS, mypy PASS (445 arquivos), migration policy PASS.
- PostgreSQL 16 real em CI: leitura transacional REPEATABLE READ READ ONLY; isolamento dos quatro eixos, recusa de escrita, vínculo de snapshot/regra e valores determinísticos; evidências sintéticas não são homologação ou crédito real.
- CI integral do mesmo SHA: https://github.com/faabio3131/nf-core-v001/actions/runs/44718511040 — em execução na hora do registro. O E2E de layout móvel da CI anterior falhou; gate de integração e promoção do bloco segue pendente. Não houve merge, deploy, aprovação fiscal nem mudança em main/production. T03 liberada conforme DoD específico, sem início de execução.

## T03 — Sentinela Normativa (20/11/2026)
CURRENT: vigia de quatro portais, comparação de bytes e cache atômico, timer de exemplo, sem sinais tributários nem alertas por empresa. TARGET: ampliar a mesma vigia com PGFN Editais e RFB Transação, classificação determinística de títulos/links de legislação/anistia/REFIS/parcelamento/transação, checkpoint v2 e projeção autenticada por tenant/unidade/ambiente. O cache é exclusivamente de evidência pública, não catálogo de regras. Alertas são triagem, nunca vigência, elegibilidade, homologação ou autorização. Fontes nacionais iniciais, expansão das jurisdições nos pacotes T08–T10. Poll único compartilhado; IDs escopados, sem dados privados no cache. Migração automática do cache v1, sem DDL. Mantido o timer existente, sem instalação ou deploy. Aceite: fixtures de editais e normativas, idempotência, mudança, indisponibilidade parcial, validade temporal, isolamento da API, regressão dos monitores e Core; T04 bloqueada até PASS.

Fontes oficiais iniciais incluem PGFN Editais, RFB Transação e RFB Legislação, além dos quatro portais existentes. Identificador estável por sinal e por escopo; links públicos da mesma origem, sem query/fragmento e sem armazenar títulos livres. Para ativar: migrar mediante cópia auditada do cache anterior para o diretório dedicado, manter timer diário existente, montar somente esse diretório no API via compose opt-in, confirmar NFCORE_COGNITIVE_ENABLED=true. Nenhum dado fiscal privado no cache. Vigência/prazos, elegibilidade, histórico completo de publicações e cobertura estadual/municipal não inferidos da classificação de títulos; permanecem governados pela revisão e T08–T10.

Regressão integral herdada da T02 (CI 44718511040): gate de dependências do motor base detectou Pydantic no pacote fiscal base. Corrigido deslocando para extras cognitive/web/dev, sem modificar o teste constitucional nem as dependências base. A suíte da T03 inclui esse gate explicitamente; 5803 PASS, 1 FAIL, 2 SKIP foram o resultado anterior, não uma CI integral aprovada.

### Certificação T03 — 20/11/2026
- HEAD certificado de código: `6a0cf5bee4562807180cc0e60bd69bb84cd8bdb4`; PR #587 (draft). DoD da planilha: pipeline interno com fixtures/fontes normativas e editais de anistia gerando alertas automáticos por tenant — PASS.
- https://github.com/faabio3131/nf-core-v001/actions/runs/44720120616 — SUCCESS, 525 PASS, 0 SKIP/FAIL, 1 warning; 6 casos focais T03; Ruff, mypy (447 arquivos), migração, PostgreSQL real da regressão T01–T02 e compose opt-in PASS. Gate de dependências V2-12 original aprovado após reposicionamento do Pydantic nos extras cognitivo/web/dev.
- T03 usa a sentinela e o timer diário existentes, sete fontes públicas iniciais, cache atômico v2, alertas de alterações e categorias e API autenticada por unidade/ambiente. Não há prova de coleta real contínua no host, vigência ou elegibilidade, nem de cobertura estadual/municipal integral. A coleta por fixtures não é homologação fiscal externa. Estado atual das fontes é projeção de triagem, não histórico completo de editais ou regras. Timer e compose apenas preparados; instalação/ativação não executada.
- CI integral do código: https://github.com/faabio3131/nf-core-v001/actions/runs/44720129576 em execução na certificação. Gate de promoção integral continua aberto; sem merge, deploy, mudança em main/production ou migration produtiva. Fase 0 certificada internamente por DoDs T01/T02/T03. T04 liberada pela trava específica, não iniciada.

## T04 — motor Simples Nacional
CURRENT: regime federal canônico e adaptador RFB RTC, sem motor PGDAS-base. TARGET: cálculo independente de IA no tax package, tabelas LC123 I–V, história consolidada da empresa, RBT12 separado por mercado, Fator R combinado, limites/sublimites e estado temporal, memória determinística e centavos. Fontes: https://legis.senado.gov.br/norma/572878/publicacao/34621013, https://normas.receita.fazenda.gov.br/sijut2consulta/link.action?idAto=92278, Portaria CGSN 54/2025 (todos os 27 UFs em 2026). Regra 2026 explicitamente versionada; 2027 exige nova regra devido à Resolução CGSN 190/2026. T04 entrega base de alíquota e diagnóstico; segregação especial e apuração PGDAS final são T06/T07. Excesso art.24 recebe repartição proporcional da base doméstica ordinária, com alíquotas federais e locais nos tetos legais, sem simular DAS definitivo. Exclusão/retroatividade bloqueiam valores inseguros. T05 deverá consumir o motor por snapshot autorizado; sem emissão, aprovação ou deploy. Testes ainda não executados.

### Certificação T04 — 20/11/2026
- HEAD de código certificado: `8dc7c4825dc517ac539326d01990bd3d7112e647`; PR #587 (draft), CI https://github.com/faabio3131/nf-core-v001/actions/runs/44722887552: SUCCESS; 114 casos focais PASS (DoD exige 20+), regressão 831 PASS, 0 FAIL, 1 SKIP externo (`tests/tax/test_rtc_group_indicators.py`: banco V0073 não montado), 1 warning. Nenhum skip T04. Ruff, Mypy (448 arquivos), política de migrations e regressão PostgreSQL real aprovados.
- Motor determinístico versionado para competência de 2026: 30 faixas dos Anexos I–V, RBT12 por mercado, Fator R com receita combinada, início de atividade, sublimite ICMS/ISS nas 27 UFs, limites proporcionais, efeitos temporais do excesso, cálculo Art.24 em base doméstica ordinária e arredondamento exato de centavos. Referência oficial de cálculo: Perguntas e Respostas do Simples Nacional, questão 5.3. Regra 2027 não aplicada por analogia; requer nova versão da legislação e testes. Sem inferência de elegibilidade pelo CNAE, sem apuração PGDAS final e sem lançamento fiscal. T05 irá conectar diagnóstico e oportunidades ao snapshot e cadastro canônicos; T06/T07 tratarão segregações e apuração. 
- Última CI integral da fundação https://github.com/faabio3131/nf-core-v001/actions/runs/44720129576: 5810 PASS Python, 2 SKIP; E2E 80 PASS e 1 FAIL preexistente no cabeçalho compacto mobile (167,125px vs máximo 125px). Não promover candidata até correção e CI integral verde. Nenhuma mudança em main/production, nenhum merge/deploy. T05 liberada pelo DoD específico, não iniciada; Bloco 1 ainda aberto.

## T05 — implementação candidata 20/11/2026
Base ad5e336b da PR #587. Escopo: diagnóstico da base doméstica ordinária, gap exato do Fator R, comparação V/III na competência seguinte dependente de cenário explícito, alertas por mercado e estado legal da T04. A simulação não reescreve fatos, não presume encargos zero e bloqueia vigência 2027 e comparações monetárias com sublimite/limite excedido. Alertas de 80/90% são política operacional proposta, não limites legais. Fonte: art. 26 da Resolução CGSN 140/2018; regra futura CGSN 190/2026 não aplicada. Escopo protegido: emissão, autenticação, migrations, RBAC e demais regras fiscais. Restam conexão ao snapshot escopado, produtor de avaliação cognitiva, jornada de API, teste PostgreSQL, CI e regressões. T05 NÃO ENTREGUE; T06 bloqueada.

### Integração candidata T05
Aplicação decodifica snapshot revisado versionado (nfcore.simples-facts/2026-v1), verifica digest da política T04, vigência e citações legais para ambas as competências. API POST /v1/portal/cognitive/economy/simples-diagnostic com sessão, AUDIT_READ, CSRF, escopo e referências exclusivamente; verifica perfil e declaração federal canônicos. Persiste no T01 apenas cenário positivo com custo explícito, sem crédito ou aprovação, expondo IDs de oportunidade e simulação para o contrato T02. Não há ingestão pública de fatos nem cadastro de norma pelo navegador; importador confiável ainda deve fornecer snapshots e regras revisadas. Testes e CI não certificados; T06 permanece bloqueada.

### Jornada de importação e integração T05
Importador operacional scripts/nfcore_simples_import_reviewed.py para ambiente não produtivo, com bundle revisado externamente, tenant/unidade canônicos, sem DDL, sem dados privados em saída. O serviço valida antes da persistência, evita reescrita de versões e gera as avaliações no mesmo escopo. O leitor cognitivo distingue competência do snapshot e competência simulada e valida digest da memória de cálculo. Fixtures sintéticas cobrem importação, replay, projeção T02 e quatro eixos de isolamento no PostgreSQL; teste HTTP cobre autenticação, CSRF, RBAC e rejeição de dados fiscais enviados pelo navegador. Gates ainda pendentes; não há homologação nem produção autorizadas.


## Certificação T05 e Bloco 1 — 20/11/2026
- HEAD de código `bd3e8d0100470fadf505291c8e74fb85933d6037`, PR #587 OPEN/DRAFT, base MFA `bc95d946`, main `549ab3c0` inalterada.
- CI integral https://github.com/faabio3131/nf-core-v001/actions/runs/44735022830 SUCCESS: 5944 Python PASS, 2 SKIP, 8 warnings; 30 frontend PASS, 81 E2E PASS; zero falhas. Skips: runtime production composition requires PostgreSQL (variante específica); V0073 database not mounted. Governança 44735026872, completude 44735026761, Contabo config/teste 44735026970 SUCCESS. Ruff/Mypy, migrations, segurança, containers, SBOM, backup/restore PostgreSQL e readiness aprovados no runner.
- Escopo interno T05 concluído: diagnóstico e cenário determinístico de Fator R, importação revisada não produtiva, referências imutáveis, oportunidades/simulações com custo explícito, escopo canônico e projeção T02. Cabeçalho MFA reconciliado sem relaxar E2E.
- Bloco 1: engenharia implementada e CI integral aprovada; integração/revisão independente ainda pendentes. Não equivale à homologação fiscal real, produção ou certificação comercial. Entrada revisada legítima, operação produtiva e UI T21/E2E T22 não demonstrados. Sem merge/deploy. T06 liberada; T07 permanece bloqueada.


## T06 — implementação e importação candidata (20/11/2026)
CURRENT T05 certificado; TARGET classificação determinística de receitas por atividade, mercado, tratamento federal e local, no mesmo PostgreSQL e API. Regra revisada 2026, art.25 CGSN140/2018; não é apuração final T07. Receitas ordinárias, monofásicas revisadas, ICMS substituto/substituído/antecipação final, exportação e retenção ISS. Totais unitários reconciliados em centavos com limites da história empresarial; desconhecidos e conflitos bloqueiam todos os buckets. Classificações jurídicas são entradas de revisão humana, não inferidas de código fiscal. Regime caixa, benefícios específicos e catálogo automático não certificados.
Operação: mesmo scripts/nfcore_simples_import_reviewed.py, bundle com schema nfcore.simples-segregation-facts/2026-v1, references de snapshot/regra e evidências revisadas. Restrito a ambiente não produtivo e unidade homologação; transação T01, sem DDL. Replay idêntico e conflito de conteúdo recusado; resultado bloqueado preservado para revisão e sem valor fiscal. API POST /v1/portal/cognitive/economy/simples-segregation recebe somente IDs/versionamento, sessão, AUDIT_READ e CSRF; leitura read-only, mesma autoridade de emissor T05. Testes candidatos de domínio, HTTP e PostgreSQL incluem quatro eixos, replay, conflito e zero crédito. CI integral obrigatória; T07 bloqueada. Nenhum deploy, merge ou homologação real.


## Certificação T06 — 20/11/2026
- HEAD de código `3c59ffb80bc8413161c10ec61071a45b92fead04`, PR #588 OPEN/DRAFT, base T05 `2b9c163a`, main `549ab3c0` inalterada.
- CI integral https://github.com/faabio3131/nf-core-v001/actions/runs/44747030794 SUCCESS: 5984 Python PASS, 2 SKIP, 8 warnings, 30 frontend PASS, 81 E2E PASS, zero falhas. Skips: variante runtime exige PostgreSQL; V0073 database not mounted. Governança 44747034288 e completude 44747034201 SUCCESS. Ruff, Mypy, PostgreSQL real, migrations, segurança, Docker, SBOM, backup/restore/readiness e transição v21-v23 PASS no runner.
- Classificador 2026, importação operacional revisada não produtiva, reconciliação exata, isolamento, replay, conflito imutável, API somente leitura, sem crédito/declaração. Correções Ruff, Mypy e propagação da exceção específica fiscal aprovadas; nenhum teste flexibilizado.
- Certificação limitada a fatos de competência revisados e tratamentos suportados; não comprova catalogação automática de NCM/CFOP/CST, regime caixa, benefícios especiais, homologação externa ou operação produtiva. T07 deve falhar fechado para casos não cobertos, sem inferir redução fiscal. UI T21 e E2E específico T22 continuam futuros. Revisão independente e integração das PRs pendentes; sem merge/deploy. T07 liberada para construção na mesma linha descendente; T08 bloqueada.


## T07 — incremento candidato (20/11/2026)
CURRENT T06 certificado; TARGET apuração segregada pela autoridade única simples_nacional.py. Auditoria encontrou também rfb_simples_calculator.py: adapter oficial IBS/CBS, não PGDAS mensal; preservado. Repartições LC123 anexos I–V vigentes em 2026 (https://www2.camara.leg.br/legin/fed/leicom/2006/leicomplementar-123-14-dezembro-2006-548099-normaatualizada-pl.html), CGSN140 arts.21/25 (https://normas.receita.fazenda.gov.br/sijut2consulta/link.action?idAto=92278). Deriva a antiga visão local da tabela completa, mantém digest T04 e versiona nova partilha. Reutiliza histórico, fator R, faixas, alíquotas e classificação. Exclusões por tratamento revisado, comparação ordinária, memória racional e arredondamento por tributo agregado (estimativa, não paridade oficial). API na mesma composição, read-only, referências T06 escopadas, sessão/RBAC/CSRF; sem nova persistência. Escopo protegido: emissão, RTC, autenticação, migrations, produção. Casos de extrapolação de limite/sublimite, regime caixa, tratamentos não representados na T06 e conciliação oficial PGDAS permanecem pendentes, não emitir valor quando ultrapassados os limites. Não declarar T07 integral; T08 bloqueada. Gates: regressão T04/T06, domínio, HTTP e PostgreSQL real, CI integral e revisão independente.


### T07 — incremento de limites, caixa e comparação (20/11/2026)
Partilha proporcional por mercado e tributo acrescentada à autoridade T04; exclusão/retroatividade bloqueadas. Conciliação de caixa 2026 por registro revisado de parcelas, saldo, recebimentos, reconhecimento compulsório e eventos de encerramento; confronto com classificação de competência. Comparador de referência PGDAS revisada, vinculado ao digest da segregação, sem declarar equivalência oficial. Ainda requer CI integral, revisão normativa e validação de casos de caixa com excesso, continuidade histórica dos registros, fixtures reais de referência e regra 2027. Nenhum merge/deploy; T08 bloqueada.

## Reconciliação RTC-RFB × Economia Fiscal T07 — 20/11/2026

Decisão do proprietário: reaproveitar integralmente a integração existente, completar lacunas sem duplicar autoridade. CURRENT auditado na PR #589, HEAD 9e334f3988fe94452f10230e11da1039667d2c69, main 549ab3c005d7183ff6c7940236414412ea004b9d. PRs #576, #584 e #585 integradas em work/nfcore-closeout-20261119 e presentes na árvore T07. Não reimportar ou reconstruir seus componentes.

| Entrega | Autoridade e destino | Estado |
|---|---|---|
| Simples RTC 1.0.2, Regular 1.7.2, banco V0073 | Adaptadores tax/rfb_* e deploy/rfb existentes | Integrados ao código, respostas registradas; operação Contabo não comprovada |
| Sombra NF-e/NFC-e | tax/rtc_shadow.py e application/rtc_shadow_recorder.py | Integrada, opt-in, sem autoridade de emissão |
| NFS-e /nao-assistido | build_nfse_request, SimplesEffectiveRates existentes | Adaptador testado por fixture real; falta composição com alíquotas PGDAS verificadas e jornada de emissão |
| Apuração mensal 2026 | tax/simples_nacional.py, segregação T06/T07, store T01 | Candidata; falta certificar caixa, excessos, histórico e comparações |
| Transição 2027 | RTC-04/05 e T07 compartilham regime temporal e evidências; reusar tax/regimes.py | Regra 2027 não pode ser deduzida das tabelas 2026; requer partilha vigente, evidência da opção e testes |
| Comparação PGDAS | T07 compare_assessment | Não confundir com comparação RTC por documento; referência real externa necessária para paridade oficial |
| Ativação Contabo e sentinela de releases | RTC/Release Manager | Gate operacional separado, não declarar ativado |

Contrato-alvo: apuração mensal revisada -> alíquotas efetivas por anexo vinculadas a emissor, competência, escopo, versão e evidência -> SimplesEffectiveRates -> adaptador oficial já existente. Nenhuma promoção automática de estimativas T07 a alíquota declarada, nenhum cálculo do browser/IA, nenhuma segunda persistência ou serviço fiscal. A opção IBS/CBS deve vir da autoridade temporal existente em tax/regimes.py, não de seleção livre no payload. Preservar modo sombra, evidências, pins, V0073 e controles de emissão. Critérios de aceite: comparação por tributo, casos de caixa/competência e excesso, vigência, isolamento, replay, testes PostgreSQL, integração dos adaptadores e CI cumulativa; revisão independente antes de promoção. T08 bloqueada até fechamento do escopo T07. Não autoriza deploy, DDL, transmissão ou merge main/production.


### T07 — integridade da opção caixa e da referência PGDAS (20/11/2026)
Auditoria do HEAD 03273718b7d654ed374d2ca1d888d2ad183db719: a opção anual irretratável de caixa (CGSN 140/2018 arts. 19–20, https://normas.receita.fazenda.gov.br/sijut2consulta/link.action?idAto=92278 e https://www8.receita.fazenda.gov.br/SimplesNacional/Servicos/Grupo.aspx?area=1&grp=5) não permite retorno arbitrário à competência em novembro. Correção limitada ao motor existente e regressão dezembro/novembro; encerramento/exclusão preservados. O comparador PGDAS passa a exigir assessment_digest além do digest de receitas e competência: evita replay de referência após alteração de histórico, alíquota, partilha ou base. Referências antigas devem ser reapresentadas com o digest do cálculo revisado; sem promoção de autoridade. Testes focais adicionados; aprovação depende de execução. Não se declara T07 concluída; permanecem caixa com excesso/impedimento local, regra temporal 2027, fixtures oficiais, CI integral e revisão independente. T08 bloqueada; sem merge/deploy.


### T07 — guarda de importação e continuidade (20/11/2026)
O importador existente valida a referência comparativa antes da persistência imutável (PGDAS divergente permanece evidência consultiva, referência incompatível ou apuração bloqueada não entra como comparação válida). Histórico caixa malformado falha com erro de domínio, sem KeyError exposto; o predecessor deve pertencer ao schema canônico. Regressão PostgreSQL cobre referência sintética válida/incompatível, ausência de registro inválido e histórico malformado. Não altera schema, RLS, RBAC, emissão ou autoridade de aprovação. Testes aguardam execução; sem certificação oficial.


### T07 — acionamento da CI integral da trilha Economia Fiscal
Detectado que CI integral automática só inclui PRs para main, production e integration/nfcore-*. A base da #589 é feat/nfcore-economy-t06-20261120. Ampliação exclusivamente aditiva do filtro pull_request para feat/nfcore-economy-t*, sem mudar jobs, permissões, comandos, asserts, regras de segurança ou política de promoção. Aprovado somente após execução comprovada no HEAD; não substitui revisão independente nem encerra lacunas fiscais.


### T07 — sexta faixa e redistribuição do ISS (20/11/2026)
Manual PGDAS-D oficial, exemplo 8, pp. 117–118 (https://www8.receita.fazenda.gov.br/SimplesNacional/Arquivos/manual/MANUAL_PGDAS-D_2018_V4.pdf): a parcela local calculada pela quinta faixa contém excedente de ISS além de 5%, redistribuído aos tributos federais. O motor T07 descartava esse excedente. Partilha v2 no mesmo módulo determinístico separa componente federal da sexta faixa e suplemento local, ponderando este pelo excesso de sublimite e preservando redistribuição. Fixture adaptada para competência 2026 com histórico equivalente; valores esperados exatos em centavos por tributo agregado e total publicado de R$ 246.061,47 (não atesta paridade oficial nem coincidência de arredondamento em outros casos). T04 diagnóstico histórico e seu digest preservados; a reconciliação de estimativas T04 nas faixas limítrofes e demais fórmulas ainda exige revisão. Não há segunda autoridade nem promoção fiscal. Teste aguardando CI do novo HEAD.


### T07 — convergência T04/T07 e regime de caixa (20/11/2026)
CI 44766890995 falhou em Ruff E501, linha 18 do teste comparativo; corrigida sem alterar assertions. Diagnóstico T04 passa a consumir assessment_partition e partition_effective_rate existentes, incluindo redistribuição de ISS; o digest de cálculo passa a incluir PARTITION_DIGEST, sem mudar digest histórico das tabelas T04. O arredondamento diagnóstico sobre o total permanece distinto do arredondamento T07 por tributo. Regime caixa aplica base recebida reconciliada e parâmetros de competência (CGSN 140 arts. 19, 20 IV e 24; manual oficial PGDAS-D), incluindo excesso <=20% antes do mês de impedimento. O último mês anterior ao impedimento e períodos já impedidos continuam bloqueados até tratamento do saldo local e recolhimento direto por ente, sem emitir DAS parcial como completo. Retroatividade/exclusão continuam bloqueadas. Receita Federal, 14/08/2026, confirma extinção caixa a partir de 01/01/2027: https://www.gov.br/receitafederal/pt-br/assuntos/noticias/2026/agosto/regime-de-caixa-deixa-de-ser-utilizado-na-apuracao-do-simples-nacional. Não extrapolar partilha 2026 para 2027. Testes focais e CI integral necessários; sem merge/deploy. T08 bloqueada.


### T07 — saldo local art. 20 IV e continuidade (20/11/2026)
No regime de caixa, o saldo ainda não reconhecido é derivado do mesmo registro de parcelas, deduzindo valores já reconhecidos e recebimentos. Quando o impedimento de ICMS/ISS é iminente e o caixa continua, calcular o montante consultivo de recolhimento direto separado do DAS (CGSN 140/2018 art. 20 IV), sem adicionar a base desse saldo à apuração federal, sem deduzir crédito ou gerar guia. Tratamentos revisados e a mesma partilha art. 21/24 são reutilizados. Se o local já estiver impedido, zerar somente a parcela local do DAS e mostrar que a tributação local está fora do regime; não declarar ausência de tributo. Exclusão federal iminente requer evento de encerramento revisado art. 20 II; retroatividade permanece bloqueada. Município/UF responsável e recolhimento direto real exigem evidência própria; nenhum pagamento ou declaração oficial é realizado. Regressões de caixa, saldo e separação adicionadas. Gate permanece parcial até validação integral e revisão normativa independente.


### T07 — integridade do escopo da comparação (20/11/2026)
Digest da apuração vincula escopo da transação T01, emissor, competência, fatos completos (exceto a própria referência comparativa), política e vigência. Referência igual em outro tenant ou após mudança do histórico deve ser recusada antes da persistência. Classificação T06 preservada. Regressão PostgreSQL adicionada; pendente execução no HEAD. Não representa homologação PGDAS.


### T07 — transição normativa 2027/2028 (20/11/2026)
Tabelas dos cinco anexos, 30 faixas LC214/2025 anexos XVIII–XXII em redação consolidada LC227/2026: percentuais em basis points, digest e vigência explícitos na autoridade já existente. Correção CBS 16,41% no anexo III faixas 3/4; sexta faixa, alíquota nominal 0,10 p.p. menor; PIS/COFINS substituídos. Testes de integridade, vigência, anexo III e sexta faixa. Apenas lookup de parâmetros; não habilita apuração 2027. Resolução CGSN 190/2026 altera art. 21/22/26 (janela RBT12/FS12 anterior ao mês anterior, primeiras duas competências na primeira faixa, do terceiro ao 13º anualização), art. 24 (revogação das antigas parcelas de excesso), art. 22-A (dedução IBS/CBS quando opção regular). Fonte: https://normas.receita.fazenda.gov.br/sijut2consulta/link.action?idAto=92278 . Próximos gates internos: regime temporal/evidência da opção, cálculo 2027 e classificação por operação, ponte verificada RTC sem promoção de estimativa, testes e revisão independente. Não usar fórmula 2026 em 2027. T08 bloqueada.


### T07-C/D — núcleo temporal CGSN 190 (20/11/2026)
No motor existente: 2027 exige modo IBS/CBS resolvido, histórico deslocado a partir de dezembro/2025, primeira faixa e fator 0,28 nos dois primeiros meses, partilha exata com IBS/CBS/ISS, complemento local da sexta faixa, art. 24 sem ponderação por excesso e art. 22-A sem redistribuição dos tributos excluídos. Fonte oficial: https://normas.receita.fazenda.gov.br/sijut2consulta/link.action?idAto=92278 . Testes determinísticos adicionados; não se declara aprovados sem CI. Serviço T07 continua fechado para 2027 até integrar eleição confiável, tratamentos por operação e contrato RTC. Não habilita emissão, não atesta paridade PGDAS nem encerra T07. Revisar particularmente vigência, segregação exportação e tratamentos específicos. 2028 permanece tabela. T08 bloqueada.


### T07 — composição de apuração 2027 com autoridade existente
Schema 2027 explícito na mesma persistência T01, API T07 e importador confiável. Eleição vinculada ao perfil canônico, escopo e emissor, resolvida nos extremos da competência pelo mesmo resolver tax/regimes.py. Opção regular H1 exige recibo; H2/abertura regular permanecem fail-closed até completar os casos normativos. Regime unificado exige revisão art.40-E. Classificação 2027 por CBS/IBS/IPI/ICMS/ISS, sem reaproveitar exclusão PIS/COFINS ou presumir incidência da exportação; indústria sem IPI usa Anexo I; sem redistribuição ISS quando ISS não integra cálculo (contrato Java oficial 1.0.2); comparação PGDAS usa vetor por competência. Não presume liquidação, tributos pagos fora do DAS nem apuração assistida oficial. Não altera emissão. Aguardam testes integrais, fixtures de casos oficiais, RTC e revisão independente.


### T07 — fechamento técnico em certificação (20/11/2026)
Correções Mypy, renúncia H2 e recibo de abertura com escopo/perfil e datas revisados (CGSN 140, art. 40-D §§1–4; CGSN 194 para janela excepcional H1). Comparação NFS-e por linhas vinculadas ao snapshot e documento, no runtime da mesma API T07, clientes oficiais existentes, lote limitado, pin de versão/banco, comparação por documento (não PGDAS). Regime regular compara referência de documento revisada; IBS fora do DAS não é zero fiscal. Status indisponível, simulado ou divergente não certifica. Nenhuma autorização de emissão. Testes usam fixture gravada. CI acumulada e revisão independente ainda obrigatórias. T08 bloqueada até certificação e integração da cadeia anterior.

Correção da CI 44775936076: tipagem da coleção NfseComparisonPlan; comparação NFS-e usa arredondamento da alíquota do leiaute oficial em dois dígitos percentuais (fonte fixada SimplesNacionalCalculoService.java), sem substituir os valores da apuração mensal; distingue referência mensal por item de tributo de documento. Fixtures sintéticas verificam match e banco divergente. Resolvedor unificado recusa recibo regular ativo. Certificação cumulativa exigida no novo HEAD; solicitação de revisão GitHub Copilot não retornou revisor confirmado.

Ajuste normativo de fronteira: CGSN 186 consolidada pela 194 art. 3 II, início especial 31/10/2026 a 31/12/2026 (não 1/10). Cancelamento da extensão de opção de abertura abril–junho/2027 sujeito a protocolo e limite 31/05, sem cancelar o primeiro período. Primeiro PA respeita a data de inscrição e autoridade efetiva do perfil, não presume cobertura antes da abertura. Esta alteração exige nova CI; não certifica opções reais nem alterações fiscais produtivas.

### T07 — revisão independente Gemini e tratamento das ressalvas (20/11/2026)

Parecer externo fornecido pelo proprietário sobre HEAD `e67bca721e5232ed4d3a1c55c0e277326e344df1`: aprovado com ressalvas pontuais. CI integral anterior 44786283485 SUCCESS (6.082 PASS, 0 FAIL, 2 SKIP). Tratamento: corrigir alinhamento dos argumentos nas duas composições cognitivas; exigir V0073 também no ramo RTC Regular embora o cliente já valide o pin configurado; validar PGDAS no mesmo percurso de importação, preservando retorno T06 e validação pré-persistência; centralizar a seção RTC/T07 neste documento, mantendo referências nos demais. Regressões de pin e importação PostgreSQL adicionadas. O novo HEAD exige CI integral e verificação das ressalvas; não herda certificação do anterior. Comparação RTC ativa e paridade PGDAS oficial não comprovadas; sem merge/deploy, T08 permanece bloqueada até fechamento formal e integração da cadeia.


## T08 — Catálogo Federal, execução técnica em 20/11/2026

CURRENT: PRs #586–#589 integradas na candidata work/nfcore-closeout-20261119, HEAD 74abb29c. CI 44820360411 e 44820435993 SUCCESS (6.084 PASS, dois SKIP externos). Main 549ab3c, production a5989e5 inalteradas. T08 em feat/nfcore-economy-t08-federal-catalog-20261120, sem deploy.

CURRENT → TARGET: a T01 já dispõe de snapshots e benefícios imutáveis com RLS, a T02 fornece contratos cognitivos consultivos, a T03 detecta alteração em portais sem determinar direito fiscal, e o cadastro fiscal/regime federal tem autoridade própria. A T08 acrescenta catálogo de atos federais e filtro conservador de competência, regime, CNAE, NCM, operação e comprovação revisada, sem nova persistência, sem motor de cálculo paralelo e sem concessão automática de benefício.

Pacote federal inicial:
- RECAP (Lei 11.196/2005), REINTEGRA (Lei 13.043/2014), SISPROM e suspensão de IPI para exportador: fontes públicas RFB/gov.br indexadas, sem inferir razão de exportação, taxa vigente ou concessão. Programas sujeitos a revisão humana.
- Atualização de fontes: o registro de promoção no exterior migrou do antigo sistema SISPROM para requerimento da Receita Federal em julho/2025; não presumir que registros antigos sejam criados no sistema descontinuado. REINTEGRA exige revisão de industrialização no Brasil, TIPI e condição sobre insumos importados (guia Siscomex); nenhuma taxa é inferida. Fonte de referência https://www.gov.br/siscomex/pt-br/servicos/aprendendo-a-exportar/5-formacao-do-preco-de-exportacao/incentivos-as-exportacoes-brasileiras-1
- Lei do Bem, Lei 11.196/2005 capítulo III: exige Lucro Real, PD&I, dispêndios, regularidade e revisão. Fonte https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/lei-do-bem/paginas/legislacao
- REIDI, Lei 11.488/2007: exige projeto aprovado, habilitação e vínculo de aquisição. Fonte https://www.gov.br/pt-br/servicos/habilitar-empresa-no-regime-especial-de-incentivos-para-o-desenvolvimento-da-infraestrutura-reidi
- IBS/CBS rural, LC 214/2025 arts. 164 e 168, e reciclagem, art. 170: filtros para 2027 em diante; sem inferir valor ou apropriação de crédito. Fonte https://www2.camara.leg.br/legin/fed/leicom/2025/leicomplementar-214-16-janeiro-2025-796905-normaatualizada-pl.html
- DIRBI: a aplicabilidade deve ser verificada separadamente na lista vigente, não inferida do nome do programa. Fonte https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/perguntas-frequentes/beneficios-fiscais/beneficios-fiscais

Reutilização canônica: tax/federal_benefits.py apenas triagem; application/federal_benefits_service.py usa fm_economy_snapshots/fm_economy_benefits do T01, digests, controle de versão e RLS. O avaliador de emissor usa perfil e declaração de regime federal existentes. POST /v1/portal/cognitive/economy/federal-benefit exige sessão, CSRF, AUDIT_READ e referências escopadas; navegador não envia regras, CNAE, NCM ou valores. O POST /v1/portal/cognitive/economy/federal-benefit-search pesquisa as regras federais revisadas da própria unidade, usando somente snapshot_id/version; a última versão de cada regra prevalece, mesmo revogada, com limites de varredura e coverage_truncated explícito. GET /v1/portal/cognitive/economy/federal-programs exibe o índice público de fontes, nunca elegibilidade ou aplicação. Importador é operacional, somente em ambiente não produtivo. Resultados são potential, insufficient_basis ou not_applicable; nenhum significa direito tributário aprovado. Valores aprovados, realizados e estimados continuam nulos; emissão e pedidos são proibidos.

Aceite: testes fiscais/HTTP/isolamento PostgreSQL real, imutabilidade e replay, governança, regressão T01–T07, Ruff, Mypy, frontend, E2E, Docker, CI cumulativa e revisão jurídico-fiscal independente. Cobertura dos programas é explícita, NÃO é o cadastro exaustivo de todos os benefícios federais: faltam expansão e revisão dos atos e condições de programas não inventariados. Não marcar T08 ENTREGUE sem critérios e provas no HEAD real. T09 bloqueada até certificação.

## T08 — reconciliação dos achados da auditoria independente Gemini (20/11/2026)

Origem: parecer Gemini fornecido pelo proprietário sobre PR #590, HEAD 8f8ea1c4.
Veredito externo: APROVADA COM RESSALVAS para a candidata interna, NÃO APROVADA
para certificação final/produção; execução local no Gemini NÃO REPRODUZIDA.
CI deste mesmo HEAD 44835437469 SUCCESS (6.124 PASS, 2 SKIP, 0 FAIL)
é evidência de software, não homologação jurídico-tributária.

Correções de engenharia na mesma PR, sem novos serviços e sem novas tabelas:
- T08-01 (ALTO): identificar Lei 9.481/1997 art.1 III-a com redação da Lei
  11.774/2008 para promoções no exterior; referência do IPI suspenso à Lei
  10.637/2002 art.29 §1 II e efeito previsto no art.68 I desde 01/10/2002.
  Indexação histórica depende de política/revisão eficaz em cada competência,
  e não significa reconhecimento retroativo. SISPROM passou do sistema MDIC
  para os requerimentos RFB em 14/07/2025; evidência de canal correta por PA
  permanece obrigatória.
- T08-02 (ALTO): conjunto estrutural de regimes por programa, sempre validado
  pelo motor e também no bundle importado; vedar Simples para REIDI, RECAP e
  IPI, e Lei do Bem restringir Lucro Real. Fonte Siscomex expressamente admite
  Simples para promoções no exterior (SISPROM), portanto não vetá-lo de forma
  genérica. REINTEGRA base dos arts.21+ da Lei 13.043/2014 é distinto das
  condições do Acredita Exportação pela LC 216/2025; esta extensão exige
  modelagem e revisão próprias, e não é silenciosamente concedida.
  IBS/CBS regular é DIMENSÃO SEPARADA do regime de IRPJ: ainda sem
  comprovação de opção regular do emissor a triagem devolve
  insufficient_basis/regular_ibs_cbs_authority_missing, inclusive para
  optantes Simples com opção potencialmente possível. A futura ligação deve
  usar eleição/autoridade fiscal canônica (T07), jamais CNAE, CRT ou JSON
  informado pelo browser como prova dessa opção.
- T08-03 (MÉDIO): EconomyStore.records existente recebe filtro opcional por
  schema_version somente para fm_economy_benefits, aplicado parametrizado
  pelo PostgreSQL ANTES de ORDER BY/LIMIT; nenhum filtro para outras tabelas.
  Busca federal jamais deve usar as 500 primeiras regras de todos os módulos.
  Validar 501 registros de outros programas + federal antigo no PostgreSQL,
  sem migração ou RLS relaxada. Volume >500 do MESMO schema continua
  explicitamente sinalizado como coverage_truncated e review_required;
  paginação/índice dedicados exigem análise de escala futura.
- T08-05 (MÉDIO): versão superior que sobreponha QUALQUER parte do mês
  bloqueia triagem da anterior; versão apenas parcialmente válida não aprova
  competência cheia. Testar início/fim internos ao mês e fim inclusivo.
- T08-04 (MÉDIO): FiscalProfile CURRENT tem somente primary_cnae.
  CNAE secundário só pode ser admitido após inclusão efetivamente aprovada na
  autoridade canônica de cadastro/registro de CNPJ, com prova de vigência,
  sem cadastro paralelo na T08. Até lá é recusado em fail-closed e permanece
  lacuna de abrangência expressamente classificada.
- T08-06 (BAIXO): a jornada visual para contador/cliente segue prevista na
  T21 sobre a MESMA aplicação Web; API não equivale a experiência Web completa.
  Não se declara a paridade comercial concluída com o catálogo atual.

Fontes oficiais verificadas para esta reconciliação:
- SISPROM: https://www2.camara.leg.br/legin/fed/lei/1997/lei-9481-13-agosto-1997-365403-normaatualizada-pl.html
- Canal RFB: https://www.gov.br/siscomex/pt-br/servicos/sisprom/aviso-importante
- Simples no SISPROM: https://www.gov.br/siscomex/pt-br/servicos/aprendendo-a-exportar/5-formacao-do-preco-de-exportacao/incentivos-as-exportacoes-brasileiras-1
- IPI: https://www2.camara.leg.br/legin/fed/lei/2002/lei-10637-30-dezembro-2002-491384-normaatualizada-pl.html
- REIDI: https://www2.camara.leg.br/legin/fed/lei/2007/lei-11488-15-junho-2007-555352-normaatualizada-pl.html
- Acredita Exportação/Simples: https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/operacoes-de-comercio-exterior/acredita-exportacao
- IBS/CBS: https://www2.camara.leg.br/legin/fed/leicom/2025/leicomplementar-214-16-janeiro-2025-796905-normaatualizada-pl.html

Gates: revisão de código alterado e CI integral do NOVO SHA, incluindo
PostgreSQL e testes regressivos T01–T07. Revisão jurídico-fiscal independente
final de atos, regimes e requisitos continua obrigatória, bem como as lacunas
explícitas secundários/IBS regular/UX. Sem fusão na main/production, deploy,
liquidação, aplicação, emissão, ativação fiscal real ou avanço T09.

A Lei 11.774/2008 foi publicada no DOU em 18/09/2008 e entrou em vigor na data de publicação; o piso conservador do registro SISPROM foi refinado para 18/09/2008 após revisão da Câmara e DOU. Não reconhecer direitos retroativos sem regra histórica revisada.


## T09 — Catálogo Estadual de Benefícios de ICMS — candidata 21/11/2026

**CURRENT confirmado:** candidata interna work/nfcore-closeout-20261119 HEAD
39e64ea3772595691a1f50bbd8389f7b95f80709, pós-merge T08 CI
44895173783 SUCCESS, 6.133 testes Python e 81 E2E PASS, 2 SKIP de ambiente.
main e production inalteradas. T09 implementada em branch independente
feat/nfcore-economy-t09-state-catalog-27ufs-20261121, sem merge, deploy
ou homologação fiscal estadual.

**Current → Target**: registrar as 27 unidades federativas de forma canônica,
pesquisar regras estaduais de ICMS revisadas para um CNPJ escopado com
filtragem por UF e schema ANTES do limite SQL, avaliar natureza do benefício,
CFOP, NCM, CNAE, regime federal, operação, competência e condições
normativas, exigindo referência oficial, hashes e revisão humana. Reutilizar
sem duplicação: FiscalProfile, declarations do regime federal, T01 EconomyStore
(RLS FORCE), LegalCitation T02, rotas de autenticação, CSRF, AUDIT_READ,
Sentinela T03 como monitor de alteração — sem afirmar vigência automaticamente.

**Implementação candidata:**
- tax/state_benefits.py: 27 UF/IBGE indexadas sem fingir 27 benefícios;
  tipos exemption, base_reduction, presumed_credit, deferral, rate_reduction,
  special_regime. Rotas de fundamentação state_statute, confaz_convention e
  lc160_reinstituted, com exigências de prova distintas.
- application/state_benefits_service.py: importação revisada idempotente,
  avaliação read-only e pesquisa consultiva, vigência de mês cheio, recusa
  de versão substituída, citações oficiais e comparação de jurisdição do
  ato com registro fiscal canônico. Nunca produz impostos, créditos,
  homologação ou autorização de emissão.
- persistence/economy_store.py: filtro aditivo parametrizado jurisdiction,
  restrito a fm_economy_benefits; preserva filtros scope/tenant/schema e RLS.
- cognitive/state_benefits_api.py: reutiliza verificador federal e FiscalProfile
  para derivar UF e comprovação da inscrição estadual, sem aceitar UF do browser
  como autoridade. Post /state-benefit e /state-benefit-search recebem somente
  IDs/versionamento da mesma sessão e unidade ativa; GET /state-jurisdictions
  informa cobertura geográfica real e cobertura fiscal incompleta.
- CLI não produtiva scripts/nfcore_state_benefits_import_reviewed.py.
- Testes domínio 27 UF, caminhos legais, negativa de CNAE/NCM/CFOP,
  segurança API/RBAC/CSRF, fonte e vigência normativa, idempotência, RLS
  PostgreSQL real, ruído de 501 regras RJ e isolamento cross-tenant.

**Limites constitucionais e lacunas reais:**
1. O índice contém **27 UFs**, mas **zero incentivos estaduais reais
   verificados/incorporados nas 27 UFs**. Não equivale a cobertura fiscal
   material de todos os estados. Matriz estadual detalhada em
   docs/NFCORE_T09_STATE_BENEFITS_COVERAGE_MATRIX.md.
2. Cada regra depende da leitura do ato estadual vigente, comparação de
   alterações do RICMS, eventual convênio e ato estadual de adesão,
   habilitação, condições de fruição, aplicação em operação, código de
   incentivo quando previsto, publicação oficial, revalidação do CONFAZ e
   revisão tributária humana. LC 160/2017 e Convênio 190/2017 não
   comprovam concessão de benefícios para todos os atos.
3. CNAE secundário não consta do FiscalProfile canônico (pendência T08-04).
   Não criar segunda autoridade cadastral: recusar sem dados oficiais.
4. Operações interestaduais em que o incentivo é atribuído ao destino,
   cadeia de substituição tributária, DIFAL e transferência de crédito
   não são inferidas da UF do emissor. Esses casos permanecem
   insuficientes/requerem modelagem especializada. Simples e ICMS têm
   dimensões tributárias independentes; política revisada deve definir
   restrições legalmente justificadas para cada benefício.
5. A revisão de Lei Complementar 214/2025 (IBS/CBS), LC 160/2017,
   convênios e vigências atuais segue separada. O ICMS não é
   automaticamente substituído no catálogo por IBS/CBS na transição.
6. UI funcional pertence à T21, na MESMA aplicação, sem segundo frontend.
   Radar estadual/municipal T10 não se presume pronto pela indexação.
7. Fontes de referência e verificação: IBGE
   https://www.ibge.gov.br/explica/codigos-dos-municipios.php ;
   LC 160/2017
   https://www2.camara.leg.br/legin/fed/leicom/2017/leicomplementar-160-7-agosto-2017-785276-normaatualizada-pl.html ;
   Portal CONFAZ
   https://www.confaz.fazenda.gov.br/legislacao/certificado-registro-deposito-cv-icms-190-17-1/minas-gerais/2018/certificado-de-registro-e-deposito-se-confaz-no-50-2018/certificado-de-registro-e-deposito-se-confaz-no-50-2018.pdf/@@download/file/CERTIFICADO%20DE%20REGISTRO%20E%20DEP%C3%93SITO%20-%20SE-CONFAZ%20N%C2%BA%2050-2018.pdf
   é exemplo de certificado por ato, não fonte de habilitação geral.

**Gates:** Ruff/Mypy, testes focais das 27 UF, PostgreSQL 16,
segurança, CI integral e regressão T01–T08, revisão independente,
normativa estado por estado e check-list do cronograma. T10 permanece
BLOQUEADA até fechamento verdadeiro da T09. Nunca declarar T09
"27 UFs homologadas" antes de obter o catálogo material com prova normativa.


### T09 — decisão sobre IA jurídica especialista e dependência externa (21/11/2026)

**DECISÃO APROVADA pelo proprietário:** curadoria normativa por benefício e competência é **EXECUÇÃO INTERNA da T09**, atribuída ao papel de agente `AI_LEGAL_TAX_RESEARCH_SPECIALIST` sob governança humana, com método e filas em
`docs/NFCORE_T09_LEGAL_EXPERT_AI_WORKFLOW_V1.md` e
`docs/NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json`.
A criação do runbook **não significa que o agente foi implantado ou que as 27 verificações já foram executadas**. Nenhum registro documental deve ser promovido sem fontes originais e hashes reais, conciliação de versões/competências, atos individuais, provas negativas/positivas e revisão contraditória.

**DEPENDÊNCIA EXTERNA:** parecer jurídico-fiscal assinado do **contador indicado pelo proprietário**, `EXTERNAL_DEPENDENCY/PENDING_NOT_RECEIVED`. Não classificar sua ausência como defeito de código ou trabalho de engenharia faltante; ao mesmo tempo **não ignorá-la** para aprovação de benefício real, homologação e operação comercial. A pesquisa técnica e testes podem continuar em paralelo sem o parecer, mas ativação fiscal não.

**CURRENT nesta decisão:** PR #592 HEAD `917cf3ac428b682c6d575aba3e8f18d4f316d4d5` antes da atualização documental; candidato técnico com governança já aprovada e CI integral #44934576426 ainda em execução na última verificação; 27 pesquisas draft, 24/27 com trechos oficiais examinados e nenhum ato integralmente consolidado/assinado. `main` e `production` sem merge/deploy; T10 não liberada por esse registro de planejamento.


### Pesquisa complementar registrada em 22/11/2026 — CURRENT documental

Pacote ZIP SHA-256 `001f7e85c84e35914931218a8b5c4d492cd65d7332e847c3f36167d66e5cc12b` conferido: 64 entradas, 29 capturas com integridade local 29/29, 27 dossiês preliminares, 58 casos propostos **não executados**. O ZIP e suas fontes originais não foram enviados ao GitHub, somente seu índice/rastreabilidade. **0/27 curadorias aceitas/importadas.** Fonte da verdade: [`NFCORE_T09_RESEARCH_PACKAGE_CHECKPOINT_20261122.md`](NFCORE_T09_RESEARCH_PACKAGE_CHECKPOINT_20261122.md); [manifesto](NFCORE_T09_RESEARCH_PACKAGE_MANIFEST_20261122.json); [pendências UF](NFCORE_T09_RESEARCH_RESIDUAL_27UFS_20261122.md). A engenharia anterior tinha 6/6 workflows verdes no commit `c6008bb7`, mas nova CI deve ser verificada no novo HEAD. INT-03–06/08/09 pendentes; dependências externas separadas; T10 bloqueada.


### T09 — Coleta documental encerrada em 22/11/2026

O proprietário declarou que não possui mais arquivos para enviar. Cinco lotes novos, **50/50 hashes locais verificados**, 22 UFs representadas nesses lotes; pacote unificado `NFCORE_T09_COLETA_CONSOLIDADA_50_ARQUIVOS_20261122.zip` SHA256 `584a0cd1458619b7033d39e95a7ee4cbe31558cba90cf0ee1cdab00e1f4cd547`, **não arquivado em Git**. Registro detalhado [fechamento](NFCORE_T09_COLETA_ENCERRADA_20261122.md) e [índice das capturas](NFCORE_T09_RECEBIMENTO_FINAL_50_DOCUMENTOS_20261122.json). Esse marco encerra **recebimento**, não a T09: 0/27 curadorias aceitas e importações, pesquisa de fontes primárias, CONFAZ, temporalidade, testes reais e revisão independente ainda internas. T10 mantém trava. CI do novo HEAD exigida após alteração documental.


### T09 — Separação de critérios internos e externos — decisão do proprietário, 22/11/2026

O **aceite humano da curadoria** é um gate **EXTERNO de promoção/ativação**, e **não impede o fechamento T09-INT**. Também são externos o parecer assinado da contabilidade, homologações reais, certificados e concessões individuais de contribuintes. **Continuam internos e obrigatórios:** pesquisa normativa completa e provada por UF, capturas oficiais e hashes, efeitos por competência, LC160/CONFAZ/adoção, requisitos CNAE/NCM/CFOP/ST/DIFAL, condições de necessidade/dispensa de concessão individual, casos legais executados, revisão técnica independente e CI final. A decisão não implica redução de gates, não concede crédito tributário e não autoriza importação/produção. Documentação: `NFCORE_T09_CURATORIAL_GATE_HANDOFF_20261122.md` e fila `NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json`.
