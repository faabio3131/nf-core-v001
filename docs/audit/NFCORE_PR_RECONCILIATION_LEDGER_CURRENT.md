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

## CURRENT EXECUTADO — 17/11/2026 (checkpoint pós-reconciliação; substitui snapshots anteriores)

- **Repositório ativo:** faabio3131/nf-core-v001. **main** `549ab3c005d7183ff6c7940236414412ea004b9d`; **production** `ea4bdd3bcb9b61e6522081a14e5cc9ad1ced9599`; ambas **inalteradas**.
- **#468 OPEN/DRAFT HEAD funcional** `1237c96021286f82d4f473dbd27bf90dce89ca37`. Integrações de fato: #522 FIS-03 `56a7d50a`, #523 MF-04/BH `287f0856`, #525 cronograma/registro `2ef57d6a` e #526 caminho PKI `1237c960`, todas MERGED na candidata somente. #522/#523/#525/#526 não estão mais abertas.
- **#498 OPEN/DRAFT HEAD Web** `41dad4fab6e892a904b5f3afa94f2806b507ed29`. Mesma implementação fiscal/Portal da #468; **11 diferenças intencionais** da release para infraestrutura/histórico, incluindo backup/restore/testes de Compose e sobrescritas operacionais preservadas por blob/mode.
- **Evidência verificada:** CI integral #44105708197 SUCCESS após #522/#523; CI #44105962170 SUCCESS da #525; CI #44108045887 SUCCESS da #526 (5.364 Python PASS, 1 SKIP justificado, 78 Playwright PASS); T2/governança/Compose atuais verdes. **CIs dos SHAs finais #468 [#44110731608](https://github.com/faabio3131/nf-core-v001/actions/runs/44110731608) e #498 [#44110843645](https://github.com/faabio3131/nf-core-v001/actions/runs/44110843645) ainda requerem conclusão**, sem herdar selo de commits antigos.
- **Quantidade de PRs abertas na captura:** 2 (#468 e #498), ambas Draft. O cronograma e registro originais de 17/11 capturavam quatro PRs de engenharia antes destes merges; suas listas abaixo são **SNAPSHOTS HISTÓRICOS**, não o CURRENT.
- **ENGINEERING NOT DONE:** FIS-03 confiança oficial SEFIN/policies/NameConstraints/LTV; MF-04/BH retenções/deduções/catálogo por competência; SP-22 e MG-W1 matriz fiscal por operação; Louveira PF contrato 2026 não comprovado (issue #509); Core Cognitivo/Sentinela adequações remanescentes; EGM independente; Contabo DPSv22/cofre A1/backup/restore/staging e acesso mutante; testes contábeis e homologação externa. Não declarar V1 100% interna nem produção aprovada.
- **Regra de continuidade:** código CURRENT + PR/CI no SHA > esta nota > checkpoints antigos. **Não houve merge main, promotion production, deploy, DDL, DNS, segredo A1 real ou transmissão fiscal oficial.** Integrador único NFCORE-GOV-RELEASE-001 preservado.

---

# CURRENT verificado — 17/11/2026 — índice de continuidade (sem promoção)

**Nota documental:** [PR #525](https://github.com/faabio3131/nf-core-v001/pull/525) OPEN/DRAFT de documentação, criada após a captura das quatro PRs de engenharia; agora existem 5 PRs abertas (4 funcionais/release + 1 documental). REC-22 registra verificação pendente do Core Cognitivo/Sentinela sem presumir capacidade normativa automática. A documentação ainda não foi integrada à #468.

**Cronograma de fechamento:** [NFCORE_RECONCILIATION_CLOSEOUT_SCHEDULE_2026-11-17.md](NFCORE_RECONCILIATION_CLOSEOUT_SCHEDULE_2026-11-17.md). **Inventário completo:** [NFCORE_PENDING_REGISTER_CURRENT_2026-11-17.md](NFCORE_PENDING_REGISTER_CURRENT_2026-11-17.md), com 4 PRs, 14 issues e matrizes SP-22/MG-W1. Este registro novo PREVALECE para CURRENT sobre os snapshots datados de 16/11 abaixo; os anteriores ficam preservados integralmente como histórico.

- main 549ab3c005d7183ff6c7940236414412ea004b9d; production ea4bdd3bcb9b61e6522081a14e5cc9ad1ced9599. **Nenhuma promoção/deploy/DDL**.
- #468 OPEN/DRAFT e1632e646e3ed8e960ba51c88d24facf3177ffc7; #498 OPEN/DRAFT fbdb33843103d25c44b1e1896629c588c4a1b423. #520/#521 integradas à #468; #498 conserva infraestrutura da release anterior.
- #522 OPEN 42fa40fb5cd8a7e6748f9834c679f66744659cbc, CI [44081550101](https://github.com/faabio3131/nf-core-v001/actions/runs/44081550101) SUCCESS; #523 OPEN 7962fe7b81c8f23cbbc84865fa7705819fcddd38, CI [44015740152](https://github.com/faabio3131/nf-core-v001/actions/runs/44015740152) SUCCESS. **Ainda não integradas à #468**; passam a REC-01.
- #468 no MESMO SHA teve CI [43952570819](https://github.com/faabio3131/nf-core-v001/actions/runs/43952570819) SUCCESS seguida da [43999832959](https://github.com/faabio3131/nf-core-v001/actions/runs/43999832959) FAILURE: 5.293 PASS/1 FAIL/1 SKIP, teste de trial expirado (200 esperado, 409 recebido). As duas branches #522/#523 contêm o mesmo teste temporal reparado, sem abrir trial expirado; aplicar uma vez e provar na CI cumulativa.
- #498 possui CI própria anterior SUCCESS no seu SHA; após novos merges precisa de CI renovada. **CI verde individual não certifica release cumulativo**.
- **Pendências internas ainda abertas:** FIS-03 confiança/revogação/LTV/credenciamento, MF-04 BH normativo, SP-22, MG-W1, Louveira PF, revisão EGM, cobertura e semântica das 96 origens, conciliação da Web, release/host. **Separar bloqueios externos** (contratos municipais/credenciais/certificados/homologações) dos internos.
- **Próximo gate:** integrador único reconcilia #522/#523 na #468, resolve drift de CI e testa HEAD; depois fecha engenharia + EGM, recompõe #498, audita Contabo e prepara promoção protegida, na ordem do anexo. Nenhum checkbox antigo ou cobertura municipal foi promovido por este índice.

---

## CURRENT — release Web conciliada, 16/11/2026

Esta entrega une a release #498 `f4a94926d3ceff7d66203eef270372177052fd91` à candidata #468 `e1632e646e3ed8e960ba51c88d24facf3177ffc7`. A candidata integra #520 e #521; sua árvore é idêntica à origem de Guarulhos `d7fd30ee411ac12f691a957a9a204b9c1f46d737`. SHA resultante e CI final registrados na PR #498; não herdar certificação de outra revisão.

- #520: CI43947807754 SUCCESS, 5.259 Python PASS / 1 SKIP / 75 Playwright PASS; T2 efetivo SUCCESS. Integrada em af1f7b58.
- #521: CI43950288422 SUCCESS, 5.294 Python PASS / 1 SKIP / 78 Playwright PASS; T2 efetivo43950367595 SUCCESS. Integrada em e1632e64. Skip somente variante SQLite exclusiva PostgreSQL; variante PG executada. Segurança, containers, SBOM e backup/restore passaram no runner; não comprovam o host produtivo.
- Revisão independente Guarulhos encontrou e confirmou correções do serviço Compose e da dupla permissão em recovery; nenhum bloqueador adicional nesse delta. Reemissão sequencial não é substituição municipal atômica; homologação real não executada.
- Cinco deltas exclusivos da release preservados: worker host-db overrides, testes, workflow e restore-test.sh com modo100755. Revisão confirmou blobs/modos e ausência de perda da candidata. Checkpoint histórico BH preservado por SHA256; mapas de sucessores documentam as origens423/440.
- #423: mecanismos MG/WebISS/nacional preservados, 176 testes focais PASS. #440: sucessores canônicos, sem segunda API/contador. Podem ser encerradas como SUBSTITUÍDAS após publicação/gates desta reconciliação, nunca como MG20/BH concluídos. Pendências normativas, E2E operacional, EGM e homologação permanecem na issue426 ABERTA.
- Main549ab3c0 e productionea4bdd3b não promovidas. O proprietário autorizou concluir e publicar; Desktop Commander tem cota0 e o SSH GitHub conhecido é somente leitura. Sem acesso operacional, não comprovar schema DPS22/cofre/backup/restore/staging nem controlar auto-pull. Nenhum deploy, migration ou emissão real realizado. Não declarar lançamento comercial pronto.

## CURRENT — MF04 integrado; Guarulhos corrigido após revisão, 16/11/2026

#520 MERGED na candidata `af1f7b58794beba42a92718dea40a44fb1ef90fa`, origem `009c72a1`. CI completa [43947807754](https://github.com/faabio3131/nf-core-v001/actions/runs/43947807754) SUCCESS e T2 efetivo fora de Draft43949507844 SUCCESS. Main/production permanecem `549ab3c0`/`ea4bdd3b`; nenhum deploy.

#521 sincronizada com essa candidata. Revisão independente encontrou dois defeitos: nome de serviço do override (`api`→`nfcore-api`) e dupla permissão ausente em recovery direto. Corrigidos: `FiscalIntentRecovery.allowed()` governa prepare, validate/resume/replay e listagem, inclusive outros canais de substituição já suportados. Papéis atuais agrupam CANCEL+ISSUE; teste de revogação parcial garante a invariável. Cajamar não ganhou endpoint novo: sua revisão não está na superfície recovery e continua bloqueada.

Prova independente: prepare200 com ambas permissões; após retirar ISSUE, resume403/zero dispatch; CANCEL-only bloqueado em prepare e endpoint direto. Testes novos cobrem6operações×2estados (prepared/recorded), listagem e replay. Suite recovery SQLite PASS/variantes PG SKIP;14gateway PASS. Ruff/Mypy421 PASS antes da sincronização; retestar composição MF04+Guarulhos. CI da origem anterior de #521 não certifica este novo HEAD. Revisão sem bloqueador adicional condicionada às correções publicadas/CI exata. Testes locais e browser/PG remotos não são homologação externa. Acesso mutante ao host permanece indisponível; publicação e DPS22/cofre/restore/staging permanecem pendentes.

## CURRENT — Guarulhos em validação, 16/11/2026

Base confirmada `81914807d3253ebe15e6cce93640f1157f222fe3`; main `549ab3c0` e production `ea4bdd3b` permanecem sem promoção. #519 integrada; main é ancestral da candidata. CI cumulativa [43945724238](https://github.com/faabio3131/nf-core-v001/actions/runs/43945724238) SUCCESS. #518 recuperou seis fontes por SHA256; #413/#448/#453 encerradas com evidência e branches preservadas.

#520 implementa decisão tributária nacional governada; HEAD `009c72a172b7ab065c70faebbb492aa045e08024`, CI [43947807754](https://github.com/faabio3131/nf-core-v001/actions/runs/43947807754) em execução. Não integrada neste checkpoint. Lacuna de trigger corrigida: PRs para `integration/nfcore-*` executam todos os mesmos gates, sem redução.

Guarulhos: composição opt-in da família GISS, 24 schemas compartilhados por hash, município explícito, eventos e Portal/RBAC/recovery existentes. Plano `docs/audit/NFCORE_GUARULHOS_OPERATIONAL_PLAN_20261116.md`; runbook `docs/operations/NFCORE_GUARULHOS_REVIEWED_GISS.md`. 11 testes HTTP Jundiaí/Guarulhos e 51 testes focais PASS; Ruff/Mypy421 PASS; frontend26 PASS/lint/typecheck/build. Suíte integral local em execução. Três testes browser adicionados; execução local bloqueada pelo download truncado e pela restrição de socket do Chromium instalado. CI remota obrigatória; NÃO COMPROVADO até executar. Revisão independente em andamento.

O usuário reiterou concluir e depois publicar. Desktop Commander retorna cota de chamadas0; único canal SSH GitHub auditado é somente leitura. Driver Contabo de promoção não está provisionado na árvore (existem Railway/unconfigured). Não usar credencial restrita para mutação nem mover production com auto-pull sem controle. Nenhum deploy ou migration realizado. DPS22/cofre/restore/staging, homologações reais, confiança ICP/revogação e cobertura fiscal ampliada permanecem pendentes; não declarar lançamento pronto.

## CURRENT — MF-09 integrado na candidata, 16/11/2026

- Candidata #468: `cac2a1e38058ca4b6a811d337eea270561cd8223`, após merge da #517. Branch `integration/nfcore-a1-sp2-current-main-20261113`. Árvore `fc9fb39603464db854178136a1b4b6b4d74fc880` idêntica à origem `1bd7449c7204f0ca3992f048c06f679cef0758d5`.
- CI da origem [43929948306](https://github.com/faabio3131/nf-core-v001/actions/runs/43929948306) SUCCESS: 5.240 Python PASS, 1 SKIP, 75 Playwright PASS, gates de segurança/container/restore aprovados. Skip somente variante SQLite exclusiva PG; variante PG executada. T2 efetivo [43933259955](https://github.com/faabio3131/nf-core-v001/actions/runs/43933259955) SUCCESS após tornar explícita a evidência E2E na descrição. Nenhum gate ou teste desabilitado.
- CI cumulativa [43933409094](https://github.com/faabio3131/nf-core-v001/actions/runs/43933409094) em execução neste checkpoint. Não tratar CI da origem como resultado do merge.
- Venda manual usa a mesma preparação, domínio, regras e arquivo; NF-e 55 SP/MG e NFC-e 65 MG online em homologação. Adoção da numeração legal requer inventário/reconciliação de legado e parada de writers antigos. Nenhum deploy, DDL ou emissão real.
- Recuperação histórica na #518: quatro documentos e dois patches, fontes exatas e revisão independente aprovadas. Gates documentais e T2 fora de Draft passaram no HEAD anterior `9e4f846b`; este checkpoint muda o HEAD e exige novos checks aplicáveis. #413/#448/#453 permanecem abertas até integração comprovada.
- Main `549ab3c0` e production `ea4bdd3b` inalteradas. A aprovação comercial #390 já está na main, mas ainda não é ancestral da candidata: conciliar antes da promoção. #498 continua Draft; cinco deltas de infraestrutura devem ser preservados.
- Pendências: MF-04/BH, confiança/cadeia/revogação/histórico de recibos, Guarulhos, MG20/SP22, EGM, DPS22/cofre/backup/staging e publicação. Auditoria MF-04 encontrou o objeto tributário canônico existente, mas ausência de resolução governada na preparação HTTP; 21 testes focais PASS não encerram esse bloco. Decisão/proposta e fontes registradas no corpo da #468.
- Próxima ação: conferir CI cumulativa, integrar recuperação documental sequencialmente, encerrar origens somente com prova e conciliar a release Draft. Produção permanece NO-GO.

## Recuperação documental em revisão — 16/11/2026

#468 permanece em93534458, CI43926134508 SUCCESS; main549ab3c0 e productionea4bdd3b inalteradas. #517 MF09 publicada em1bd7449c, árvorefc9fb396 idêntica ao commit localab1a56a0, CI43929948306 em execução neste registro; reconsultar antes de integrar. Revisão independente confirmou equivalência dos24 caminhos e nenhum bloqueador novo.

Auditoria das PRs413/448/453 identificou quatro documentos ausentes e acréscimos históricos não incorporados. Recuperação estritamente documental com fontes/hash/limites em `NFCORE_DOCUMENT_RECOVERY_20261116.md` e manifest JSON. As três PRs permanecem abertas até integração e gates desta recuperação; não rotulá-las como incorporadas antes disso. Pendências fiscais e operacionais não foram resolvidas por recuperar documentos.

# NFCore — reconciliação em execução, 16/11/2026

O proprietário autorizou nesta conversa reconciliar o trabalho existente, concluir pendências das PRs e atualizar a aplicação web. Essa autorização cobre a integração e o deploy após validação. Emissão oficial e operações destrutivas de dados exigem decisão específica. A auditoria recebida é diagnóstico de entrada, com decisões técnicas a validar.

## CURRENT — retomada MF-09 e integração #516, 16/11/2026

- main549ab3c005d7183ff6c7940236414412ea004b9d; productionea4bdd3bcb9b61e6522081a14e5cc9ad1ced9599, conferidas novamente no GitHub. Nenhuma publicação realizada nesta retomada.
- #515 integrada: candidata9bd66f7366fad2895df78489f3ca6ca2157120b0.
- #516 agora MERGED na candidata#468:93534458a4f2e3d4879ead703bf407f346a1fa35. HEAD origem169384489e87ed8e790d349060a7282f202f4689, CI43921916359 SUCCESS:5197Python PASS/1SKIP/71Playwright PASS. Skip somente variante SQLite de teste exclusivamente PG; versão PG executa. T2 fora de Draft43925653026 SUCCESS.
- CI cumulativa43926134508 em execução no momento deste registro; reconsultar no SHA93534458.
- PRs abertas após integração:413,423,440,448,453,468,498. Fechamento administrativo não equivale a homologação ou publicação.
- Delta MF09: formulário manual, regras/perfis do servidor, preparação55/65, numeração legal única, assinatura, arquivo, transmissão/consulta e PDFs existentes. Defeitos de numeração/replay/namespace descobertos e corrigidos conforme plano MF09. Revisão independente163PASS/25PG SKIP/0FAIL; testes locais adicionais de namespace e suíte integral em fechamento. Novo bloco ainda exige PR/CI exata.
- Pendências globais preservadas: MF04/BH; confiança/cadeia/revogação e histórico de recibos nacionais; ciclo municipal Guarulhos; Louveira PF contrato próprio; revisão das origens/documentação ainda aberta; reconciliação release498 e gates de host/cofre/DPS22/backup/publicação. MG20 e SP22 não são declarados completos.

## CURRENT — pós-#514, 16/11/2026

Este checkpoint substitui os estados históricos abaixo; pendências não marcadas como resolvidas permanecem abertas.

- #514 MERGED somente na #468: `2eb7858dfa669b27b2804d846c876ec19b025672`. Árvores de origem bfd5d0d4 e integração2eb7858d iguais: `699739fd9df8c732e3627be9902b2a33654b75b7`. [CI43912553533](https://github.com/faabio3131/nf-core-v001/actions/runs/43912553533) SUCCESS,5111 Python PASS/3 SKIP,71 Playwright PASS. [T2 efetivo43915564090](https://github.com/faabio3131/nf-core-v001/actions/runs/43915564090) SUCCESS fora de Draft, log Bloco completo. [CI cumulativa43915895064](https://github.com/faabio3131/nf-core-v001/actions/runs/43915895064) em execução neste registro.
- #515 correlação SP retargetada para #468, HEAD9cfe2e07, Draft, [CI43913718612](https://github.com/faabio3131/nf-core-v001/actions/runs/43913718612) em execução. Correlação preserva campos opcionais das rejeições. Revisão independente e136 testes focais PASS; integral local sem falhas, com PG pulado.
- #437 CLOSED WITHOUT MERGE, origem619a051cef2346c835ada4ed5accbf7f8881e7bf, incorporada em #468@ab93ef0d. Quatro arquivos idênticos: gateway/webiss_extrema_canonical.py, tests/e2e/extrema_webiss_ui.spec.js, tests/web/test_extrema_nfse_events_http.py, tests/web/test_extrema_nfse_preparation_http.py. As três funções Portal appendExtremaNfsePreparation/Cancellation/Substitution são idênticas; teste durable_flow só tornou exceção de conflito específica. Prova completa no corpo da PR, branch preservada. #434 ainda aberta; não inferir fechamento dela.
- #508 origem0f98472ff32731636ef153d9eddaf4fb937b2759:18 caminhos comparados contra2eb7858d.14 idênticos. Deltas restantes: service.py e composition.py adicionam pre-dispatch NT009; native preparation adiciona cTribMun/preflight; testes HTTP passam a NT009 e incluem BH, mantendo jornadas Louveira/Guarulhos. Fechamento administrativo pendente da CI cumulativa; não declara Guarulhos completo.
- [Auditoria43758223307 tentativa2](https://github.com/faabio3131/nf-core-v001/actions/runs/43758223307) EXECUTOU às16:57UTC em16/11: SSH autenticado/SHA instalado ea4bdd3bcb9b/API/Portal/containers/backup recente/schema20-21 PASS. Falha específica de prontidão Bling: flag API, montagens de segredos/política, artefatos de política e worker PENDING. OAuth, pedido real e A1/SEFAZ UNVERIFIED_EXTERNAL. DPSv22/cofre A1/offsite/restore isolado/staging/auto-pull não são comprovados por esse script. Não aguarda mais revisão humana. Nenhum deploy ou DDL executado por esta rodada.

### Incremento FIS-03 em validação

Base9cfe2e07; plano em `NFCORE_FIS03_RECEIPT_CONTRACT_PLAN_20261116.md`. Núcleo de integridade reaproveitado; nacional exige XSD NFSe NT009, contexto canônico e chave/emitente/DPS coerentes. Assinatura DPS aninhada opcional é verificada quando presente; assinatura em outra posição e IDs duplicados rejeitados. POST verifica identidade antes de TLS/rede; GET divergente não reenvia. Preflights de XML arquivado nacionais usam o mesmo contrato. Simpliss conserva schema municipal e importa diretamente o núcleo de integridade.

Fixtures positivas passaram a NFSe completa contendo a DPS efetivamente enviada.148 testes focais PASS no delta após últimas correções (incluindo25 regressões de contrato e jornadas HTTP), Ruff PASS e Mypy418 fontes PASS no código final. Suíte integral final4677 PASS/521 SKIP (sem DSN PostgreSQL local),2 avisos de depreciação;36 testes antigos de recibo reexecutados com contexto explícito PASS. Revisão independente final:122 testes focais e24 HTTP PASS, sem bloqueador remanescente identificado; não é execução original EGM. CI remota do HEAD publicado ainda necessária. Confiança ICP/SEFIN/cadeia/revogação e perfil histórico persistido continuam pendências explícitas. Número/data/DV da chave não certificados neste incremento.

Próxima ação: reavaliar delta final FIS-03, publicar para CI e integrar sequencialmente na candidata após gates; conferir #515/#468 e atualizar #498 preservando seus5 deltas. Nenhuma promoção main/production até conclusão real de engenharia e operação.

## Baseline preservado

- main `549ab3c005d7183ff6c7940236414412ea004b9d`.
- production `ea4bdd3bcb9b61e6522081a14e5cc9ad1ced9599`.
- Candidata #468 `f4724afba13257374f065c87dffb5b55c40d71e9`.
- Release #498 `41103876947f4daf264c27589384dca88173a569`.
- Todas as 96 origens da planilha foram recuperadas por refs de PR. O manifesto registra SHA imutável e ancestralidade. Ancestralidade é evidência histórica, sujeita à revisão de comportamento e eventuais reversões.

## Incremento cognitivo #486

Origem `21a7e3fb5c46785ec0bd370592d66bbf15eb531d`. Aplicados os oito arquivos do patch original sobre a candidata, depois de examinar alterações de código e testes. Nenhum conflito textual.

| Arquivo/símbolo | Decisão | Prova local |
| --- | --- | --- |
| cognitive/api.py — create_cognitive_router | Incorporar validação e normalização subject_id | test_validation_errors_and_not_configured |
| cognitive/context.py — ContextPackBuilder.build | Incorporar escopo, origem e instante no hash | test_context_hash_separates_tenants_units_and_evidence_origin |
| cognitive/guardrails.py — OutputGuard | Fundamentar números em evidências confiáveis citadas na seção | testes adversariais test_context_and_guard.py |
| cognitive/portal_evidence.py — PortalSurfaceEvidenceProvider | Filtrar documento e marcadores tenant/unidade divergentes | testes HTTP test_api.py |
| cognitive/service.py — _maybe_call_model | Preservar baseline quando não há audit sink | test_missing_audit_sink_blocks_model_but_preserves_baseline |

Validação local do patch e candidata em Python 3.12: suíte tests/cognitive passou com dois testes PostgreSQL pulados por ausência de banco local. Ruff aprovado. Mypy aprovado nos 34 módulos cognitivos. CI integral com PostgreSQL e Python 3.11 ainda pendente. A #486 permanece aberta até prova de incorporação no destino.

## Revisão independente do roteiro

Revisores em contextos novos executaram a etapa 9 do protocolo EGM usando personas Implementation Readiness, Codebase Details e Style. O roteiro exige refinamento por subbloco. Revisão do roteiro não certifica o produto.

Correções aplicáveis ao trabalho:

- A conclusão global continua abrangendo as pendências de engenharia existentes. Publicação intermediária não encerra a missão nem altera o estado da cobertura municipal.
- A triagem cobre todas as 96 origens, incluindo as encerradas antes de novembro.
- A autorização vigente será reaproveitada nas ações cobertas, mantendo os checks técnicos e a proteção efetiva do GitHub.
- Antes de promover production, inspecionar o auto-pull real. Se ativo, coordenar sua suspensão e aguardar CI do SHA promovido antes da instalação. Registrar mecanismo e execução efetivos.
- Decisões de contratos HTTP, seleção de schema e confiança do XML serão registradas junto de cada implementação e seus testes.

## Pendências em andamento

Revisão semântica das origens restantes, BH/NT009, Louveira/Guarulhos, MF-09, MF-04, confiança do GET nacional, verificação das operações MG/SP, certificação cumulativa, promoção e verificação do servidor. Nenhuma conclusão global ou publicação foi realizada por este incremento.


## Checkpoint de integração — 16/11/2026, 15h UTC

- PR #513 integrada à candidata #468: `ab93ef0d3b03b8e0b41cda686f83fdff2fed808d`. Nenhuma mudança em main/production por este merge.
- HEAD cognitivo validado: `8ccbe41057507025ff93a6635dddc6a55e1576e7`; [CI43888420172](https://github.com/faabio3131/nf-core-v001/actions/runs/43888420172) SUCCESS:5027 testes Python passaram,3 pulados;69 Playwright passaram; gates PG/imagens/segurança/restore aprovados. [T2 fora de Draft43892327257](https://github.com/faabio3131/nf-core-v001/actions/runs/43892327257) aplicado, log `Bloco completo`. CI pós-merge da candidata [43892521240](https://github.com/faabio3131/nf-core-v001/actions/runs/43892521240) em andamento neste checkpoint.
- PR #514 publicada em Draft no SHA `4cbbeeb5822ca8c5fcc559cc7f119639bd6b3d03`: #508 recuperada e perfil DPS nacional NT009. Suíte Python local passou, com dependentes de PG pulados por ausência de DSN; Ruff/Mypy417 módulos e Portal lint/typecheck/build/26 testes passaram. Chromium local falhou no download; navegador e PG dependem da CI deste SHA. Isso não encerra as pendências do release.
- Revisão independente do NT009 encontrou validação tardia de série e bypass no transporte HTTP de baixo nível. Ambos corrigidos; re-revisão não encontrou novo bloqueador no delta. Testes verificam série89999/90000, preservação READY_TO_TRANSMIT e ausência de A1/rede na recusa. Preparação municipal mantém seu próprio contrato.
- Fontes das96PRs foram recuperadas com paginação completa:2496 ocorrências de caminhos, registradas por blob no manifesto. Comparação automática de arquivos/AST serve à triagem; decisões funcionais ainda pendentes continuam explícitas.

### Contrato NT009 deste incremento

O ZIP foi obtido da [documentação oficial de homologação](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/producao-restrita), por sua rota de download `@@download/file`. Os dez membros foram preservados sem normalizar quebras de linha. O manifest está no pacote `NFSE_NACIONAL_1.01_NT009_20261020`. Comparação contra #440: quatro membros idênticos e seis diferentes. Não rotular o espelho anterior como ZIP oficial.

O perfil é escolhido pela data operacional do endpoint e pelo ambiente, não pela competência retroativa nem pelo município. O fluxo nacional usa NT009 em homologação desde20/10/2026; a função legada continua disponível para Simpliss municipal. O seletor impede assumir o pacote de produção após a mudança anunciada para01/12/2026 sem nova revisão. O gateway nacional existente permanece exclusivamente homologação.

O novo pacote compila DPS, NFSe, pedido e retorno de evento. O incremento inicial conectou DPS à execução. O ajuste de retomada conecta também pedidos e retornos de eventos; NFSe recebido/GET, confiança ICP/revogação e proveniência persistente do perfil continuam pendentes.

### Acesso operacional

Desktop Commander retornou limite mensal esgotado, impedindo a via anterior ao PC/SSH. Os workflows históricos de auditoria não comprovam o estado atual de migration22, A1, restore ou auto-pull. Nenhum deploy, DDL produtivo ou emissão oficial foi executado. Essa limitação operacional não transforma pendências de código em externas.

### Port seletivo BH — classificação municipal

Recuperado de #440 o desdobramento de três dígitos `cTribMun`, usando `municipal_taxation_detail` no modelo canônico existente. Preservado no fingerprint, arquivo fiscal, formulário nativo e nos dois perfis DPS; ausência mantém a compatibilidade dos arquivos antigos. Nenhuma segunda numeração, rota BH ou campo NBS paralelo foi criado. Revisão independente do delta não encontrou bloqueador introduzido. Testes locais cobrem formato ASCII, XSD dos dois perfis, arquivo e adulteração, replay e conflito autenticado. O teste Playwright novo usa HTTP simulado e comprova apenas apresentação/contrato do formulário.

| Comportamento original #440 | Destino e decisão |
| --- | --- |
| cTribMun obrigatório quando local do serviço é BH | Campo recuperado; obrigatoriedade não portada. Depende de política revisada de incidência do ISS, que não pode ser inferida apenas do local do serviço. |
| NBS obrigatório para BH desde competência 2026 | Campo canônico existente reutilizado. Obrigatoriedade, aplicabilidade e vigência continuam pendência interna. |
| Regime especial explicitamente revisado em BH | Modelo canônico tem tratamento tributário próprio. Equivalência e prevenção de defaults indevidos ainda pendentes em MF-04. |
| Combinação cTribNac/cTribMun válida | Formato e XSD verificados; validação contra tabela municipal e município de incidência ainda pendente. |
| Ciclo fiscal BH | Preparação/readback não certificam autorização, substituição, cancelamento, recuperação, confiança do recibo ou homologação externa. |

A primeira CI de #514 falhou na coleta por importação de namespace de testes ausente no runner. Corrigido isoladamente em `d1a84e30e0d8409aa9d90e5347fb0640a9b0e74c`: testes de perfil movidos para o diretório de seus helpers e dependência do módulo de testes de persistência removida; 22 testes locais do perfil/cTribMun passaram. Nova CI integral necessária nesse SHA.


## Retomada verificada — 16/11/2026

CURRENT remoto: main `549ab3c005d7183ff6c7940236414412ea004b9d`; #468 `ab93ef0d3b03b8e0b41cda686f83fdff2fed808d`; #514 `4deb6f4884757093c09c1d7cc634723ab3aeb092`. CI cumulativa #43892521240 SUCCESS. #486 já encerrada como incorporada pela #513. Permanecem 18 PRs abertas contando a #514.

A CI #43894496103 da #514 falhou no Ruff (ordem de imports dos testes), antes de Mypy/Pytest. Corrigida a ordem sem excluir testes. O incremento em revisão conecta pedido/retorno de cancelamento ao mesmo pacote oficial NT009 de homologação, selecionado pela data operacional do endpoint; preserva o contrato municipal Simpliss. A fixture de Salto foi corrigida para usar a estrutura de chave exigida pelo schema, mantendo assinatura e fluxo HTTP reais com transporte sintético. Ruff/Mypy (417 fontes) aprovados e 101 testes dirigidos passaram localmente. Suíte integral e revisão independente estão em execução; CI deste incremento ainda não comprovada.

Escopo aceito deste incremento: schema/roteamento de DPS e eventos nacionais, recuperação da #508 já implementada, cTribMun na preparação canônica. Não conclui Guarulhos, BH integral, MF-04/MF-09, GET XSD/ICP ou release global. Não confundir merge incremental na candidata com certificação desses blocos.

Auditoria Contabo #43758223307, tentativa 2: WAITING, environment `nfcore-contabo-audit`, revisor requerido `faabio3131`. O SSH não foi executado nesta tentativa enquanto o gate aguarda. A execução #43118619235 é anterior e falhou por SHA esperado obsoleto; não é a auditoria corrente. Nenhum DDL, deploy ou mudança em production realizado nesta retomada.

Revisão independente da retomada (`review_national_delta`, contexto isolado): 112 testes dirigidos e 18 testes HTTP selecionados passaram; nenhum bloqueador ou regressão concreta no delta revisado. Inspeção confirmou seleção nacional por ambiente/data, contrato próprio Simpliss e recusa antecipada da série 90000 sem A1/rede/claim. Não equivale a execução do protocolo EGM original nem a homologação fiscal externa.

## Revisão semântica de origens e correção SP — 16/11/2026

Revisor independente `review_legacy_equivalence` examinou #461/#450/#446/#449 e MG/Extrema. Execuções focais: 269 testes sem falhas; outro conjunto 214 PASS/10 deselected. Worktree evoluiu durante revisão de `4deb6f48` a `c8d1c6b9`; esses números não são certificação imutável da árvore inicial.

| Origem | Decisão por comportamento | Evidência CURRENT / pendência |
| --- | --- | --- |
| #461/#450/#446 — gateway `nacional_query` | Superado pelo `national_query`; não copiar fixture sem assinatura ou contador derivado | Binding QUERY, DPS reservado, A1, XMLDSig e recuperação HTTP. Diferença 404→erro ambíguo (antes PENDING) permanece decisão/teste a concluir. |
| #461/#450/#446 — preflight SP | Não restaurar veto estadual genérico a NORMAL | Canal exige análise municipal; Salto/Louveira NORMAL têm adesão própria. Guard nacional SP municipal permanece em auditoria. |
| #446 — inutilização SP | Rejeitar proibição universal antiga | Política de transição permanece; encontrado e corrigido defeito de correlação dos retornos SP em delta dedicado. |
| #449 — DPS/hash e preparo | Numeração derivada substituída por reserva durável canônica; HTTP/codec/arquivo/DANFSe preservados | Testes de serial reservado, replay, CSRF, escopo e codec atuais. Não criar segundo contador. |
| #423 — MG/RTC | Guard/canais/ordenação e binding preservados | Isso não conclui MG-W1 20/20. Manter PR ativa enquanto escopo municipal continuar incompleto. |
| #430 — diagnóstico WebISS | Incorporação literal confirmada em #468 `ab93ef0d`, CI #43892521240 SUCCESS | PR encerrada como SUPERSEDED_WITH_PROOF em 16/11; branch original preservada. |
| #432 — documento upload WebISS | Histórico por SHA; não republicar como CURRENT | Materializar vínculo histórico no manifesto/ledger; pacote e testes posteriores presentes. |
| #434/#437 — Extrema | Funções de substituição/cancelamento preservadas: somente nota substituta 124, nunca original | Testes durable_flow e Web/API atuais passam. PRs permanecem abertas até conclusão documental da equivalência completa. |

GET Nacional ainda aceita fixtures assinadas sem conteúdo fiscal completo: ausência de XSD/trust e correlação com DPS/CNPJ é pendência real de FIS-03, não justificativa para importar o gateway legado. Revisão do patch SP e fontes estão em `NFCORE_SP_RESPONSE_CORRELATION_REVIEW_20261116.md`.


## Continuidade — integração documental e mecanismo MF-04, 16/11/2026

#518 MERGED na candidata em0ebb510a, árvore5c92bfc1 igual à prévia; seis fontes do manifesto preservadas. PRs413/448/453 CLOSED com evidências nas descrições; branches mantidas. CI43943547457 SUCCESS. #519 MERGED em81914807 após governança/T2/revisão independente; árvore67a1a070 coincide com merge previsto e recupera dois documentos da main549ab3c. Main agora ancestral da candidata, sem promover main ou production.

Mecanismo tributário nacional implementado em branch `feat/nfcore-national-tax-treatment-20261116` sobre81914807; ainda em validação para PR. Plano/impacto/aceite/revisões: `NFCORE_MF04_GOVERNED_TREATMENT_PLAN_20261116.md`. Instalação e limites: `../operations/NFCORE_NATIONAL_TAX_DECISIONS.md`. Não interpretar isso como fechamento de BH ou tributação universal. Demais lacunas fiscais/operacionais permanecem abertas. Em16/11 o Desktop Commander confirmou0% de cota remota restante; via PC/SSH continua indisponível. Fluxos GitHub de auditoria/promoção são alternativa a verificar, sem contornar aprovações humanas efetivas.
