# NFCore V1 — Cronograma de execução: Universal ERP Integration Hub

**Decisão do proprietário: 25/11/2026.** [Issue #620](https://github.com/faabio3131/nf-core-v001/issues/620). Estado: **PROGRAMADO / NÃO INICIADO**. Escopo obrigatório da V1, não backlog V2. Este anexo integra o cronograma mestre e a trilha BUILD-ONLY sem substituir ou renumerar os 59 IDs históricos, BLD-00–08, T01–T33 ou H01–H06.

## 1. Ordem de execução e dependências

- Base documentada no momento da decisão: main `6b1f940bcad984a5800abcaa7c0104a58e169491`; T17 certificada, T18 em PR #619 Draft no HEAD então observado `17e368a2b6cdf525524930a2fe20350e9e9f0e56`. Não tocar no HEAD ativo; consultar o GitHub antes de retomar.
- Concluir T18–T22 na ordem existente. Após certificação T22 e integração deste anexo, iniciar ERP-01; um bloco interno por vez, cada predecessor certificado.
- ERP-15 é pré-requisito adicional da folha T23 (mantém T22 como predecessor) e do fechamento interno antes de H01. Preservar T23–T33 e H01–H06, com suas próprias travas. Nenhuma atividade de execução simultânea foi liberada por este registro.
- Datas e estimativas serão definidas após ERP-01, com base em inventário e dependências reais; não inventar prazo.

## 2. Arquitetura-alvo e invariantes

ERP / SaaS ⇄ adaptador configurável (manifesto e credenciais por instalação) ⇄ gateway, mapeamento, eventos/sincronização ⇄ contrato e modelo canônico NFCore ⇄ Core fiscal/tributário e intelligence ⇄ autoridades fiscais. O fluxo de retorno é mediado por capacidades e contratos do fornecedor, sem efeito fiscal automático.

Reutilizar Product Contract Packs, FM Fiscal Bridge, `integrations/contract.py`, contratos e ports Bling, `connectors/erp_pme.py`, control plane, escopo, vault, TaxRuleEngine, API/Portal/Worker, PostgreSQL/RLS, inbox/outbox, idempotência e auditoria. ERP-01 confirma a aderência antes da implementação; não atribuir capacidades a ativos só pela existência de arquivo. Proibido motor tributário duplicado, banco/fila/roteador paralelo, dependência de formato de fornecedor no Core, mapping com scripts arbitrários ou autorização inferida de credencial. O adaptador não decide imposto, competência, jurisdição, elegibilidade ou crédito.

Configuração é declarativa, tipada, versionada, revisada e pinada por instalação. Extensão por port/adaptador específico onde necessário; não criar abstração universal insegura que aceite URL/comando/código arbitrário. Contrato externo, capacidades, efeitos e fontes devem ser explícitos. O Core fiscal continua autoridade única; a IA atua sob as regras existentes de governança.

## 3. Cronograma obrigatório

Todos os itens abaixo têm estado **PENDENTE**, sem data de entrega ou evidência de implementação. O DoD específico complementa o gate comum.

| ID | Depende de | Entrega | Critério de aceite específico | Estado |
|---|---|---|---|---|
| ERP-01 | T22 | Auditoria arquitetural, inventário e ADR | Mapear código, contratos, interfaces, escopos, fluxos e gaps por fornecedor/versão; aprovar CURRENT → TARGET, fronteiras, decisão de reuse, threat model e matriz de capacidades. Registrar evidência de cada ativo e critérios de seleção de produtos. | PENDENTE |
| ERP-02 | ERP-01 | Contrato universal e modelo canônico | Schemas versionados de instalação, empresa, filial, parceiros, produtos, venda, compra, documento fiscal, ajustes, pagamentos, apuração e resultados. APIs e eventos com contratos, identidade, origem, versão, competência, idempotência e validação; round-trip de fixtures e compatibilidade comprovados. | PENDENTE |
| ERP-03 | ERP-02 | Registry e runtime declarativo de conectores | Manifesto de provider/produto/versão, capacidades, operações, protocolos, schemas e referência de configuração. Resolução explícita, versionamento, validação e instalação isolada. Provar novo ERP sintético por configuração sem alterar Core; sem executar código fornecido em configuração. | PENDENTE |
| ERP-04 | ERP-03 | Gateway de autenticação e credenciais | Ports reutilizáveis OAuth2/API key/JWT/mTLS conforme contratos; scopes, consentimento/rotação/revogação, vault existente, SSRF allowlist, RBAC/MFA/CSRF/S2S, isolamento de host/tenant/unidade/ambiente/instalação; falhas e ataques testados em sandbox. | PENDENTE |
| ERP-05 | ERP-04 | Motor de mapeamento e transformação | Campos/códigos/decimal/data/moeda e normalização determinística, validação sem inferência fiscal, proveniência e versão de mapeamento, revisão de incompletos. Fixtures de ERPs heterogêneos com ausência de campos, incompatibilidade, drift e round-trip sem perda silenciosa. | PENDENTE |
| ERP-06 | ERP-05 | Ingressos e sincronização bidirecional | API/webhook autenticados conforme contrato, REST/SOAP/GraphQL/arquivos quando aplicáveis, pull/push, paginação, cursor, rate limit, dedupe, inbox/outbox existentes, retries, DLQ, backfill, versionamento e conflitos. E2E de recuperação e não duplicidade, sem efeitos fiscais externos. | PENDENTE |
| ERP-07 | ERP-06 | SDK e sandbox de certificação | Templates, registro declarativo, transportes simulados, contract tests, fixtures versionadas, teste de compatibilidade, integração Postgres e jornadas de referência. Provar onboarding de ERP novo e atualização de versão sem mudança do TaxRuleEngine. | PENDENTE |
| ERP-08 | ERP-07 | Bling na arquitetura universal | Migrar/reutilizar o conector Bling, preservando contratos versionados, OAuth, HMAC, empresa, status, revisão, política fiscal, outbox e limites. Regressão integral do ciclo existente; mapear capacidades reais sem prometer importação XML quando não suportada. | PENDENTE |
| ERP-09 | ERP-08 | Tiny/Olist ERP | Reutilizar normalizador existente; adapter configurável de API, autenticação, eventos/polling conforme contrato, mapeamentos, sincronização e retorno disponíveis; testes de contrato/sandbox e isolamento. Identificar API/versão exata. | PENDENTE |
| ERP-10 | ERP-09 | Omie | Implementar adapter por contrato documentado, credenciais, mapeamento de fatos, integração bidirecional suportada e tratamento de falhas; fixtures, testes de contrato e E2E interno. | PENDENTE |
| ERP-11 | ERP-10 | Conta Azul | Implementar adapter por contrato documentado, OAuth/scopes quando aplicáveis, fatos de negócio, integração bidirecional suportada e recuperação; fixtures, testes de contrato e E2E interno. | PENDENTE |
| ERP-12 | ERP-11 | Odoo, TOTVS e SAP Business One | Selecionar edição/produto/versão/contrato com precisão; subdividir ERP-12 por fornecedor e certificar cada adapter no recorte conhecido. Não afirmar suporte a todas as versões. Lacuna de documentação bloqueia somente capacidade específica, com rastreabilidade e construção de infraestrutura restante. | PENDENTE |
| ERP-13 | ERP-12 | Central de integrações no Portal NFCore | Onboarding, instalação, conexão/credenciais por vault, configuração e revisão de mapeamentos, capacidades, sincronização, estado, fila, alertas e histórico/replay governado. UI PT-BR responsiva, sem tokens/payload sensível, controles reais de backend e Playwright. | PENDENTE |
| ERP-14 | ERP-13 | Segurança, resiliência e escala | Threat model atualizado, testes adversariais de identidade, SSRF, replay, idempotência, concorrência, limites/quotas e recuperação; carga reproduzível com SLO e critérios definidos no ERP-01; observabilidade, trilha LGPD e parecer Gemini sem P0/P1. | PENDENTE |
| ERP-15 | ERP-14 | Certificação integral e integração | E2E interno de jornadas fiscais e inteligência tributária pelo contrato canônico, matriz de capacidades por fornecedor, isolamento, nenhuma regressão fiscal, CI integral exata, auditoria independente e integração autorizada com CI pós-merge. Documentar gates externos não satisfeitos e liberar folha somente após evidência. | PENDENTE |

## 4. Gate de conclusão comum por tarefa

1. Confirmar CURRENT (SHA, branches, código, contratos e evidência), predecessor certificado e escopo. Abrir issue/PR própria, manter trilha de decisões e não repetir ativo existente.
2. Entregar implementação executável e documentação, não somente schema, interface vazia, diagrama ou simulação de sucesso. Testes de contratos públicos versionados e mocks apenas em teste/sandbox; produção não aceita fixture/credencial fictícia.
3. Validar unit/integration/PostgreSQL/RLS/adversarial/contract/Playwright conforme escopo, regressão integral, Ruff/Mypy/CI e governança no HEAD exato. CI verde não prova compatibilidade externa.
4. Parecer técnico independente Gemini, correção de P0/P1 e demais bloqueios efetivos, rastreio de refinamentos; autorização expressa para merge no SHA revisado; árvore integrada conferida; CI pós-merge e reconciliação documental.
5. Registrar status, data, SHA, PR, CI e parecer no anexo/issue/AGENTS. Não liberar sucessor sem gate. Não iniciar produção sem autorização independente.

## 5. Gates de construção e operação são distintos

| Estado | Evidência |
|---|---|
| INTERNAL_CONSTRUCTED | Código funcional configurável, contrato/sandbox e testes internos. |
| INTERNAL_CERTIFIED | DoD, CI exata, auditoria independente, merge autorizado e CI pós-merge. |
| READY_AWAITING_CONFIGURATION | Capacidade construída; instalação aguarda credenciais/configuração legítima. |
| EXTERNAL_CONTRACT_GAP | Fonte insuficiente de operação/versão; declarar limitação e construir restante possível. Não certificar compatibilidade específica não demonstrada. |
| EXTERNAL_CONNECTED | OAuth/API real, identidade/escopo verificados, autorização da instalação. |
| EXTERNAL_HOMOLOGATED | Jornada oficial/real comprovada no escopo de provider, produto, versão, instalação e capability; não inferir homologação fiscal de conexão ERP. |
| PRODUCTION_APPROVED | Autorização específica, segurança, readiness, rollback, operação e gates fiscais/comerciais aplicáveis. |

A falta de credenciais, clientes, aprovação de marketplace ou homologação não é justificativa para não construir/testar internamente. Dependência externa desconhecida deve ser delimitada à capacidade específica, não bloquear genericamente a entrega de arquitetura, runtime, adaptadores conhecidos ou certificação interna do recorte demonstrado. As evidências externas permanecem obrigatórias para ativar as capacidades correspondentes; nenhuma alegação universal de homologação ou cobertura.

## 6. Controle de evidência

Issue #620 acompanha a trilha. Cada linha da tabela terá seu próprio registro PR/SHA/CI/parecer/data antes de receber estado ENTREGUE. A planilha Master v3 é a fonte histórica T01–T33/H01–H06; a extensão ERP preserva IDs e acrescenta travas, sem promover estados de produção.

**Não autorizado por este documento:** início antecipado ERP, merge automático, deploy, mudança de produção, migração produtiva, credenciais, clientes, transmissão fiscal, ativação de provider ou reconhecimento de crédito.
