# FM NFCORE V1 — Decisão comercial: planos, trial e identidade técnica

**Data da decisão:** 2026-11-01  
**Autoridade:** proprietário do produto  
**Estado:** DECISÃO DE PRODUTO APROVADA; configuração de catálogo, implementação e ativação operacional ainda exigem verificação e gates próprios.  
**Escopo:** NFCore V1, sem alterações em produção, sem ativação de cobrança ou emissão fiscal.

## 1. Planos comerciais aprovados

| Plano | Mensalidade BRL | CNPJs incluídos | Documentos fiscais/mês |
| --- | ---: | ---: | ---: |
| Essencial | R$ 179,00 | 5 | 1.000 |
| Crescimento | R$ 299,00 | 15 | 3.500 |
| Escala | R$ 499,00 | 50 | 7.500 |

Os valores acima são **preços de produto aprovados**, não evidência de catálogo publicado, checkout configurado ou autorização de venda. Excedentes, periodicidade alternativa, tributos, promoções e regras detalhadas de upgrade/downgrade não foram aprovados nesta decisão.

## 2. Trial gratuito aprovado

- **Prazo máximo:** 30 dias corridos desde a ativação governada do trial.
- **Franquia:** até **100 documentos fiscais** no período.
- **IA:** até **750.000 tokens de entrada** e **210.000 tokens de saída** no período (franquia aceita na conversa; medição por usage canônico).
- **Encerramento/bloqueio do consumo correspondente:** primeiro limite atingido entre prazo e franquias aplicáveis; quando uma quota se esgotar, bloquear a capacidade medida correspondente sem permitir estouro, respeitando a política de encerramento do trial e continuidade de acesso a dados já existentes.
- **Emissão fiscal real:** não autorizada pela concessão do trial. Simulação e homologação são diferentes de autorização oficial; habilitação por documento, operação, jurisdição e ambiente exige gates próprios.
- **Simulação interna:** pode ser disponibilizada sob rate limiting, antiabuso e isolamento de tenant, sem ser contabilizada como emissão real; consumo de infraestrutura/IA continua contabilizado conforme a capacidade utilizada.
- **Homologação oficial:** só fica disponível após validação do adapter/célula e das condições oficiais; não equivale a autorização produtiva.

**Pendências de detalhamento:** regra exata de contagem de documentos (tentativa x documento processado, cancelamentos, famílias fiscais), política de excedente, transição ao plano pago, reset/reconciliação de tokens, identificação de trial duplicado e condições comerciais/legais. Não presumir valores ou estados não definidos.

## 3. Modelo econômico e limites da estimativa

O **motor fiscal próprio** é o caminho principal do NFCore. Não pressupor API fiscal comercial paga nem taxa de R$ 0,20/documento para calcular o trial. Custo real inclui consumo incremental da Contabo, persistência, armazenamento, certificação quando aplicável, suporte e IA. As simulações anteriores de custos e roteamento de modelos **não são preços reais certificados ou unit economics de produção**. Medir uso e custo antes de fixar orçamento unitário como fato.

## 4. Identidade do produto e legado Kordena Fiscal

**Identidade oficial:** FM NFCORE V1 / NFCore.  
**Repositório GitHub atual identificado em 2026-11-01:** `faabio3131/nf-core-v001`, mesmo repository ID 1366374504 do nome histórico `faabio3131/kordena-fiscal-engine-v2`.

**Decisão:** eliminar referências de marca Kordena Fiscal **da identidade pública e dos novos contratos/documentos** do NFCore, sem apagar histórico ou renomear cegamente símbolos de execução já utilizados.

### Migração técnica exigida, separada desta decisão documental

1. Inventariar usos de `kordena_fiscal`, `Kordena Fiscal`, `kordena-fiscal` em módulos Python, imports, packaging/entrypoints, Docker, workflows, migrations, SQL, API, frontend, observabilidade, scripts, testes e integrações consumidoras.
2. Classificar cada ocorrência como **marca pública substituível**, **identificador técnico com consumidores**, **persistência/schema histórico imutável** ou **referência histórica/compatibilidade**.
3. Definir namespace Python/identificadores TARGET e estratégia de compatibilidade e deprecation antes da implementação; não criar segundo motor, API, runtime, autoridade fiscal nem alterar migrations históricas por estética.
4. Migrar por etapas com import compatibility quando necessário, testes de instalações fresh/upgrade, CLI, container, integração e regressão.
5. Só remover aliases históricos após provar que não há consumidores relevantes e que os gates estão verdes.

**Não realizado nesta decisão:** refactor/rename de pacotes, mudança de database/schema, deploy, migrations, alteração de DNS, ativação fiscal, billing real, alteração de produção ou merge em main.

## 5. Gates para implementar / publicar

- Auditar `main` atual, PRs e contratos canônicos de Pricing, Subscription, Usage Quota e Trial antes de editar runtime.
- Persistir estas configurações nas autoridades existentes, com valores versionados e configuração governada, sem hardcode no Site FM.
- Testar quotas concorrentes, expiração 30 dias, limites por tenant, antifraude, medição de input/output, trial→assinatura e comportamento fail-closed.
- Pricing publicado **não equivale** a compra habilitada; preservar Commercial Release Authority e aprovação humana.
- CI/Governança e E2E em HEAD exato; aprovação específica para publicação real, deploy, migração produtiva e efeitos externos.

**Próxima ação:** inventário e mapa de impacto do rename `kordena_fiscal`; em paralelo, localizar o catálogo/trial CURRENT e implementar os valores aprovados sem reintroduzir segunda autoridade.
