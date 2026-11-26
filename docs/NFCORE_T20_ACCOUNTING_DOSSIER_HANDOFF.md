# T20 — Gerador de Dossiê Contábil PDF/Excel/XML

## CURRENT — preparação de continuidade, 26/11/2026

**Próxima tarefa: #626. Implementação NÃO INICIADA.** A T19 está integrada pela #624 em `75542dd18d7a1521a33017f80395e24285c39fe4` e certificada tecnicamente no escopo interno. [CI pós-merge #45746332104](https://github.com/faabio3131/nf-core-v001/actions/runs/45746332104) e governança #45746332101 SUCCESS. [Handoff completo T19](NFCORE_T19_RECOVERY_LIFECYCLE_HANDOFF.md).

A autorização do proprietário inclui o fechamento documental e a liberação da T20. **READY_TO_START / NOT_STARTED passa a valer após integração e CI/governança próprias da reconciliação documental T19**, com os SHAs/runs finais registrados na [issue #626](https://github.com/faabio3131/nf-core-v001/issues/626). A existência deste handoff não comprova implementação de gerador, exportação ou jornada de usuário.

## CURRENT → TARGET e fonte de escopo

CURRENT confirmado no Git: a T01 possui `EconomyStore.append_dossier`, com referência à oportunidade, versão, arquivo e digest SHA-256. T13/T15–T19 oferecem autoridades de aprovação, proveniência, análise, cálculo e ledger a inventariar. A existência dessas autoridades não comprova geração PDF/Excel/XML.

### TARGET e DoD literal recuperados

Fonte do proprietário: `NFCore_Cronograma_Master_v4_1_ERP_Universal.xlsx`, Master v4.1, aba `Trilha1_Construcao_Interna`, linha **25**, registro **T20** (entrega D25; DoD G25). SHA-256 original `bb02fbdf49058ce2b079350baeda1e838b1abacdb34435202a7b3067b4967cca`. Arquivo de 44.500 bytes, modificação registrada em 25/11/2026 às 17:29:05 UTC; localizado e lido em 26/11/2026 entre os arquivos persistentes do proprietário. O estado T18/T19 desse snapshot é histórico e deve ser reconciliado com GitHub; os critérios e a ordem permanecem preservados. A busca inicial no Drive não localizou a fonte; a recuperação posterior resolveu a lacuna do DoD antes de concluir este fechamento.

| Campo da fonte | Conteúdo literal |
|---|---|
| Fase | Fase 7 - Dossiê & UI Fiscal |
| Bloco | Dossiê & Validação Contábil |
| Tarefa / Entrega Obrigatória | Gerador de Dossiê para Validação Contábil (pacote PDF + Excel + XMLs de prova com base legal, memória de cálculo e parecer estruturado) |
| Pré-Req. | T19 |
| Ativo Reaproveitado | Core Cognitivo + Persistência |
| Critério de Aceite (DoD) | Exportação em 1 clique gera dossiê completo pronto para revisão e assinatura do contador sem edição manual. |
| Prazo (Dias) | 5 |

O prazo de cinco dias é uma estimativa histórica, não um compromisso de entrega nem uma nova data aprovada. Aplicar este DoD ao desenho da implementação; não reduzir o pacote a um formato nem confundir a prontidão para assinatura com assinatura/aprovação automática do contador. A integração global de telas da Central pertence à T21; a T20 precisa comprovar sua própria exportação exigida pelo DoD sem antecipar a exposição das operações T19 bloqueadas pela #625. Toda decisão de implementação, aceite técnico detalhado e teste deve ficar vinculada a esta fonte e às autoridades CURRENT.

## Retomada executável

1. Reconsultar GitHub: main/production, PRs, HEAD e CI; confirmar fechamento #622/#623 e estado READY_TO_START na #626.
2. Conferir o DoD literal acima contra a versão vigente, identificar dependências e registrar Current → Target, mapa de impacto, áreas protegidas, aceite e testes na PR da T20 antes de código.
3. Inventariar persistência de dossiês T01, leitores de evidência/versões/digests e exportadores existentes. Reutilizar o que for correto; não criar segunda regra fiscal, ledger, autenticação, tenant ou persistência canônica.
4. Construir somente a T20 aprovada, com isolamento e proveniência verificáveis. Não inferir crédito reconhecido ou validade fiscal real de material sandbox.
5. Testar o DoD literal, cenários negativos, integridade/formato e autorização aplicáveis; cumprir CI integral no HEAD exato, revisão independente, autorização específica do merge de implementação e certificação pós-merge. Atualizar cronograma e handoff com evidência.

## Dependências e fronteiras preservadas

- T19: certificado interno e fechamento documental governado acima. Não repetir fase certificada sem regressão comprovada.
- #625: cinco P3 de engenharia interna obrigatórios antes da T21/Portal/produção. A issue não bloqueia a T20 documental após T19 certificada; não antecipar exposição HTTP/Portal de operações T19 para contornar o gate.
- #613/#616 permanecem abertas; recuperar suas restrições ao definir consumidores dos resultados T16/T17.
- #593: curadoria/expansão territorial segue independente da construção; fonte não validada permanece indisponível para cálculo/aplicação no escopo correspondente.
- Ordem preservada: T20 → T21 → T22 → 18 etapas ERP → T23–T33 → H01–H06, com ERP-15 antes de T23/H01 e os 59 IDs históricos intactos. ERP não inicia por esta liberação.
- Production observada `a5989e523c871c288bc2388c9508c1738082bb9a`. Sem deploy, migração produtiva, credencial real, homologação fiscal externa, publicação comercial ou reconhecimento real de crédito nesta entrega.

## Evidência e próximos registros

A PR documental de `docs/nfcore-t19-postmerge-closeout` e a #626 registram a conclusão do gate documental, o commit integrado e as execuções próprias. A PR futura de implementação T20 registrará seu próprio HEAD, diff, CI, revisão e autorização; nenhuma certificação futura é herdada deste handoff.
