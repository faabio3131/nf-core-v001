# COG-02 — Franquias aprovadas e controle durável de IA

**Decisão humana:** 2026-11-01. **Estado:** implementação interna em PR #301, não certificada nem habilitada em staging/produção neste documento.

## Franquias aprovadas

| Plano | Escopo do período | Tokens entrada | Tokens saída |
| --- | --- | ---: | ---: |
| Trial gratuito | 30 dias corridos, sem renovação automática | 750.000 | 210.000 |
| Essencial | mensal, mesmo com pagamento trimestral/anual | 1.000.000 | 300.000 |
| Crescimento | mensal, mesmo com pagamento trimestral/anual | 3.000.000 | 900.000 |
| Escala | mensal, mesmo com pagamento trimestral/anual | 8.000.000 | 2.400.000 |

**Fonte da autorização do cliente:** `fm_commercial_subscriptions` (tenant, `plan_id`, status, período, `quotas_json`). Chaves canônicas em `periodic_quotas`: `cognitive.input_tokens` e `cognitive.output_tokens`. A publicação histórica do pricing e a assinatura contratada são autoridades comerciais; o mapa de franquias aprovado é apenas **teto de segurança**. Nenhuma ausência de configuração vira concessão implícita. A provisão do trial associa as quotas trial à assinatura sem alterar outros entitlements; a conversão autorizada do trial recupera o plano pago original pela publicação versionada, não por input do navegador.

## Persistência e execução

- Schema **19 aditivo**: `fm_cognitive_token_counters` (saldo reservado/contabilizado por tenant e janela) + `fm_cognitive_token_reservations` (idempotência e estado); nenhuma nova autoridade de plano, motor fiscal ou DB externo.
- Antes de cada chamada de modelo, reservar atomicamente no PostgreSQL um teto conservador para entrada e saída; qualquer erro, quota ausente, assinatura vencida, plano desconhecido ou consumo esgotado bloqueia **somente a chamada de IA**, mantendo aconselhamento determinístico. 
- Duplicidade da mesma request não executa novamente o modelo. Cada reserva contém somente identificadores técnicos, janela, token counts e timestamp; não armazena prompt, resposta, segredos ou certificado.
- Fallback de até dois provedores reserva orçamento para **duas tentativas**. Timeout/falha ou uso não confirmado retém o orçamento conservador, evitando estorno fictício. Resposta de provedor único com usage válido pode liquidar a reserva idempotentemente e liberar excedente não consumido.
- Janela mensal ancorada na data inicial do período contratado, com fechamento calendário (inclusive mês com dia 28/29/30/31). Trials fecham no mínimo entre expiração canônica e start + 30 dias, sem reset.
- O total de tokens representa a capacidade máxima reservada/medida; distinguir reservas pendentes de gasto efetivamente confirmado em relatórios futuros.

## Gates operacionais

- `NFCORE_COGNITIVE_ENABLED=true` habilita **somente a interface consultiva** por padrão.
- Modelos reais em staging/produção exigem adicionalmente `NFCORE_COGNITIVE_DURABLE_AI_ENABLED=true`, PostgreSQL schema19 certificado, assinatura canônica com quotas publicadas, auditoria durável e configuração de provedor no cofre. Sem qualquer dependência, **IA OFF**.
- Não configurar secrets, não aplicar schema19 em produção, não atualizar `production` nem a Contabo por esta PR.
- Migration em staging/prod deve passar por `scripts/ci/migration_guard.py` e autorização operacional separada; o deploy automático da Contabo não executa DDL. A mudança de versão exige migração governada **antes** da promoção do código.
- Homologação contábil de catálogos fiscais continua independente; IA nunca substitui Tax Rule Engine.

## Critérios de aceite técnicos

- Testes SQLite e PostgreSQL descartável com reserva concorrente, atualização sem overdraw, isolamento por tenant, dedupe/idempotência, uso incerto, status inválido, 30 dias e renovação mensal.
- Testes do adapter modelo comprovam: sem reserva sem modelo, sem chamada duplicada, timeout conserva reserva, settlement apenas seguro.
- Teste de composição confirma opt-in de produção com banco e auditoria; Ruff/Mypy/Pytest/frontend/E2E/containers/CI+Governança obrigatórios no SHA exato.
- Ao fechar: registrar na PR e no ledger SHA, CI/Gov, estado, migrations não aplicadas, blockers, promoção e testes pós-merge.

**Pendências de operação:** publicação governada das quotas na configuração comercial pagante, ativação de chaves Gemini/OpenAI via cofre, possível ajuste de sincronização trial→contrato após pagamento real, verificação operacional Contabo, revisão normativa de tabelas e Go/No-Go humano antes de produção.
