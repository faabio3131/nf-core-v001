# T20 — Gerador de Dossiê Contábil PDF/Excel/XML

## CURRENT — remediação da auditoria independente R1 (26/11/2026)

**Estado:** IMPLEMENTED_NOT_CERTIFIED / R1_REPROVADO / R2_REQUIRED. PR #628 Draft, issue #626 aberta. Base main `188241b491e5e9712dc3214130c86bc8e8b9587d`; production `a5989e523c871c288bc2388c9508c1738082bb9a`. SHA auditado R1 `eb913f9988bc3c58d23c7a5dd7ef1a9b6cc8a91e`, árvore `3c974277ab83195bd042ed7eb2f974280021eff9`, CI #45833423112 SUCCESS (44/44, 7254 Python, 1 skip fora T20, 88 E2E), governança #45833423194 SUCCESS. Parecer R1 REPROVADO: 0 P0, 1 P1, 3 P2, 4 P3. [Parecer original](https://drive.google.com/file/d/1eN7nwb0qNfpPoesdoEHHbP0vsBmK0Hef/view).

### Current → Target e mapa de impacto

- P1-01: `application/accounting_dossier.py` usa a data local atual na mesma autoridade T17 (`verify_recovery_bundle`), não repete regras de prescrição/SELIC. Impede finalizar transação quando muda o dia durante o processamento. Regressões de corte próximo dia, próximo mês e após prazo quinquenal, serviço e HTTP 409, sem registros de dossiê.
- P2-01: `archive/accounting_dossier.py` quebra palavras por WORD, traduz rótulos principais, usa ARGB opaco, centavos numéricos formato 0 e texto formato @/quotePrefix, abas vazias humanas, tabela de evidências e alturas de linhas. JSON mantém chaves e valores canônicos. `pypdf` apenas em dev para regressão de extração de texto PDF. Evidência prévia: 12 casos isolados de formato passaram no renderer intermediário 3e56dd94; nova renderização/CI exigidas no HEAD final.
- P2-02: `tests/test_t20_accounting_dossier.py` e Playwright: COFINS, corrida simultânea, 4 eixos RLS e autorização cross-tenant/cross-unit, corrupção de parte/índice (fault injection), órfão T19, revogação durante render/rollback, CLI subprocess PG/MFA/destino, HTTP real com MFA e runtime flags. Runtime staging/production testam composição em schema PG isolado com adaptação explícita **somente no teste** do probe preexistente que referencia public.*; não equivalem à certificação do schema real de produção. Browser transport ainda é simulado, os formatos reais e HTTP PG são validados separadamente.
- P2-03: única instância de serviço no runtime determina disponibilidade informativa no bootstrap; UI não autoriza operações. Mensagens T20 em pt-BR, valor em BRL sem conversão float (BigInt), cancelamento MFA e 409/503 explícitos. Backend mantém verificação própria por operação.
- P3-01: CLI pré-valida symlink quebrado e diretório inexistente; publicação atômica sem overwrite preservada. Corrida de filesystem após a pré-validação pode falhar após commit documental; replay idempotente mantém recuperabilidade, sem alegar atomicidade DB+filesystem.
- P3-02: oportunidade documental `nfcore.accounting-dossier/v1` é somente vínculo FK, **não somável como oportunidade econômica**. T21 e qualquer agregador futuro devem excluir esse schema/benefit_id nulo antes de totalizar; adicionar prova antes de T21. Não mudar T01 nem apagar registros.
- P3-03: soma dos bytes lidos no verificador ZIP; parecer identifica XMLs T15/T16 como contexto mensal de recomputação e não prova direta de todo achado. Minimização futura condicionada à recomputação verificável.
- P3-04: seleção malformada 400 e sessão revogada/expirada 401, mensagens PT-BR. Lock global não redesenhado; #625 obrigatória antes de T21/Portal/produção.

**Gates:** revisar diff, Ruff/Mypy/PG/Pytest/E2E/CI integral, governança, QA visual independente e R2 com zero P0/P1/P2 no SHA exato; somente então T2 efetiva e solicitar autorização de merge; CI pós-merge e documentação antes de T21. Nenhuma migration/workflow novo, nenhuma segunda autoridade fiscal, nenhum efeito real. Master XLSX e #625/#613/#616 preservados. O teste local não substitui a CI; nenhuma certificação de produção.

## HISTÓRICO — implementação candidata inicial (26/11/2026)

Base `188241b491e5e9712dc3214130c86bc8e8b9587d`; #627 integrada, CI #45751148265 e governança #45751148291 SUCCESS; #622/#623 fechadas. Autorização expressa de implementação do proprietário; issue #626, branch `feat/nfcore-economy-t20-accounting-dossier`. Sem autorização de merge, deploy ou produção.

### Escopo técnico e aceite

- Dossiê por achado potencial T17 em competência encerrada, fontes atuais verificadas no corte registrado, ICMS/PIS/Cofins conforme modalidade e evidências existentes. T13 não constitui aprovação de achado de recuperação. Dossiê de benefício/comparação sem XML e assinatura digital automática não foram incluídos neste recorte.
- PDF com identificação, cálculo, base legal, histórico, parecer preparatório e campos de revisão/assinatura; XLSX com centavos exatos (inteiros maiores que 15 dígitos como texto) e texto não executável; XMLs originais, evidências, JSONs e manifesto SHA-256 em ZIP único. Provas abrangem a competência selecionada no mesmo escopo.
- Reuso T17/T16/T15 via `verify_recovery_bundle`, T18/T19 para reconciliação histórica; não há novo cálculo ou ledger. Arquivo imutável em partes T01, oportunidade documental vinculada à fonte e dossiê existente; replay por evidência/ator e nova versão quando muda a base. Sem migration.
- Serviço `AccountingDossierService`; endpoints de candidatos e exportação no router cognitivo existente, mesma autenticação/CSRF/RBAC e MFA recente para contador designado. Feature flag `NFCORE_T20_DOSSIER_ENABLED=true`, `NFCORE_ECONOMY_ENABLED=true`, router cognitivo ativo, MFA canônica, apenas runtime não produtivo e escopo homologation. CLI `scripts/nfcore_accounting_dossier.py` usa as mesmas autoridades e não sobrescreve arquivos. Ação pontual na tela Reforma Tributária; T21 e exposição de operações T19 não antecipadas.
- Testes propostos: PDF/XLSX/ZIP reais, hashes, XML byte a byte, texto anti-fórmula, precisão, paths, corrupção, autorização, rollback, versões, PostgreSQL, rota binária e jornada de download Playwright com transporte simulado. Exigir CI integral, revisão independente, gate T2 efetivo, merge autorizado e CI pós-merge antes de fechar #626. CLI e composição runtime ainda exigem prova de integração na validação; nenhuma execução de produção autorizada.
- Riscos: limites explícitos de memória/arquivos e contenção herdada do lock canônico; #625 continua bloqueador antes de T21/Portal/produção. Ausência de XML, fonte inválida ou autoridade insuficiente bloqueia exportação. Sem homologação fiscal real, assinatura eletrônica ou reconhecimento contábil.

**Estado:** IMPLEMENTED_NOT_CERTIFIED. HEAD e CI devem ser registrados na PR e issue após publicação; não presumir aprovação. XLSX Master ainda não sincronizado; manter ordem v4.1 e #613/#616/#625.


## HISTÓRICO — preparação de continuidade, 26/11/2026

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
