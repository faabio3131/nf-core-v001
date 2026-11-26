# T20 — Gerador de Dossiê Contábil PDF/Excel/XML

## CURRENT — preparação de continuidade, 26/11/2026

**Próxima tarefa: #626. Implementação NÃO INICIADA.** A T19 está integrada pela #624 em `75542dd18d7a1521a33017f80395e24285c39fe4` e certificada tecnicamente no escopo interno. [CI pós-merge #45746332104](https://github.com/faabio3131/nf-core-v001/actions/runs/45746332104) e governança #45746332101 SUCCESS. [Handoff completo T19](NFCORE_T19_RECOVERY_LIFECYCLE_HANDOFF.md).

A autorização do proprietário inclui o fechamento documental e a liberação da T20. **READY_TO_START / NOT_STARTED passa a valer após integração e CI/governança próprias da reconciliação documental T19**, com os SHAs/runs finais registrados na [issue #626](https://github.com/faabio3131/nf-core-v001/issues/626). A existência deste handoff não comprova implementação de gerador, exportação ou jornada de usuário.

## CURRENT → TARGET e fonte de escopo

CURRENT confirmado no Git: a T01 possui `EconomyStore.append_dossier`, com referência à oportunidade, versão, arquivo e digest SHA-256. T13/T15–T19 oferecem autoridades de aprovação, proveniência, análise, cálculo e ledger a inventariar. A existência dessas autoridades não comprova geração PDF/Excel/XML.

TARGET nomeado pelo proprietário e cronograma: **Gerador de Dossiê Contábil PDF/Excel/XML**. O cronograma Git reproduz apenas o título T20 e cita `NFCore_Cronograma_Master_v3_Trilhas_Com_Trava.xlsx`; o planejamento vigente registra Master v4.1. **Antes de congelar a implementação, recuperar a linha T20 e seu DoD literal na planilha vigente, registrar versão/local/evidência e confrontar com o CURRENT.** Não declarar requisitos inferidos como aprovados nem alterar escopo silenciosamente. A busca somente leitura em 26/11/2026 no workspace e no Google Drive conectado não localizou a planilha Master vigente; não há ID/URL verificado da fonte a registrar. Essa limitação é de recuperação do escopo literal, não desfaz a certificação T19 nem autoriza inventar requisitos.

## Retomada executável

1. Reconsultar GitHub: main/production, PRs, HEAD e CI; confirmar fechamento #622/#623 e estado READY_TO_START na #626.
2. Recuperar o DoD literal vigente, identificar dependências e registrar Current → Target, mapa de impacto, áreas protegidas, aceite e testes na PR da T20 antes de código.
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
