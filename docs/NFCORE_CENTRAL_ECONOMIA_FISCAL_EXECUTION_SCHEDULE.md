# Central de Economia Fiscal — execução T01–T22
Fonte: NFCore_Cronograma_Master_v3_Trilhas_Com_Trava.xlsx, Trilha 1, linhas 6–27.
A folha T23–T33, a Trilha 2 H01–H06 e a reformulação Enterprise não integram esta rodada. A futura oitava tela é a Central de Economia Fiscal; T21 exige interface funcional antes do redesign. Nenhuma tarefa é ENTREGUE sem DoD, data e evidência.

| ID | Entrega | Estado |
|---|---|---|
| T01 | Modelagem de dados, oportunidades, benefícios, ledger, dossiês, RLS | DoD interno aprovado — 44 PASS, 0 SKIP/FAIL (44678481529, 570170f3) |
| T02 | Contrato Core Cognitivo | ENTREGUE — DoD interno aprovado em 20/11/2026; 308 PASS, 0 SKIP/FAIL; 24 casos focais (44718504072, d53a2c62) |
| T03 | Sentinela Normativa e anistias/REFIS | ENTREGUE — DoD interno aprovado em 20/11/2026; 525 PASS, 0 SKIP/FAIL; 6 casos focais (44720120616, 6a0cf5be) |
| T04 | Motor Simples e Fator R | ENTREGUE — DoD interno aprovado em 20/11/2026; 114 casos focais PASS, 831 PASS na regressão, 0 FAIL, 1 SKIP externo RTC (44722887552, 8dc7c482) |
| T05 | Diagnóstico e otimizador Fator R | EM EXECUÇÃO — implementação determinística candidata; gates e integração pendentes |
| T06 | Classificador de receitas segregáveis | Bloqueado |
| T07 | Apuração/PGDAS segregada | Bloqueado |
| T08 | Catálogo federal | Bloqueado |
| T09 | Catálogo estadual 27 UFs | Bloqueado |
| T10 | Benefícios municipais e radar unificado | Bloqueado |
| T11 | Simulação Presumido/Real e IVA | Bloqueado |
| T12 | Comparador multi-regime | Bloqueado |
| T13 | Aprovação contábil auditável | Bloqueado; referência anterior preservada |
| T14 | Aplicação autorizada emissão | Bloqueado; protótipo de engenharia preservado |
| T15 | Auditoria histórica 60 meses | Bloqueado |
| T16 | Créditos não aproveitados | Bloqueado |
| T17 | Recuperação/prescrição/SELIC | Bloqueado |
| T18 | Ledger partidas dobradas | Bloqueado |
| T19 | Restituição/compensação | Bloqueado |
| T20 | Dossiê PDF/Excel/XML | Bloqueado |
| T21 | Interface Central vinculada a APIs reais | Bloqueado |
| T22 | E2E interno seis blocos | Bloqueado |

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
