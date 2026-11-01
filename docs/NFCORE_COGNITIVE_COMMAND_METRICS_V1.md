# NFCore → FM Command: métricas do core cognitivo (contrato v1)

**Estado:** implementado no NFCore (lado produto); **o conector do lado do Command ainda não existe**
(no Command o NFCore consta como `UNSUPPORTED`). Este documento é a especificação para o agente do Command.

## Padrão seguido
O mesmo já usado com o IRON: rota de leitura do produto, protegida por **token de control-plane
dedicado por produto**, `X-Correlation-Id` obrigatório, `Cache-Control: no-store`, envelope de fatos com
proveniência e frescor. O Command acessa por contrato HTTP (Integration Fabric); **nunca** lê o banco do NFCore.

## Endpoint
`GET https://api.nfcore.com.br/v1/command/cognitive/metrics`

| Item | Valor |
|---|---|
| Autenticação | `Authorization: Bearer <token>`; o token é o segredo `NFCORE_COMMAND_CONTROL_PLANE_TOKEN` (≥ 32 caracteres), injetado no NFCore pelo secret store e referenciado no Command por *secret-by-reference* (`env:`), nunca em código |
| Cabeçalho obrigatório | `X-Correlation-Id` (≤ 128) |
| Erros | 503 sem token configurado/fraco · 401 token inválido · 400 sem correlação · 429 acima de 60/min |
| Cache | `no-store` |

## Envelope
`schemaVersion: nfcore.cognitive.metrics/v1`, `mappingVersion: "1"`, `productId: nfcore`, `source: nfcore.cognitive`,
`correlationId`, `observedAt`, `freshness {scope: process, semantics: monotonic_counters_since}`,
`provenance`, `aiEnabled`, `facts`.

`facts`: `since`, `lastObservedAt`, `requests {total, byStatus, byCapability, degradedByReason}`,
`model {calls, inputTokens, outputTokens, costReportedCalls, costMicroBrl}`, `latencyMs {sum, count, bucketsLe}`,
`tenants {<tenantId>: {requests, modelCalls, degraded}}` (limitado a 500; excedente em `_overflow`).

## Semântica (importante para o conector)
- Contadores **monotônicos desde `since`** (início do processo). Reinício = `since` novo: o Command trata como
  reset de contador, não como queda para zero.
- **Ausência não é zero:** `costMicroBrl` é `null` enquanto nenhuma chamada reportou custo (`costReportedCalls = 0`).
  `lastObservedAt = null` significa que nada foi observado.
- Somente contagens. **Nunca** prompt, resposta, evidência, dado fiscal ou pessoal.
- Fonte `aiEnabled=false`: o core responde só com regras/catálogos; `model.calls` permanece 0 e isso é um fato válido.

## O que o Command precisa fazer
1. Registrar a source `nfcore` no Source Registry com `secretRef` do token (nunca o valor).
2. Implementar o connector de pull deste endpoint no Connector Runtime (timeout, retry classificado, idempotência por `correlationId`, checkpoint por `since`).
3. Mapear para fatos canônicos (`nfcore.cognitive.requests_total`, `...degraded_total`, `...model_calls_total`,
   `...model_cost_micro_brl_total`, `...latency_ms`), preservando proveniência/frescor.
4. Fornecer o mesmo valor do token ao NFCore (`NFCORE_COMMAND_CONTROL_PLANE_TOKEN`) pelo secret store.
