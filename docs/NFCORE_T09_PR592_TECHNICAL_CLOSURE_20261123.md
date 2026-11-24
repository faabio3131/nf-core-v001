# NFCore T09 — Termo de encerramento técnico da PR #592
**Data da decisão:** 23/11/2026 · **Produto:** FM NFCORE V1 · **Repositório:** `faabio3131/nf-core-v001`

## 1. Decisão aprovada do Diretor e escopo congelado

**DECISÃO APROVADA:** encerrar a entrega **técnica** T09 separadamente da curadoria **jurídico-documental** de SE, AP, PA e RR. Apenas documentação e gate de release foram atualizados neste fechamento. **Nenhum cálculo, regra do motor fiscal, cadastro/importador, API, teste ou contrato de segurança foi modificado.**

**CURRENT técnico certificado**: PR [#592](https://github.com/faabio3131/nf-core-v001/pull/592), branch `feat/nfcore-economy-t09-state-catalog-27ufs-20261121`, HEAD-fonte certificado `d4d5f295d3ccbd42c6fc0b76726e5c53f832fb3a`. [CI integral #45261283697](https://github.com/faabio3131/nf-core-v001/actions/runs/45261283697) **SUCCESS** no HEAD exato: **6.929 Python PASS, 81 E2E PASS, 0 falhas, 2 SKIP, 8 warnings**, job principal **43 etapas SUCCESS**. Os **7 workflows auxiliares** do HEAD também foram SUCCESS (governança, completude, fontes oficiais e kit operacional).

**Veredito de engenharia**: `T09_ENGINEERING_CERTIFIED_INTERNAL`. Não significa homologação fiscal externa, curadoria 27/27 aceita, regra estadual aprovada nem prontidão comercial total.

## 2. Separação que passa a governar o release

| Objeto | Estado de encerramento | Efeito |
|---|---|---|
| Motor T09, aplicação, proteção do importador e testes | **CERTIFICADO INTERNAMENTE** no SHA-fonte `d4d5f295d3ccbd42c6fc0b76726e5c53f832fb3a` | Gate técnico aprovado no HEAD-fonte; não exige a ativação de benefícios das quatro UFs |
| Benefício SE (PSDI, seis modalidades) | **BLOQUEADO / NÃO IMPORTÁVEL** | Sem efeitos fiscais, nenhuma concessão presumida |
| Benefício AP (pescado, Decreto 3.599/2001) | **BLOQUEADO / NÃO IMPORTÁVEL** | Normas de pescado de 2026 não equivalem a concessão automática |
| Benefício PA (Lei 6.913/2006 / sucessão Lei 8.930/2019) | **BLOQUEADO / NÃO IMPORTÁVEL** | ADI 3779 impede invocar lei histórica isolada, não prova inaplicabilidade de toda sucessão |
| Benefício RR (RICMS-RR Anexo I art.1º LXVII) | **BLOQUEADO / NÃO IMPORTÁVEL** | Prazo histórico até 31/12/2025, extensão estadual 2026 não comprovada |

A classificação de bloqueio documental externo significa **prova a obter de publicadores/autoridades oficiais**: pesquisa, coleta de documentos públicos e hashes são atribuições da **curadoria técnica NFCore**, não do Diretor. Não converter indisponibilidade de portal em certidão negativa ou criar `APLICAVEL_CERTIFICADO` / `NAO_APLICAVEL_CERTIFICADO` gerais sem o conjunto probatório correspondente.

**Não transferir** benefícios com `legal_benefit_certified=false` para cálculo/emitir incentivo; não fazer merge da futura curadoria neste bloco. Checklist único: [backlog jurídico SE/AP/PA/RR](NFCORE_T09_4UF_FUTURE_CURATORIA_SINGLE_CHECKLIST_20261123.md).

## 3. Evidências existentes preservadas

- Documentação versionada: `NFCORE_T09_27UF_EVIDENCE_MATRIX_20261123.json`, `NFCORE_T09_DOSSIE_RECONCILIATION_V1.json`, `NFCORE_T09_FOUR_STATE_TERMINAL_OPERATIONS_20261123.json`, `NFCORE_T09_4UF_REAUDITORIA_JURIDICA_FINAL_20261123.md`.
- [Coleta oficial #45260593829](https://github.com/faabio3131/nf-core-v001/actions/runs/45260593829): 20 fontes tentadas, 11 capturas verificadas com SHA-256 e 9 indisponíveis; manifesto `NFCORE_T09_4UF_NEW_PRIMARY_CAPTURE_20261123.json`. Cópia durável: `/NFCore Commercial Launch/T09 Legal Evidence/NFCORE_T09_4UF_SOURCE_CAPTURE_e131e883_20261123.zip`.
- A presença de arquivo hashado não altera o status jurídico do conteúdo. O documento de curadoria posterior deverá certificar a cadeia por modalidade/competência e registrar revisão independente.

## 4. Gate de integração: Draft → revisão → merge

**ESTADO REAL NA DATA DO FECHAMENTO:** PR #592 **OPEN/DRAFT**, com base `work/nfcore-closeout-20261119` (**não é `main`**) e HEAD técnico anterior `d4d5f295d3ccbd42c6fc0b76726e5c53f832fb3a`. Portanto, **clicar Merge nesta PR atualmente NÃO integraria diretamente na `main`**. A integrabilidade da candidata na `main` ainda precisa ser reconciliada com sua árvore atual.

Critérios para sair de Draft e integrar, sem confundir com autorização de deploy:

- [x] Escopo de motor congelado: não promover as quatro candidatas nem editar código fiscal.
- [x] CI do HEAD técnico-fonte `d4d5f295d3ccbd42c6fc0b76726e5c53f832fb3a` = **SUCCESS**; Ruff, Mypy, Pytest, E2E, runtime, segurança, backup/restore e ready.
- [x] Matriz e dossiê distinguem certificação interna de curadoria legal pendente.
- [x] Backlog jurídico específico criado para PR posterior, sem bloquear os gates internos do motor.
- [x] **CI do HEAD #592 `c083595b57a6222bbd8fc34f66d3e6fedf3b9364` — [#45273717614](https://github.com/faabio3131/nf-core-v001/actions/runs/45273717614), SUCCESS em 23/11/2026.** Este certificado é do HEAD **anterior à reconciliação multi-parent**; a candidata final precisa passar uma única CI no próprio SHA. Não herdar o certificado da #592.
- [ ] **Destino `main`**: reconciliar/retarget ou executar integração controlada conforme branches vigentes e verificar CI integrada no destino; PR atual tem base em branch de trabalho.
- [ ] Aplicar gate humano de merge/release conforme as regras do projeto; **nenhum merge em main foi realizado nem solicitado neste fechamento**.

**Veredito técnico**: `READY_FOR_TECHNICAL_REVIEW` sob verificação do HEAD documental e do fluxo de integração; **não** `PRODUCTION_APPROVED`, **não** `GO_LIVE`, **não** `27_UF_LEGAL_CERTIFIED`.

## 5. Reconciliação HEAD #592 → PR única `main` (23/11/2026)

**FATOS DE GRAFO:** `main@549ab3c` é ancestral do HEAD #592 com 1293 commits de avanço; `production@a5989e5` também é ancestral, com 1329 commits de avanço; `work/nfcore-closeout-20261119@39e64ea` é ancestral, 163 commits atrás. `#498@4cbbe7c3`, `#560@96fdfbed` e `#563@1da651e2` são ancestrais. `#468/#556@5cb2f4e9` divergem por 3 commits; `#591@30b9d1e9` diverge por 2 commits. A candidata tem os três HEADs como pais diretos, preservando todo o DAG, sem reescrever SHA. Consultar [auditoria de perda zero](audit/NFCORE_7PRS_ZERO_LOSS_CANDIDATE_20261123.md).

**PRESERVAÇÃO:** nenhum arquivo que exista nas sete PRs, `main` ou `production` está ausente no snapshot #592. Os 149 caminhos de 59 tarefas constam na candidata. Os controles de A1 e da identidade DPS já estavam no código de #592, mas seus dois testes específicos foram adicionados no fechamento. O diff da candidata versus #592 deve conter apenas esses dois testes e documentação de auditoria/ledger. **Nenhuma regra, permissão, importador, flag, migration ou runtime foi alterado.**

**GATES SEPARADOS:** `ENGINEERING_BUILD_CANDIDATE` só pode ser promovido a `CERTIFIED_INTERNAL_ON_CONSOLIDATED_HEAD` se a CI única do novo SHA terminar SUCCESS e a prova dos 149 caminhos e ancestralidade permanecer válida. `INTEGRATED_MAIN` só depois de merge autorizado + CI pós-merge. `PRODUCTION_APPROVED=NO` até provas operacionais e Go/No-Go. `T10_RELEASED=NO` até integração à `main` e fechamento técnico formal T01–T09.

**SE/AP/PA/RR:** `BLOCK_ICMS_BENEFIT_CALCULATION_AND_FISCAL_IMPORT`, `legal_benefit_certified=false`, 0/4 importáveis, pesquisa documental futura apartada. Não há nova pesquisa ou habilitação neste fechamento.
