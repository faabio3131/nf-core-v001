# T11 — simulação de regimes da Central de Economia Fiscal

## Retomada em 24/11/2026

Base integrada da T10: main `8f48f5af241e02315800055477b8aeca1450b5b7`, PR #596. Branch da T11: `feat/nfcore-economy-t11-simulation`. O registro de execução da [#597](https://github.com/faabio3131/nf-core-v001/issues/597) concentra PR, HEAD, resultado da CI e pendências. Verificar ali a revisão mais recente antes de continuar.

## Contrato e recorte implementado

O Portal, na tela Reforma Tributária, consulta `POST /v1/portal/cognitive/economy/quarterly-simulation` com unidade, ambiente e primeiro dia do trimestre. O backend usa sessão, permissão audit.read, CSRF, cadastro de emitente e histórico de regime federal. O regime cadastrado é identificado à parte dos dois cenários hipotéticos. O acesso aos fatos usa o snapshot T01 revisado e mais recente no escopo do banco, com RLS e leitura repetível. Um histórico ambíguo ou ausente produz base insuficiente.

A versão cobre trimestres civis completos de 2026 para empresas ordinárias não financeiras com comércio e serviços gerais. Os fatos devem consolidar a pessoa jurídica e ter revisão contábil para o escopo autorizado. Os valores monetários usam centavos. O Presumido usa presunção ponderada por atividade, faixas ordinárias efetivas previamente reconciliadas com o acumulado anual e adicional do IRPJ. No primeiro trimestre a majoração da presunção só alcança o IRPJ. As demais receitas integralmente tributáveis entram nas bases indicadas. O Real parte do resultado contábil com adições, exclusões e compensações informadas separadamente para IRPJ e CSLL. O limite ordinário de compensação é verificado.

PIS/Cofins usa bases mensais ordinárias revisadas e créditos separados de cada tributo no cenário não cumulativo. IBS e CBS usam os itens computados da resposta oficial do Regime Regular, com digest, versão e lista de itens conferidos. Valores negativos representam saldo credor no período. Créditos informados devem incluir apenas valores aproveitáveis no mês simulado, sem repetir saldos. O operador deve conferir a ligação dos documentos ao mês, à empresa e à composição contábil antes da importação. São resultados consultivos por tributo, antes de retenções, antecipações, compensações gerais e efeitos de recolhimento da transição. A T12 tratará comparação anual e recomendação.

Períodos reduzidos, Lucro Real anual, instituições financeiras, percentuais especiais por atividade, receitas com tratamento diferenciado, outros anos e opção fiscal efetiva exigem tratamento próprio. O esquema da revisão explicita a hipótese aceita. O Portal não recebe bases, créditos ou alíquotas.

## Dados e reprodução

1. Em banco de homologação já provisionado, usar o importador operacional `scripts/nfcore_quarterly_simulation_import.py BUNDLE --tenant TENANT --unit UNIT`. O ambiente exige DATABASE_URL e configuração existente da Central. O bundle inclui tenant, unit, issuer_cnpj, version e facts. O comando valida competência, regime, documentos e escopo antes da gravação. A primeira versão é 1. Repetir exatamente uma importação devolve o mesmo digest. Correções exigem a próxima versão.
2. O exemplo sintético está em `tests/tax/fixtures/t11_reviewed_example.json`. A planilha XML de referência em `tests/tax/fixtures/t11_quarter_reference.xml` abre no Excel/LibreOffice e contém fórmulas e resultados em centavos. É uma referência interna de engenharia. Os valores do exemplo de presunção reproduzem a questão 14 da Receita. A fixture RTC gravada na T07 está em `tests/tax/fixtures/rfb/rr_calc.json`. O caso positivo usa o item calculado, o teste negativo rejeita a resposta que também contém item inconsistente.
3. Executar `pytest tests/tax/test_quarterly_simulation.py tests/tax/test_rfb_live_fixtures.py tests/cognitive/test_state_benefits_api.py tests/persistence/test_economy_schema_postgres.py` com PostgreSQL de teste. O cenário Playwright “quarterly simulator” exercita o Portal e a apresentação de dados insuficientes. Ruff, Mypy, verificações de frontend e CI cumulativa são gates de engenharia.
4. Após aprovação da candidata, integrar somente com autorização e registrar CI da main antes de liberar T12. Curadoria territorial e uso com contabilidade real seguem o cronograma próprio.

## Fontes fiscais de referência

- Receita Federal, redução de benefícios, questões 11–14 e tratamento da receita por atividade: https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/perguntas-e-respostas/beneficios-fiscais/perguntas-e-respostas-reducao-de-beneficios-v2.pdf
- Orientações da RFB sobre IRPJ e CSLL: https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/tributos/IRPJ e https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/tributos/CSLL
- RFB, perguntas e respostas da pessoa jurídica, PIS/Cofins: https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/perguntas-e-respostas/ecf/perguntas-e-respostas-da-pessoa-juridica-2022
- Adapter oficial RTC, versão fixada e proveniência dos ensaios: [documentação do repositório](rtc/RTC_RFB_OFFICIAL_CALCULATORS.md).
