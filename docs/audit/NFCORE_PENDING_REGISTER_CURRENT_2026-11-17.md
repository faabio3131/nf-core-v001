> **Entrega incremental 19/11/2026 — REC-03:** verificação OCSP offline complementar à LCR, CertID exato, resposta GOOD válida, assinatura da AC emissora ou responder delegado com EKU e revogação verificadas, mount existente opt-in. Nenhum endpoint externo ativado; materiais oficiais/identidade, LTV e certificação permanecem abertos. Código/testes no mesmo commit sobre `8cc67ababe091db76cf85b04d9636995aebf0f62`, sem execução de testes, nova CI, PR ou deploy. Fonte: RFC 6960. Dossiê `docs/operations/NFCORE_NATIONAL_RECEIPT_TRUST_SIGNER_PINS.md`.

> **Entrega incremental 19/11/2026 — REC-03:** verificação criptográfica do DPS antes de POST, vínculo com fingerprint do A1 do Vault e verificação do arquivo histórico usando seu instante de observação somente para a assinatura DPS. Signatário oficial da NFS-e continua sujeito à confiança atual; não equivale a LTV/OCSP. Mudança e testes no mesmo commit desta nota sobre `22a0c7da9d2f8b334d61ed606882cbbd64e764a1`, testes não executados. Sem nova CI, PR, promoção ou deploy. Dossiê: `docs/operations/NFCORE_NATIONAL_DPS_DISPATCH_EVIDENCE.md`.

> **Entrega incremental 19/11/2026 — REC-04:** contrato de deduções ampliado às espécies NFSeMun, NFNFS, nDocFisc e nDoc do XSD de fevereiro e docFiscalOutro/docOutro do NT009, com identificação de fornecedor, escolha por perfil, fingerprint/archive e reserva por identidade e hash contra alias na mesma unidade/emitente. Código e testes no mesmo commit desta nota, sobre `04305538178a097fdccd56273201c5257b39aea8`; testes não executados por ordem de construção. Política revisada e legitimidade dos comprovantes originais continuam obrigatórias; não promover REC-04/SP22/MG20 ou homologação a DONE. Detalhes em `docs/operations/NFCORE_REVIEWED_DOCUMENTARY_DEDUCTIONS.md`. Próxima dependência: integridade criptográfica e legado, lacunas municipais e gates de aceitação. Sem nova CI, PR, deploy ou expansão.

## CURRENT — 19/11/2026: construção consolidada (não certificada)

- Branch de trabalho única `work/nfcore-closeout-20261119`; **HEAD de engenharia** [`2224b3d0d6fca49029afa4fd41b194f65ac6562a`](https://github.com/faabio3131/nf-core-v001/commit/2224b3d0d6fca49029afa4fd41b194f65ac6562a). O commit documental que contém esta nota é posterior ao HEAD de engenharia; consultar a ref no GitHub em cada retomada.
- main `549ab3c005d7183ff6c7940236414412ea004b9d`; production `ea4bdd3bcb9b61e6522081a14e5cc9ad1ced9599`; sem promoção ou deploy nesta rodada.
- PRs abertas, todas Draft: #468 e #556 (mesma branch fiscal, HEAD `49546e06fd0ccf2970723d9e8950a43d003c1c70`), #498 (Web, `4cbbe7c3b222cc2abdf8c1a791203474072e8e5a`), #560 (`96fdfbede1b2109c44a4f2847268525f588cc594`), #562 (`347c1ab59961b01243f85f4c1bdb4aed30ae9614`), #563 (`d90baf14b8e9ab60b0abdee314e581f4922d2ec6`). A consolidação na branch de trabalho não equivale a merge dessas PRs nas respectivas bases.
- CI anterior nos SHAs das PRs: #468/#556 [44451576085](https://github.com/faabio3131/nf-core-v001/actions/runs/44451576085) SUCCESS; #498 [44314193608](https://github.com/faabio3131/nf-core-v001/actions/runs/44314193608) SUCCESS; #560 [44451353152](https://github.com/faabio3131/nf-core-v001/actions/runs/44451353152) SUCCESS; #562 [44450892681](https://github.com/faabio3131/nf-core-v001/actions/runs/44450892681) SUCCESS; #563 [44451657588](https://github.com/faabio3131/nf-core-v001/actions/runs/44451657588) FAILURE. O patch de lint foi incorporado à branch de trabalho, sem recertificação. **Branch de trabalho: 0 runs, nenhum teste novo executado**, por determinação do proprietário de terminar construção antes de nova certificação; testes de regressão escritos não equivalem a PASS. Não herdar CI anterior.
- Checkpoints: [consolidação](https://github.com/faabio3131/nf-core-v001/issues/510#issuecomment-6999029427) e [entregas](https://github.com/faabio3131/nf-core-v001/issues/510#issuecomment-6999508612). Snapshots datados de 17/11 e anteriores abaixo são históricos; prevalece esta atualização para fatos supervenientes.

### Entregas por REC (engenharia implementada na branch, aceite pendente)

| REC | Commit de engenharia | Mudança | Estado e limite |
|---|---|---|---|
| REC-01/12/14 | `7a57cc3497784704e867f89b5764a5ab9da0109c` | Consolidou candidata fiscal pós-#561, deltas Web #498/#556, deploy coordenado #560 e conteúdo DPS #563 | Implementado na branch; integração das PRs e certificação integral pendentes; host não verificado |
| REC-03 | `60562364f0d112f5012809bd4606552dafcc5c6b` | Pré-validação dos signatários pinados de nota e evento, antes da rede | Código; signatários oficiais, LTV/OCSP e revisão independente pendentes |
| REC-04 | `fb2ffe7809978e2850d53baee863a9f1691f12e6` | Informação complementar fiscal revisada e guarda BH cooperativa 3% | Código; matriz normativa/casos restantes pendentes |
| REC-17/03 | `e6cdc7e3a74b45c89c1a35e8a2be5d9578802b45` | Incorporou retirada de A1 IRON #562 e correção de imports da #563 | Código; sem nova CI da composição |
| REC-03 | `7c78c892d09503a1a940fd12392da717c8194daa` | Recusa chaves fracas e controles de política X.509 não processados | Fail-closed; não é processador completo RFC5280, OCSP ou LTV |
| REC-03 | `388b00ae255b65b22e083465f0bc0730b9dc0cf4` | Recuperou wrapper NFSe de fevereiro por identidade de blob e separou perfis de validação | ZIP integral de fevereiro não verificado; NT009 oficial já adquirido; ver dossiê de proveniência |
| REC-04 | `0c1652108d27f3d2749e6576995456c5154ad9e5` | Deduções NF-e/NFS-e revisadas ligadas à origem, competência, digest, valores, archive e DPS | Política do servidor; demais espécies documentais e prova do original pendentes |
| REC-04 | `e032e115d657a92e48ac5a61c0376287f6e8b317` | Reserva durável de comprovante por unidade/emitente, na transação de preparação | Reuso entre escopos e alocação parcial não certificados |
| REC-03/07 | `e4cf162efd25978eb16ab2c29d1224e805ab6401` | Guarda DPS exato/perfil antes do POST; recuperação e recibo arquivado usam evidência; fallback histórico por dhProc | LTV/OCSP e timestamp independente não concluídos; registros irreproduzíveis recusados |
| REC-04/06/08 | `2224b3d0d6fca49029afa4fd41b194f65ac6562a` | Separa valor total/elegível/aplicado; corrige assinatura de consulta GISS Guarulhos/Jundiaí sem Id incompatível com XSD | Código; WSDL/signatário oficial, jornada integral e certificação municipal pendentes |

Nenhum REC acima promovido a DONE por esta anotação. REC-05 MF-09/SP-MG: #561 integrada à #468 em `49546e06`, sem certificação completa das jornadas/produção. REC-07 Louveira PF, REC-08 SP-22, REC-09 MG20, REC-11 EGM, REC-13 reconciliação semântica das origens, REC-14 ambiente Contabo, REC-15/16 release e homologação, REC-21 Go/No-Go e REC-22 Core/Sentinela continuam abertos conforme seus próprios gates. Não ampliar cobertura nem iniciar expansão nacional. Próxima dependência: terminar lacunas internas, depois rodar matriz integral no SHA final, obter revisão independente, reconciliar as seis PRs e só então publicar mediante gates operacionais e autorizações aplicáveis.

**A–E:** A funcional e B paridade parciais; C produção, D operação e E comercial não certificadas. Matriz SP22 de 12/11 e MG20 de 11/11 são snapshots históricos, mantidos intactos; não inferir status certificado de célula a partir da implementação compartilhada.

Dossiês técnicos: [deduções](../operations/NFCORE_REVIEWED_DOCUMENTARY_DEDUCTIONS.md), [despacho histórico](../operations/NFCORE_NATIONAL_DPS_DISPATCH_EVIDENCE.md), [proveniência XSD](../operations/NFCORE_NATIONAL_RECEIPT_SCHEMA_PROVENANCE.md), [Guarulhos GISS](../operations/NFCORE_GUARULHOS_REVIEWED_GISS.md).

---

> **ATUALIZAÇÃO SUPERVENIENTE — 17/11/2026:** após as quatro integrações na candidata #468, #522/#523/#525/#526 estão **MERGED**; restam **somente #468 e #498 OPEN/DRAFT** no snapshot GitHub. #468@1237c960, #498@41dad4fa; CI final de ambos em execução. O inventário de quatro PRs e as descrições individuais abaixo referem-se à captura ANTERIOR a esses merges e foram preservados como histórico. A matriz de 22 SP/20 MG **não** foi promovida; continuam as 14 issues de escopo e os bloqueios internos/externos. Pesquisas de Louveira PF registradas na issue #509. O estado de CURRENT técnico superior é o GitHub e o ledger de reconciliação deste mesmo commit.

# NFCore — Registro Único de Pendências CURRENT e Origem Histórica (17/11/2026)

**ID:** NFCORE-REC-PENDING-20261117 • **Estado do documento:** INVENTÁRIO / NÃO É CERTIFICAÇÃO • **Repositório:** faabio3131/nf-core-v001 (mesmo repo da URL histórica kordena-fiscal-engine-v2). Data-base 17/11/2026 BRT.

**Usar junto com:** [Cronograma de fechamento](NFCORE_RECONCILIATION_CLOSEOUT_SCHEDULE_2026-11-17.md), [ledger cumulativo](NFCORE_PR_RECONCILIATION_LEDGER_CURRENT.md), [issue #510](https://github.com/faabio3131/nf-core-v001/issues/510), [issue #447](https://github.com/faabio3131/nf-core-v001/issues/447) e governança do integrador. Este registro consolida pendências para impedir perda de contexto; NÃO altera automaticamente a autoridade dos planos/ledgers originais.

## 1. Fontes e regras de classificação

FATO CONFIRMADO por GitHub: main 549ab3c005d7183ff6c7940236414412ea004b9d; production ea4bdd3bcb9b61e6522081a14e5cc9ad1ced9599; #468 e1632e646e3ed8e960ba51c88d24facf3177ffc7; #498 fbdb33843103d25c44b1e1896629c588c4a1b423; #522 42fa40fb5cd8a7e6748f9834c679f66744659cbc; #523 7962fe7b81c8f23cbbc84865fa7705819fcddd38. As duas últimas **não estão integradas** à #468.

Categorias: IMPLEMENTED_BRANCH ≠ INTEGRATED_CANDIDATE ≠ MAIN ≠ PRODUCTION ≠ INTERNAL_CERTIFIED ≠ OFFICIAL_HOMOLOGATED ≠ COMMERCIAL_APPROVED. Pendências são INTERNAL, EXTERNAL, OPERATIONAL_ACCESS, HUMAN_APPROVAL ou HISTORICAL_REVIEW. Em caso de conflito, prevalece código CURRENT + CI no SHA, depois documento versionado; ausência de prova é NÃO CERTIFICADO.

## 2. PRs abertas — reconciliação e status

| PR | Escopo e HEAD | Estado GitHub | Falta para fechar |
|---|---|---|---|
| [#468](https://github.com/faabio3131/nf-core-v001/pull/468) | Integração fiscal/Web e1632e64 → main | OPEN/DRAFT; CI anterior SUCCESS, última FAILURE | incorporar #522/#523, corrigir/validar flaky trial, CI cumulativa + EGM + G2; gates reais ainda abertos |
| [#498](https://github.com/faabio3131/nf-core-v001/pull/498) | Release Web fbdb3384 → production | OPEN/DRAFT; CI SUCCESS no SHA atual | rebase/merge seguro da #468 final, preservar infraestrutura, CI própria, preflight e aprovação |
| [#522](https://github.com/faabio3131/nf-core-v001/pull/522) | FIS-03 pin, cadeia AC e CRL; 42fa40fb | OPEN; CI 44081550101 SUCCESS | revisão/integração; RFC5280 completo, identidade SEFIN, revogação/histórico/LTV ainda não concluídos |
| [#523](https://github.com/faabio3131/nf-core-v001/pull/523) | BH MF-04; 7962fe7b | OPEN; CI 44015740152 SUCCESS | revisão/integração; classificações normativas e E2E oficiais ainda incompletos |

**Regressão identificada:** [run #43999832959](https://github.com/faabio3131/nf-core-v001/actions/runs/43999832959) da #468 falhou em tests/web/test_staging_gsm_administration.py::test_commercial_trial_binding_is_platform_only_and_replay_safe; HTTP 409 em lugar de 200 após expiração da janela. Patch testado em #522 e #523 congela o tempo do cenário legítimo e testa recusa após expiração; integrar uma vez e executar CI no HEAD combinado. Não alterar validade de produção, não desativar testes.

**PR documental criada nesta retomada:** [#525](https://github.com/faabio3131/nf-core-v001/pull/525) OPEN/DRAFT, exclusivamente para o anexo e os índices CURRENT. Não é mais uma frente de engenharia nem está integrada à #468; após sua abertura há cinco PRs abertas (quatro operacionais + uma documental). CI da PR #525 deve ser consultada no HEAD final antes de seu aceite.

**Entregas confirmadas na candidata, sem promover a main:** #513 correção cognitiva (#486), #514 perfil NT009/#508, #515 correlação SP, #516 contrato do recibo nacional, #517 venda manual, #518 recuperação histórica, #519 aprovação comercial ancestral, #520 política tributária governada, #521 Guarulhos GISS. #504/#505/#506/#511 integram o histórico anterior. Esses merges não encerram EGM, homologação, cobertura, Contabo ou release.

**Origens encerradas sem merge direto:** #413/#448/#453 com fontes recuperadas pela #518; #423/#440 com mapas de sucessor e histórico preservado; #486 recuperada em #513; #508 recuperada funcionalmente por #514/#521. Conferir equivalência por função, não por título/ancestralidade. O manifesto de 16/11 registra 96 origens mas preserva estados anteriores aos merges tardios; reconciliar valores, sem apagar dados históricos.

## 3. Issues abertas — inventário completo do repositório (14 no snapshot)

| Issue | Prioridade | Pendência/escopo | Pacote cronograma | CURRENT e limite |
|---|---|---|---|---|
| [#510](https://github.com/faabio3131/nf-core-v001/issues/510) | P0 | Gate transversal SP5, MF-04/MF-09/GET-ICP/NT009, EGM e release | REC-01/02/03/04/05/11/12/14/15 | ABERTO; checkboxes antigos não representam current pós-#520/#521/#522/#523 |
| [#447](https://github.com/faabio3131/nf-core-v001/issues/447) | P0 | Emissor independente sem Bling: login→preparo→XML→transmissão→consulta/cancelamento→arquivo/PDF→piloto | REC-05/08/15/16 | ABERTO; fluxo sintético parcial e piloto real não comprovado |
| [#445](https://github.com/faabio3131/nf-core-v001/issues/445) | P0 | Incidente de 22 municípios SP e NF-e/NFC-e estadual; provar cada contrato e operação | REC-05/08 | ABERTO; não generalizar município por roteamento/IBGE |
| [#426](https://github.com/faabio3131/nf-core-v001/issues/426) | P0/P1 | MG20/BH, MG55/65, regimes, tabelas, contratos por polo e EGM | REC-04/09/11 | ABERTO; #423/#440 fechadas sem merge; sucessores parciais |
| [#509](https://github.com/faabio3131/nf-core-v001/issues/509) | P1 externo + interno condicionado | Louveira PF NFe-Cidades 2026: WSDL/XSD, CPF/IM, credenciamento, operações e assinatura | REC-07 | ABERTO; contrato oficial PF não comprovado; não inferir suporte |
| [#414](https://github.com/faabio3131/nf-core-v001/issues/414) | P1 governança | Cobertura UF→município→documento→operação→ambiente, prioridade e histórico divergente | REC-00/08/09/10/13 | ABERTO; corrigir sem abrir UFs fora da ordem |
| [#424](https://github.com/faabio3131/nf-core-v001/issues/424) | P1 infra | Cofres A1/GSM/Bling, migração worker, mount/backup, isolamento, Contabo | REC-14/18 | ABERTO; inspeção host pendente; não unificar vaults por conveniência |
| [#283](https://github.com/faabio3131/nf-core-v001/issues/283) | P1 release | Main↔production, overlay Contabo, cron auto-pull, backup/restore, deployment SHA e rollback | REC-12/14/15 | ABERTO; release ainda não publicado |
| [#181](https://github.com/faabio3131/nf-core-v001/issues/181) | P1 histórico operacionaI | P05 GSM staging; separar T01/T02 anteriores de smoke E2E rollback e status 59 IDs | REC-14/20 | ABERTO; revalidar com CURRENT, não refazer versões já certificadas |
| [#417](https://github.com/faabio3131/nf-core-v001/issues/417) | P2 opcional | Bling OAuth, schema/secret/overlays/worker/teste pedido externo | REC-18 | ABERTO; Bling não é bloqueio para emissor nativo |
| [#524](https://github.com/faabio3131/nf-core-v001/issues/524) | P2 produto separado | IRON S2S: onboarding fiscal, A1 delegado, status seguro, provider, metering | REC-17 | ABERTO; lacuna interna confirmada; homologação externa distinta |
| [#210](https://github.com/faabio3131/nf-core-v001/issues/210) | P2 planejado | IBS/CBS/RTC: auditoria de layouts, schemas, regras, operações e vigências | REC-19 | BACKLOG ABERTO, não marcar pronta nem alterar escopo sem design |
| [#184](https://github.com/faabio3131/nf-core-v001/issues/184) | P2 governança | Skill/fitness de integridade e rastreabilidade futura | REC-20 | BACKLOG ABERTO; não confundir com gate EGM atual |
| [#168](https://github.com/faabio3131/nf-core-v001/issues/168) | P2 governança | Prontidão interna independente de backup externo, observabilidade e priorização P09 | REC-20/21 | ABERTO; avaliar estado sem desativar gates de produção |

Nenhuma issue acima foi fechada por este documento. Quando um bloco foi parcialmente implementado (MF-09, MF-04, FIS-03, Guarulhos), atualizar o **subitem correspondente**, não encerrar automaticamente o item guarda-chuva.

## 4. Engenharia fiscal interna — checklists de fechamento

### 4.1 FIS-03 e segurança do recibo nacional — issue #510 / PR #522

- [ ] Definir política de confiança do signatário oficial SEFIN/ICP, cadeia válida, anchors versionados, propósito/policies/NameConstraints, revogação por CRL/OCSP conforme contrato, timestamp e validade histórica/LTV; vincular certificado ao payload e à identidade canônica; falha segura sem rede.
- [ ] Testar XSD NFS-e GET de produção e produção restrita com ZIP/hash/source e XMLDSig, DPS nested, identidade CNPJ/município/ambiente, chave fiscal, ausência de replay, XML arquivado e bytes preservados.
- [ ] Reexecutar adversariais para certificado errado/forjado/revogado/vencido, intermediária, CRL assinada ausente/falsa, troca de trust store, histórico, política ambígua, schema perfil trocado; revisão EGM independente.
- [ ] Registrar separadamente operador/credencial oficial, A1, certificado do órgão e hospedagem real (BLOCKED_EXTERNAL/OPERATIONAL até prova). CI sintética não substitui prova fiscal real.

### 4.2 MF-04, BH e decisões de ISS — issue #426/#510 / PR #520/#523

- [ ] Matriz de competência/regime/código do serviço/alíquota/ISS/retencão/dedução/benefício/estimativa/cooperativa por fonte oficial e perfil; não inferir dos campos da UI.
- [ ] Validar exceções Estimativa e ato cooperado, benefícios distintos de produção/restrita, elegibilidade e prazos da PBH, subitens com início 01/12/2026, documentação de dedução em subitens exigidos; bloqueio até haver comprovante transportável.
- [ ] Testes MEI/Simples/normal/sublimite, imune/não incidência/exportação, dedução/retencão, replay após rotação de política, identidade/fingerprint/arquivo por tenant/unidade e negative gates.
- [ ] Não declarar BH, MF-04 ou MG20 integralmente concluídos a partir da #520/#523; catálogo fiscal normativo de todas as cidades permanece pendente.

### 4.3 Venda manual, modelos 55/65 e emissão Portal — issue #447/#445/#426/#510

- [ ] Conferir elegibilidade do emissor/empresa/estado e CNPJ, inscrição, cadastro de serviço/produto, regime, tomador, preço/pagamentos com regras fiscais reais, A1 e número fiscal durável.
- [ ] Revalidar prepare/confirm/issue/query/recover/cancel/inutilize conforme UF, NFC-e QR v3/CSC/contingência onde necessário, estados de timeout indeterminado sem rePOST, arquivo XML autorizado e DANFE/DANFC-e/DANFSe corretos.
- [ ] Conciliar contadores e writers legados antes do cutover de numeração; migrar somente com lock, idempotência e rollback testados.
- [ ] E2E HTTP/Browser autenticado, PG, RBAC/tenant/unidade/CNPJ; sem Bling; piloto com resposta oficial em célula específica só após homologação externa.

### 4.4 Infraestrutura, segurança, operação comercial e release — issues #283/#424/#181/#417/#168

- [ ] Revalidar host Contabo e credenciais de acesso por via autorizada. Desktop Commander reportou cota esgotada em 16/11; acesso atual não revalidado. Nenhum token/segredo/arquivo A1 no Git ou log.
- [ ] read-only: hostname, deployed SHA, container digests, Compose/overrides, cron auto-pull, migrations 20/21/v22, fiscal counters/reservations, GSM/A1 Vault namespace, Cakto/Bling opt-in, tenant authorization.
- [ ] Backups do PG e Vault A1, offsite, checksum, retention, restore isolado, disponibilidade de rollback de banco/imagem, ambiente staging real, TLS, health, métricas, tracing/alertas, runbooks, worker/outbox.
- [ ] Promover main/production somente após CI no SHA final, revisão EGM, aprovação humana específica, preflight e suspensão/controle do auto-pull se aplicável; depois registrar .deployed + smoke/E2E e auditoria de regressão.
- [ ] Plano mestre 59 IDs: conferir P05-T01/T02/T03/T04/T05 e demais abertas contra evidência operacional atual, sem zerar contadores ou reexecutar migrations por causa de cronograma histórico. Recovery/trial/comercialização/site/billing/suporte/LGPD exigem critérios específicos de release.
- [ ] Bling OAuth só como integração opcional. #524 IRON tem onboarding e cofre S2S próprios dentro da autoridade fiscal canônica e precisa de Security Review e testes cross-host.

## 5. Matriz SP-22: 22 células obrigatoriamente individualizadas

**Fonte:** docs/coverage/NFCORE_SP22_OPERATION_READINESS_2026-11-12.json, snapshot 12/11 e is_runtime_authority=false. Os estados abaixo são os rótulos **históricos** do JSON; a #468 recebeu implementações posteriores para cidades selecionadas. Reavaliar cada linha **por contrato + operações + CI**, sem promover todo o grupo de uma vez.

| Ordem histórica | Município | IBGE | Estado do snapshot 12/11 | Revalidação CURRENT |
|---:|---|---|---|---|
| 1 | Barueri | 3505708 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 2 | São Paulo | 3550308 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 3 | Campinas | 3509502 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 4 | Sorocaba | 3552205 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 5 | Guarulhos | 3518800 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 6 | Santos | 3548500 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 7 | São Caetano do Sul | 3548807 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 8 | Jundiaí | 3525904 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 9 | Suzano | 3552502 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 10 | Santana de Parnaíba | 3547304 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 11 | Osasco | 3534401 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 12 | Itapevi | 3522505 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 13 | Jandira | 3525003 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 14 | Mairiporã | 3528502 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 15 | Arujá | 3503901 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 16 | Louveira | 3527306 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 17 | Valinhos | 3556206 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 18 | Itu | 3523909 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 19 | Salto | 3545209 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 20 | Monte Mor | 3531803 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 21 | Guarujá | 3518701 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |
| 22 | São Vicente | 3551009 | INTERNAL_INCOMPLETE | Exigir reavaliação contra #468 + novos HEADs; sem promoção automática |

**Obrigatório por linha:** regra vigente por regime e competência, endpoint/WSDL/XSD e hash, A1/assinatura/identidade, seleção do transportador real, emitir/consultar/cancelar/substituir/recuperar/XML/PDF conforme suporte, idem PG/RBAC/tenant, evidência HTTP/Browser/CI no SHA e homologação externa independente. São Paulo capital: governar competência do Simples a partir de 01/11/2026 e retroativa; SP55/65: política específica de inutilização/QR/contingência, sem extrapolar rótulo NFS-e. Louveira PF tem uma célula separada não comprovada (#509), distinta de PJ nacional.

## 6. Matriz MG-W1: 20 polos sob issue #426

**Fonte:** docs/coverage/NFCORE_MG_W1_MUNICIPAL_CELLS_2026-11-11.json, snapshot 11/11 e is_runtime_authority=false. Identificação de canal não prova contrato de integração nem emissão.

| Prioridade econômica | Município | IBGE | Estado histórico | Lacuna |
|---:|---|---|---|---|
| 1 | Belo Horizonte | 3106200 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 2 | Betim | 3106705 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 3 | Uberlândia | 3170206 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 4 | Contagem | 3118601 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 5 | Uberaba | 3170107 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 6 | Juiz de Fora | 3136702 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 7 | Extrema | 3125101 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 8 | Ipatinga | 3131307 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 9 | Sete Lagoas | 3167202 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 10 | Pouso Alegre | 3152501 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 11 | Montes Claros | 3143302 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 12 | Nova Lima | 3144805 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 13 | Poços de Caldas | 3151800 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 14 | Varginha | 3170701 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 15 | Divinópolis | 3122306 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 16 | Araxá | 3104007 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 17 | Governador Valadares | 3127701 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 18 | Patos de Minas | 3148004 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 19 | Congonhas | 3118007 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |
| 20 | Itabira | 3131703 | CHANNEL_RESEARCHED | Contrato/operações por célula ainda sem certificação integral |

**Obrigatório por linha:** estadual MG55 e MG65 completos quando aplicáveis, fonte normativa primária, NFSe nacional/municipal de cada regime, XML/XSD/assinatura, bindings, operações e Portal, testes HTTP/PG/browser, EGM e dossiê de homologação. Uberaba/Extrema/Governador Valadares/Itabira exigem confirmação técnica primária atual. PRs #423 e #440 foram encerradas como substituídas, NÃO equivalentes a MG20 concluída.

## 7. Remanescentes nacionais, operação e produto

- #414: reconciliar MG, SP, RJ, RS, PR, MT, MS e decisões históricas DF→GO→MT→MS com prova por operação/célula; ordem e escopo só mudam por aprovação explícita.
- #210: IBS/CBS/RTC e vigência 2026/27 exigem auditoria legal/técnica e provedor compatível; não confundir implementação de objetos fiscais com leiaute/ambiente homologado.
- #184: skill permanente de rastreabilidade/documentação e anti-retrabalho; não substitui revisão independente real.
- #524: IRON multi-tenant/cross-host, A1 delegado sem expor PFX, autorizações owner/step-up, metering por unidade e rollback de integração; projeto vinculado, não pré-condição artificial de todo o piloto.
- #168/#181: separar status de build interno, staging GSM, trial, operações e homologação externa; os planos históricos não são recontabilizados silenciosamente.
- Prontidão comercial do produto: planos/preços aprovados, status de checkout/billing, assinatura, onboarding, recuperação de senha, observabilidade, suporte e LGPD devem ser verificados contra os 59 IDs e evidência do deploy. Não autorizar compra, trial fiscal ou marketing de municípios sem fonte operacional.

### 7.1 Core Cognitivo, guardrails e Sentinela normativa — REC-22

- [ ] Reconfrontar o patch #513/#486 já integrado à candidata: auditoria obrigatória antes de chamar LLM; grounding dos números frente à evidência citada; filtragem tenant/unidade/documento; hashes/proveniência e redaction; não permitir instrução de emissão/autoridade fiscal.
- [ ] Residual documentado pela própria #513: grounding hoje lexical (sem tipagem semântica robusta para moeda/percentual), subject não incorporado à identidade canônica da requisição e cache local de resposta inexistente. Classificar relevância para a V1 antes de exigir nova implementação; não presumir que cache é requisito crítico.
- [ ] Auditar `src/kordena_fiscal/compliance/normative_sentinel.py`: é sentinela **offline**, verifica SHA de artefato pinado; define explicitamente `official_provenance_verified=false` e `fiscal_production_approved=false`. Não afirmar pesquisa normativa contínua, verificação de autenticidade governamental ou ativação fiscal por checksum. Reutilizar `rtc_evidence.verify_regulatory_artifact_bytes`, sem segunda fonte autoritativa.
- [ ] Verificar contratos do Core com Portal/API, políticas de audit sink, baseline sem IA, quotas, consumo, proteção contra prompt injection, classificação normativa/atualidade, logs e testes adversariais; revisão EGM independente e critérios de aceite explícitos por requisito. Evitar expandir escopo sem comprovar necessidade e sem decisão de arquitetura.

## 8. Controle de atualização e aceite

Ao fechar um item, inserir: OWNER, data, branch/HEAD, PR/commit, linha/célula, norma/versão/hash, teste efetivamente rodado (PG/Browser/real), CI/link, status A funcional/B paridade/C produção/D operação/E comercial, riscos e bloqueio externo/humano. Atualizar o ledger corrente e a matriz municipal/issue na **mesma mudança**. Não marcar 100% por texto ou CI de outra revisão; nenhum deploy/merge/DDL realizado pela edição deste arquivo.

> **2026-11-19 — REC-04 — incremento de evidência documental (base `d38c872dba2c`).** Nesta entrega: bytes originais previamente revisados, em diretório de política por escopo `<sale_policy_key>.evidence/<sha256>.bin`, máximo 2 MiB por arquivo/16 MiB por decisão, verificação do SHA-256 na resolução/instalação, retenção no arquivo fiscal canônico na mesma UoW da reserva e revalidação na recuperação. Sem segunda persistência ou aceitação de upload do navegador como autoridade. Requer provisionamento autorizado dos documentos e revisão fiscal; não equivale à comprovação de autenticidade/aceitação externa. Testes escritos, não executados; sem CI, merge ou deploy; REC-04 segue aberto até certificação normativa e operacional.


## CURRENT reconciliado em 19/11/2026 — 59 IDs + SP-22/MG-20 + Cajamar

[Reconciliação individual do código CURRENT](./NFCORE_CURRENT_RECONCILIATION_59_TASKS_42_MUNICIPALITIES_2026-11-19.md), auditoria commit `f97ba0aacc5d11b6af7cf786f99b3184e80a7d39`, SHA de engenharia auditado `79bee7c64e3b2e984fb9517d190d2ca6b128a573`. Preservados IDs/ordem e provas históricas. As dimensões de engenharia, certificação, operação e dependências externas são independentes. Não reimplementar por checklist antigo. Cajamar é célula adicional; corrigidas jurisdição do candidato de substituição e montagem Contabo, permanecem GAP-CAJ-01/02/03. Inventário inicial individualizado, não auditoria exaustiva das operações. Nenhuma CI, merge ou deploy nesta rodada.


## CURRENT 19/11/2026 — delta de Cajamar após reconciliação 59/43

**SHA de engenharia:** `0cdd034a293696e376aafd70923a42bfe7dced0f`, ver `docs/operations/CAJAMAR_GEISWEB_RUNTIME_PROVISIONING.md`. Preservadas emissão/consulta de lote/cancelamento/XML e autoridade canônica. GAP-CAJ-01 avançou: intent durável, códigos incertos fail-closed e ConsultaNfse por nota original conectada a Portal/arquivo (`5430c180`, `c3c80feb`, `b129fe6e`, `b52ab1eb`). Sem status oficial inequívoco no manual público, confirmação final de cancelamento incerto depende de contrato/prova autenticada adicional; consulta não muda lifecycle. GAP-CAJ-02: revisão humana agora arquivada, sem simular substituição; integração da confirmação municipal exige formato/contrato comprovado. GAP-CAJ-03: indisponibilidade de impressão oficial em homologação documentada e refletida no Portal; PDF municipal não fabricado (`0cdd034a`). Testes novos escritos, ainda não executados. **IMPLEMENTED_NOT_CERTIFIED** no escopo entregue; não declarar Cajamar nem NFCore completo. Sem CI, merge ou deploy. Não reabrir construção existente sem evidência de regressão.
