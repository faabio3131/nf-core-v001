> **T09 — FECHAMENTO DO RECEBIMENTO 22/11/2026 (CURRENT DOCUMENTAL, VALIDAR GITHUB):** o proprietário informou **TERMINEI, só tenho esses**. Foram identificados 50 arquivos de cinco lotes, 50/50 hashes verificados, 22 UFs no novo lote; pacote consolidado 59 entradas SHA-256 `584a0cd1458619b7033d39e95a7ee4cbe31558cba90cf0ee1cdab00e1f4cd547` (original ZIP fora do Git). Veja `docs/NFCORE_T09_COLETA_ENCERRADA_20261122.md` e `docs/NFCORE_T09_RECEBIMENTO_FINAL_50_DOCUMENTOS_20261122.json`. Isso **não** conclui a T09: 0/27 curadorias aceitas/importadas, INT-03/04/05/06/08/09 pendentes, T10 bloqueada, sem merge/deploy. A CI 6/6 verde referia-se a `8155a7de268fb3d37d5a07c07de7a13eb244f004` antes deste commit, novo HEAD requer CI própria. Priorizar trabalho interno sem requisitar novos documentos ao proprietário.

# FM NFCore V1 — T09 — checkpoint de pesquisa normativa (22/11/2026)

> **Documento de continuidade canônico para o pacote de pesquisa de 22/11/2026.** Não substitui código, testes ou CI reais. Último HEAD de entrada confirmado: `c6008bb7bb0e3c2ec5e52c693f2384e6969a5fc4`; PR [#592](https://github.com/faabio3131/nf-core-v001/pull/592) OPEN/DRAFT, base `work/nfcore-closeout-20261119`, `main` `549ab3c005d7183ff6c7940236414412ea004b9d` não mergeada. CI integral [#44986673875](https://github.com/faabio3131/nf-core-v001/actions/runs/44986673875) SUCCESS e outros cinco workflows SUCCESS **somente nesse HEAD**; novo commit exige CI própria.

## Pacote efetivamente conferido

`NFCORE_T09_PESQUISA_NORMATIVA_PARCIAL_20261122.zip` recebido na conversa, SHA-256 real `001f7e85c84e35914931218a8b5c4d492cd65d7332e847c3f36167d66e5cc12b`, 9.087.055 bytes, 64 entradas, estrutura ZIP validada. Manifesto interno: 29 registros, 29/29 SHA-256 e comprimentos validados sobre bytes arquivados no ZIP, zero divergência e zero nomes repetidos. **O ZIP binário NÃO foi persistido neste repositório**: para recuperar originais, conservar o arquivo em armazenamento governado e confirmar SHA. O registro da sua existência e do hash não é prova de arquivamento remoto.

- 27 dossiês **preliminares** e 27 linhas de regras de **pesquisa**, não políticas executáveis.
- 58 casos jurídicos de teste **propostos** (58 IDs únicos; todos `executed=false`), não 58 testes aprovados. Os 34 testes reais adicionados em commits anteriores não devem ser somados ou substituídos por esses designs.
- 29 capturas incluem **CAPTCHA rejeitado** (RJ SSER 362), **base sem anexo** (RN), **versão histórica superada** (SE), notícia (AM), resumo de ADI anterior ao julgamento (PA), 4 prints do IOERJ, atos de projeto distinto (RR) e um decreto geral fora da hipótese industrial (RO). Integridade de hash **não comprova vigência, pertinência ou publicação oficial**.
- 22 itens da fila histórica têm conteúdo localizado ou cotejado, não significam 22 originais oficiais autenticados. A contagem de 29 capturas do ZIP é distinta e não deve ser somada à de 22 documentos.
- 0/27 candidatas legalmente aceitas, 0/27 importações autorizadas, 0 homologações reais; nenhum parecer profissional assinado e nenhuma revisão **independente** registrada na PR. O documento `07_REVISAO_CONTRADITORIA.md` do pacote é **autorrevisão**, não aprovação por outro agente.

## Vínculos jurídicos adicionais como evidências de pesquisa, ainda não certificados por candidata

| UF | Achado | Bloqueio residual |
|---|---|---|
| TO | Certificados CONFAZ 11/2018 e 5/2020 foram localizados; Lei 3.577/2019 indicada como reinstituição | Comprovar anexo/planilha do ato e modalidade do PROINDÚSTRIA |
| MG | Convênio ICMS 136/1997 e alteração/prorrogação 21/2026 identificados | Confirmar prorrogação posterior 131/2026, internalização estadual e competência |
| MT | Convênio 79/2025 e Decreto 1.802/2025 vinculados ao Anexo V art. 31-A | Confirmar texto estadual integral, ST/DIFAL, prazos e alcance material |
| RR | Convênio 100/1997 com prorrogação federal até 2027 | Falta prova do ato **estadual** de 2026 para art. 1 LXVII; não usar Decreto 6.147-E/2004 como sinônimo |
| SP | Art.41 do Anexo III (crédito outorgado) e art.52 do Anexo II (redução de base) distintos | Reconciliar opções, exceções, vigência e depósito específico, sem cumular regimes |
| AC | Indicação de prazos 2032 versus 2035 em referências distintas | Distinguir natureza do benefício, lei, outorga e duração individual |
| RN | Crédito presumido do pescado alterado em 20/03/2025 para 64% do imposto | Reconciliar competência intramensal, percentuais históricos e opção |
| PA | Risco STF ADI 3779 já documentado | Acórdão completo, efeitos e reinstituição compatível |

Fontes candidatas explícitas: [LC160](https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp160.htm), [CONFAZ 79/2025](https://www.confaz.fazenda.gov.br/legislacao/convenios/2025/CV079_25), [CONFAZ 136/1997](https://www.confaz.fazenda.gov.br/legislacao/convenios/1997/CV136_97), [certificado TO 11/2018](https://www.confaz.fazenda.gov.br/legislacao/certificado-registro-deposito-cv-icms-190-17-1/tocantins/2018/certificado-de-registro-e-deposito-11-2018-1.pdf). A identificação de um certificado **não comprova automaticamente** que a candidata específica está coberta: verificar planilha e ato estadual.

## Fontes de verdade e arquivos da continuidade

1. Código, branch e CI **CURRENT** no GitHub, não este checkpoint.
2. Catálogo draft: `NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json`; nunca preencher `source_sha256`, `approved_for_eligibility` ou `import_authorized` só porque existe uma captura local.
3. Fila canônica 27 itens: `NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json`.
4. Dossiês estruturados existentes: `NFCORE_T09_DOSSIE_RECONCILIATION_V1.json`.
5. Novo inventário de pendências: `NFCORE_T09_RESEARCH_RESIDUAL_27UFS_20261122.md`.
6. Novo manifesto de hashes e classificações: `NFCORE_T09_RESEARCH_PACKAGE_MANIFEST_20261122.json`.
7. Cronograma mestre: `NFCORE_CENTRAL_ECONOMIA_FISCAL_EXECUTION_SCHEDULE.md`. T10 **BLOQUEADA** até saída de T09.

## Gates obrigatórios

INT-01 arquivar originais e proveniência; INT-02 completar documentação por benefício; INT-03 resolver alterações/revogações/competência; INT-04 detalhar operação/NCM/CNAE/CFOP/regime/ST/DIFAL; INT-05 confirmar rota CONFAZ/LC160 ou fundamento alternativo; INT-06 implementar e executar casos legais reais; INT-07 revalidar motor na CI do novo HEAD; INT-08 revisão independente adversarial; INT-09 aceite humano de cada curadoria; INT-10 CI cumulativa do commit final; INT-11 reconciliar documentação e governança. EXT-01–05 (parecer profissional, concessões individuais de contribuintes, certificados, homologação real e atos futuros) **não impedem a pesquisa e testes internos**, mas impedem aplicação fiscal real quando exigidos.

**Estados formais:** `T09-ENGINEERING-CERTIFIED` refere-se exclusivamente ao HEAD e gates técnicos comprovados; `T09-NORMATIVE-CURATION-CERTIFIED` exige aprovação por candidata; `T09-EXTERNAL-FISCAL-APPROVED` exige evidências externas reais. **Resultado desta rodada: RESEARCH-PARTIAL, sem merge/deploy/ativação fiscal.**
