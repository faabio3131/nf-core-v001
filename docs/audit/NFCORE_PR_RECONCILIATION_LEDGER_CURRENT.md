# NFCore — reconciliação em execução, 16/11/2026

O proprietário autorizou nesta conversa reconciliar o trabalho existente, concluir pendências das PRs e atualizar a aplicação web. Essa autorização cobre a integração e o deploy após validação. Emissão oficial e operações destrutivas de dados exigem decisão específica. A auditoria recebida é diagnóstico de entrada, com decisões técnicas a validar.

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
