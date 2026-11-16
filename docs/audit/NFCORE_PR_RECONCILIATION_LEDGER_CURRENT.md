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
