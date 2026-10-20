# FM NFCORE V1 — Política comercial por utilização e benchmarking de mercado

Data: 2026-10-20. Estado: **política FM APROVADA; preço do NFCore Essencial R$ 149,00/mês APROVADO; demais preços, franquias numéricas e estratégia de excedentes ainda NÃO APROVADOS**.

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

Preço do plano NFCore Essencial: **R$ 149,00/mês — DECISÃO APROVADA DA FM**. Quantidades de CNPJ/notas incluídas (proposta anterior: 1 CNPJ e 500 documentos/mês), preços dos demais planos, excedentes, trial_days, CNPJ adicional, custo por documento, política por tipo NF-e/NFC-e/NFS-e, prazos e descontos ainda **pendentes de validação/aprovação específica**. A decisão do preço isoladamente **não publica** uma configuração de cobrança.

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

Definir os tetos iniciais por faixa, os valores dos outros planos e a política de excedentes. O **valor de R$ 149,00/mês do Essencial já está aprovado**, mas sua franquia quantitativa ainda será validada com FinOps. Construção de enforcement pode prosseguir com fixtures sintéticos e gates internos. Nenhum preço deve ser publicado por esta documentação.

## 7. Decisão de preço e infraestrutura (2026-10-20)

### 7.1. DECISÃO APROVADA: preço de entrada

- Produto: **FM NFCore V1**; plano comercial: **Essencial**.
- Mensalidade aprovada pelo responsável da FM: **BRL 149,00 (R$ 149,00/mês)**, e **não** R$ 149,90 nem R$ 69,90.
- Escopo desta aprovação: **valor da mensalidade**, não franquia final de CNPJs, notas, tokens de IA, excedentes, contratação anual ou publicação pública. A proposta anterior continha 1 CNPJ e 500 notas, mas essa combinação ainda depende de cálculo de margem e de aceitação comercial.
- O preço deve ser persistido no catálogo FM versionado pela autoridade `CommercialPricingAdministrationService` somente após definir os demais campos contratuais e aprovar a publicação. Não alterar código de preços nem criar plano paralelo.
- A venda e o trial real exigem os gates operacionais externos, além das configurações efetivamente publicadas no catálogo.

### 7.2. DECISÃO DE DIREÇÃO: Contabo como destino de hospedagem de baixo custo

- Provedor selecionado pela FM como **TARGET**, não CURRENT: **Contabo**, VPS de entrada com **8 GB RAM**.
- Valor de orçamento informado pelo responsável: **R$ 43,00/mês**. **Cotação informada pelo cliente, ainda não confirmada na fatura/checkout**, depende da região, moeda, impostos e opcionais.
- Oferta contemporânea de referência oficial: `Cloud VPS 4` (Core VPS) com 4 vCPU compartilhadas, 8 GB RAM, 100 GB SSD, porta 200 Mbit/s. Confirmar a SKU e os termos efetivos da compra: https://contabo.com/en/pricing/ e https://docs.contabo.com/docs/servers-hosting/vps/
- Oportunidade de contribuição antes dos demais custos: **R$ 149,00 - R$ 43,00 = R$ 106,00**, se **um único cliente** custeasse a VPS inteira. Isso **NÃO é lucro**: faltam operação fiscal, provedores, certificados, backup, tributos, gateway, IA, suporte, egress, monitoramento e mão de obra. Se houver 5 clientes, o custo fixo de R$ 43,00 equivaleria a R$ 8,60/cliente, antes do aumento de capacidade.
- CURRENT técnico: API, Worker, Portal e PostgreSQL estão implantados no projeto `FM NFCORE Staging` do Railway. A aquisição e a presença da VPS em execução foram comprovadas por captura do painel Contabo em 20/10/2026; isso **não comprova instalação ou homologação das aplicações**, nem autoriza DNS, cutover ou exclusão do Railway.
- TARGET inicial a avaliar: hospedar a **mesma aplicação e os mesmos containers** (API, Worker, Portal, PostgreSQL) no VPS, com volumes persistentes, configuração de segredos protegida e isolamento externo de PostgreSQL; proxy TLS; backup **criptografado off-host** e restauração periódica. Não desenvolver segunda API/autenticação/persistência nem acoplar o produto à Contabo.
- Um VPS único é ponto único de falha. As metas reais de CPU, RAM, IOPS, disco, concorrência, filas, retenção legal de XML/PDF, disponibilidade, RPO/RTO e degradação devem ser medidas por ensaios de carga e recuperação. A capacidade de 8 GB é uma **hipótese de sizing inicial, não certificação**.
- Snapshots não substituem backup recuperável. O backup automático Contabo é adicional e possui retenção limitada; avaliar backup externo independente. Referência: https://docs.contabo.com/docs/servers-hosting/vps-auto-backup/
- A VPS já foi adquirida pelo responsável. A preparação de hospedagem foi solicitada; ainda não há autorização para apagar instalações preexistentes, reinstalar o sistema operacional, expor bancos, migrar bancos reais, alterar domínio/TLS de produção ou executar cutover irreversível sem inventário, backups e rollback comprovados.

### 7.3. CURRENT -> TARGET e gates

CURRENT: preço Essencial aprovado, ainda não publicado no pricing; Railway staging existente; VPS Cloud VPS 4 contratada e visível como em execução na Contabo, com orçamento mensal de R$ 43,00 informado pelo usuário (fatura e valor exato ainda não verificados).

TARGET: plano Essencial R$ 149,00/mês no catálogo administrado da FM; NFCore executando na estrutura Contabo validada, com rollback Railway, tenant isolation, idempotência, observabilidade e recovery intactos.

Gates: proposta comercial detalhada -> aprovação de quotas/overage -> catálogo FM publicado -> avaliação de contrato Contabo -> sizing/carga/backup/restore -> provisioning governado -> deploy da mesma aplicação -> E2E staging -> DNS/TLS/cutover quando especificamente aprovado.

### 7.4. Checkpoint de implantação compartilhada — 20/10/2026

**Blueprint operacional detalhado desta decisão:** [FM_TECNOLOGIA_CONTABO_MULTI_SAAS_BLUEPRINT_2026-10-20.md](FM_TECNOLOGIA_CONTABO_MULTI_SAAS_BLUEPRINT_2026-10-20.md). Este é o documento de continuidade para redes Docker segregadas, NPM existente, AtendeVendeIA/Evolution, Kordena e NFCore. Não substituir por Compose de demonstração sem antes auditar CURRENT.

**DECISÃO APROVADA:** iniciar a hospedagem de **Kordena, AtendeVendeIA e NFCore** na **mesma VPS Contabo Cloud VPS 4, 8 GB de RAM**, região US-central. O usuário apresentou captura do painel indicando VPS **em execução**. Instância e IP são dados operacionais e **não serão versionados em arquivos públicos**.

**ESTADO DE ACESSO CONFIRMADO:** testes TCP do computador autorizado: SSH porta 22 acessível, HTTP 80 e HTTPS 443 ainda fechadas. A chave SSH do host já consta em `known_hosts` local, mas autenticação SSH administrativa não interativa com as chaves disponíveis falhou (`Permission denied (publickey,password)`). Não foi realizada instalação, login administrativo, modificação da VPS nem transferência de segredos. Próximo pré-requisito: conferir SO pelo console VNC do painel e habilitar chave SSH pública do dispositivo autorizado, sem inserir senha root ou chave privada no GitHub/chat.

**Repositórios CURRENT auditados e próximos passos específicos:**
- Kordena: `faabio3131/fm-ai-platform`, main `9a047f98d45574eb7dbf171a9fff8fe5a79fcb2d`; backend Python/FastAPI e frontend Next.js; confirmar banco atual, dependências, PRs não integradas e testes antes de criar build/compose, sem sobrescrever ambientes Render/Railway.
- AtendeVendeIA: legado/vertical `faabio3131/fm-vendedor-recuperacao-vendas`, main `f8040738e3f6030c364fb8fabba311d242de86ed`; já contém `deploy/hetzner/docker-compose.prod.yml`, Caddy e scripts backup/restore/rollback adaptáveis **sem segundo frontend**. Fundação mais recente usa `faabio3131/-FM-Assistant-Base` e `faabio3131/FM-Core-Base-`, com PRs em Draft: **reconciliar identidade do artefato deployável** antes de publicar para não regredir funcionalidades.
- NFCore: `faabio3131/nf-core-v001`, main `476e97b79202e45369156144f9c4e10fe9dd478e`, `compose.yaml` e três Dockerfiles reutilizáveis. O `compose.yaml` atual possui **defaults locais de desenvolvimento** (senha, HTTPS desativado e portas diretas) e **não é homologado como Compose de produção**. Railway staging possui migração v18 e serviços originais, preservar até novo E2E.

**Arquitetura-alvo comum sem autoridades duplicadas:**
- Reverse proxy central único em 80/443 com TLS, rotear hostnames individualmente para os serviços. Não subir três proxies Caddy separados brigando por essas portas.
- Contêineres e redes isolados por produto; PostgreSQL com **bancos e roles separados**, ou clusters separados quando capacidade e risco justificarem. Nunca compartilhamento de tabelas, usuários de banco, sessão, RBAC, tenant, segredos ou credenciais fiscais entre SaaS.
- Workers do NFCore, Kordena, FM Assistant e eventuais integrações externas com limitação de memória/CPU/concorrência, healthchecks e reinício governado. Evolution API, Core/Assistant e demais serviços adicionais contam no sizing; **8 GB é hipótese de capacidade, não certificação**.
- Um só servidor = ponto único de falha; backup de banco **criptografado fora do VPS**, restore testado, retenção, RPO/RTO, observabilidade e resposta a incidente antes do Go/No-Go.
- Migrar **um SaaS por vez**, com inventário de contratos/segredos, teste isolado, comparação com CURRENT e rollback; não trocar DNS dos três simultaneamente. Fazer cutover/produção só com gate e aprovação específica. Nunca carregar credenciais reais para Git.

**PENDÊNCIA FUNDAMENTAL DE EXECUÇÃO:** acesso administrativo seguro à VPS; após isso, inventário não destrutivo do SO, disco, RAM, Docker, firewall e backup; preparar proxy/redes/volumes e então empacotamento das aplicações canônicas. Este checkpoint é documentação, não deploy.
