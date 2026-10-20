# FM NFCORE V1 — Política comercial por utilização e benchmarking de mercado

Data: 2026-10-20. Estado: **política FM APROVADA; preços, franquias numéricas e estratégia de excedentes ainda NÃO APROVADOS**.

## 1. Decisão FM aprovada (2026-10-20)

**A FM Tecnologia não diferenciará planos de seus SaaS pela liberação de funcionalidades.** Os planos possuem paridade funcional e variam por cotas de utilização/solicitações. Para o NFCore, as duas dimensões comerciais prioritárias são:

- Quantidade de empresas/estabelecimentos emissores (CNPJ) habilitados.
- Quantidade de documentos fiscais (notas) processados no ciclo.

A regra vale como diretriz da FM para seus produtos, mas a definição de métricas e cotas específicas de cada SaaS deve permanecer no respectivo domínio, sem compartilhar estados, tenant ou assinaturas entre produtos. O tipo fiscal só poderá operar quando estiver tecnicamente implementado e homologado, independentemente do plano — **paridade de produto não elimina gates de segurança/fisco**.

A contratação não concede autonomia fiscal, RBAC ou credenciais. Preservar os contratos canônicos já existentes.

## 2. Benchmark oficial (consultado em 2026-10-20)

| Provedor | Estrutura publicada | Distorção em relação à decisão FM |
|---|---|---|
| Focus NFe | Solo R$94,90/mês, 1 CNPJ, 100 docs, R$0,11/doc extra; Start R$119,90/mês, 3 CNPJs, 100 docs/CNPJ, CNPJ extra R$39,90, documento extra R$0,11; Growth R$572/mês, CNPJs ilimitados, 4.000 docs, excedente a partir de R$0,125/documento. 30 dias de teste. | Forte benchmark híbrido CNPJ + documentos com API ampla. |
| Nuvem Fiscal | Grátis: 1.000 dfe-eventos/mês, CNPJs ilimitados; Fiscal I: 10.000 eventos/mês; Fiscal II: 100.000/mês conforme documentação de limites. Eventos abrangem emissão, cancelamento, inutilização e outros envios; conta documentos e não mero número de HTTP calls. | Concorrente permite CNPJs ilimitados; restringir CNPJs agressivamente tem risco competitivo. Consultar preços atuais antes de definição financeira. |
| NS Tecnologia | Starter até 4 mil emissões; Business até 27 mil; Corporate acima de 27 mil; Custom sob medida. Todos os DFes listados nas faixas. Valores sob cotação. | Exemplo relevante de paridade funcional e diferença sobretudo por volume. |
| eNotas | Basic R$137/mês e 60 notas, adicional R$0,77; Plus R$257 e 500 notas; Pro R$347 e 1.500; Business R$737 e 5.000; Enterprise R$1.147 e 10.000; valores conforme tabela do suporte atualizada 19/10/2026. | Apesar de escalar por volume, bloqueia recursos como API nos planos inferiores: **não replicar essa trava**. |
| TecnoSpeed PlugNotas | Uma API REST para diferentes DFes e integração ERP; consulta comercial personalizada. | Evidência de API unificada, sem valor público comparável confirmado. |

Fontes primárias:
- https://focusnfe.com.br/precos/
- https://focusnfe.com.br/precos/simulador-growth/
- https://dev.nuvemfiscal.com.br/docs/limites/
- https://nstecnologia.com.br/planos
- https://atendimento.enotas.com.br/hc/pt-br/articles/35773756727565-Quais-s%C3%A3o-os-planos-do-eNotas-e-como-gerenciar-minha-assinatura
- https://atendimento.enotas.com.br/hc/pt-br/articles/47587235681549-Como-acessar-a-documenta%C3%A7%C3%A3o-API-pelo-Emissor
- https://tecnospeed.com.br/plugdfe/plugnotas/

Preços de mercado são referências externas mutáveis, não preços FM. Ao reavaliar, verificar o site oficial atualizado. A Nuvem Fiscal detalha limites por **eventos fiscais**, que não são equivalentes a notas autorizadas — comparar as unidades com cuidado.

## 3. CURRENT técnico revisado no commit 476e97b79202e45369156144f9c4e10fe9dd478e

Autoridades existentes, **sem recriar**:
- `src/kordena_fiscal/product/pricing.py`: `PlanDefinition.periodic_quotas`, preços, cadência, trial, configuração versionada.
- `src/kordena_fiscal/product/billing.py`: `CommercialPlan`, `UsageQuota(metric_id, limit)`, `CommercialSubscription`, controle de usage/períodos.
- `src/kordena_fiscal/control_plane/pricing_admin.py`: publicação administrada pela FM.
- `src/kordena_fiscal/application/commercial_trial.py`: trial usa catálogo efetivamente publicado.
- `docs/checkpoints/NFV1_P02_T05_BILLING_PLANS_USAGE_2026-10-07.md`: superfícies de billing, plans, usage, sem autoridade de mutation no portal cliente.

**PENDENTE de prova end-to-end:** aplicação transacional das novas métricas de empresas ativas/documentos fiscalmente contabilizáveis em TODAS as operações reais, teste de concorrência, segregação por tenant/CNPJ, eventos de consumo, respostas de limite, relatório e reconciliação com billing. A existência de modelos de quota não comprova enforcement fiscal.

## 4. Target proposto, ainda sujeito à revisão de engenharia e comercial

Duas cotas nucleares e auditáveis por assinatura NFCore:
1. `nfcore_active_issuers` — quantidade de CNPJs emissores ativos vinculados ao tenant no ciclo. Desativação de CNPJ não pode permitir abuso por cadastro/remoção em massa; considerar também emissores distintos no período.
2. `nfcore_documents_per_period` — unidades documentais fiscalmente contabilizadas por janela comercial. Definir por política governada quando ocorre consumo: autorizado, transmitido, rejeitado, cancelado, inutilizado e situações assíncronas. Não contar retries/idempotência como novas notas, nem contabilizar lotes pelo número de requisições HTTP.

Por proteção antiabuso e FinOps, limites técnicos por segundo, concorrência, armazenamento, consultas de alto custo e custos de provider poderão existir transversalmente sem se tornarem bloqueios arbitrários de funcionalidades por plano.

Excedente: desenhar política **configurável FM** de alerta em 70/90/100%, upgrade, pacote extra pré-autorizado ou bloqueio seguro de nova emissão. Nada de cobrar excedente silenciosamente. Na falta de crédito não bloquear consulta de notas históricas, cancelamento/obrigações legais ou acesso à auditoria; estabelecer comportamento fiscal fail-closed e recuperação.

Limites e preços definitivos, trial_days, CNPJ adicional, custo por documento, política por tipo NF-e/NFC-e/NFS-e, prazos e descontos **a decidir** após FinOps e aprovação da FM.

## 5. Matriz de aceitação para construção

- Mesmas capacidades técnicas e RBAC por plano, conforme produto realmente suportado.
- Limites definidos por catálogo FM versionado; sem números/prices hardcoded.
- Checagem no backend, identidade de tenant/unidade canônica, emissão idempotente, lock/reserva transacional e reconciliação contra documentos efetivamente processados.
- Registro independente de CNPJ ativo e documentos por período com histórico de ajustes, charge/reversal e audit trail.
- Atomicidade entre contador e admissão de novas emissões sob múltiplos workers; concorrência em PostgreSQL e reinício não devem furar teto.
- Painel do cliente com consumo, franquia, saldo, alertas e instrução de upgrade; FM Command com editor governado e visão consolidada por produto/tenant.
- Testes com múltiplos CNPJs, concorrência, cancelamento, falha de provider, retries, tenant spoofing, upgrade/downgrade, períodos e rate limit.
- Homologação externa e provas de produção continuam fase distinta da construção. Nenhuma publicação real de preço ou habilitação fiscal por este documento.

## 6. Próxima decisão humana

Definir os tetos iniciais por faixa, os valores comerciais e a política de excedentes. Sem isso, criar planos de produção seria inventar condições comerciais. Construção de enforcement pode prosseguir com fixtures sintéticos e gates internos.
