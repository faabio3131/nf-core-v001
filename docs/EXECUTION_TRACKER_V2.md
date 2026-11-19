> **Referência de continuidade NFCore V1 — 17/11/2026:** este tracker V2 preserva certificações históricas de engenharia e NÃO é fonte do CURRENT da linha fiscal/Web de novembro. Consulte [Anexo de reconciliação e cronograma](audit/NFCORE_RECONCILIATION_CLOSEOUT_SCHEDULE_2026-11-17.md) e [Pendências CURRENT](audit/NFCORE_PENDING_REGISTER_CURRENT_2026-11-17.md) antes de interpretar os estados da main/production, municípios, homologação e release. Nenhuma célula fiscal ou deploy foi certificado pela inclusão desta referência.

# FM FISCAL CORE V2 — EXECUTION TRACKER

Data de início: 2026-09-11  
Repositório: `faabio3131/kordena-fiscal-engine-v2`  
Status global: **ENGENHARIA INTERNA V2-00..V2-18.11 CONCLUÍDA/CERTIFICADA; CÓDIGO PROMOVIDO PARA `main`; PRODUÇÃO/CUTOVER REAL AINDA BLOQUEADOS POR PRÉ-CONDIÇÕES REAIS.**  
Release Candidate técnico: **FM Fiscal 2.18.0-rc.1**

## Regra de governança atual

Estados permitidos: `PENDENTE`, `EM EXECUÇÃO`, `BLOQUEADO`, `CONCLUÍDO`.

A autorização de 2026-09-13 permitiu promover para `main` código certificado e reconciliar PRs antigas quando os gates estivessem verdes. Essa promoção de fonte foi executada. Ela **não equivale** a deploy produtivo, homologação oficial, migração produtiva, ativação de autoridade fiscal real, freeze de writers, uso de segredo real ou cutover.

Homologação oficial continua exigindo evidência externa real. `PRODUCTION_APPROVED` não pode ser inferido a partir de CI, merge ou Release Candidate.

## Estado por fase

| Fase | Escopo | Status | Evidência principal |
|---|---|---|---|
| V2-00..V2-11 | Equivalência → Control Plane | **CONCLUÍDO / INCORPORADO EM `main`** | histórico PRs #1-#12 / promoção #24 |
| V2-12 | Gateway/Signer/Vault | **CONCLUÍDO / INCORPORADO EM `main`** | 508 PASS / promoção #24 |
| V2-13 | Observabilidade/Compliance | **CONCLUÍDO / INCORPORADO EM `main`** | 563 PASS / promoção #24 |
| V2-14 | Hardening sistêmico | **CONCLUÍDO / INCORPORADO EM `main`** | 582 PASS / promoção #24 |
| V2-15 | Homologação/pilotos | **INTERNO CERTIFICADO / EXTERNO PENDENTE** | 620 PASS / evidência oficial externa ainda necessária |
| V2-16 | Integração produtos FM | **INTERNO CERTIFICADO / CONSUMIDORES PARCIAIS** | 646 PASS / consumer states abaixo |
| V2-17.1 | Readiness + single authority | **CONCLUÍDO/CERTIFICADO** | 116 source / 651 PASS |
| V2-17.2 | Migration + rollback rehearsal | **CONCLUÍDO/CERTIFICADO SINTÉTICO** | 117 source / 660 PASS |
| V2-17.3 | Cutover rehearsal / authority transfer | **CONCLUÍDO/CERTIFICADO SINTÉTICO** | run `34787607567`, 118 source / 675 PASS |
| V2-17.4 | Consumer integration closure | **CONCLUÍDO COMO REAUDITORIA GOVERNADA** | blockers reais preservados |
| V2-17.5 | Final convergence readiness | **CONCLUÍDO/CERTIFICADO** | cutover real ainda bloqueado |
| V2-18.1 | Product identity + packaging | **CONCLUÍDO/CERTIFICADO** | 120 source / 681 PASS |
| V2-18.2 | Public developer documentation | **CONCLUÍDO/CERTIFICADO** | docs públicas/sintéticas |
| V2-18.3 | Self-service onboarding | **CONCLUÍDO/CERTIFICADO** | idempotent/checkpoint/fail-closed |
| V2-18.4 | Plans + entitlements + billing foundation | **CONCLUÍDO/CERTIFICADO** | commercial billing separado da authority fiscal |
| V2-18.5 | SDKs | **CONCLUÍDO/CERTIFICADO** | Python + TypeScript reference / Bridge público |
| V2-18.6 | SLA + support + operations | **CONCLUÍDO/CERTIFICADO** | SEV1–SEV4 + runbooks + health |
| V2-18.7 | LGPD + retention + compliance técnico | **CONCLUÍDO/CERTIFICADO** | `LEGAL_VALIDATION_REQUIRED` preservado |
| V2-18.8 | Premium Product Experience | **CONCLUÍDO/CERTIFICADO** | run `34791085676`, 126 source / 724 PASS |
| V2-18.9 | Commercial End-to-End | **CONCLUÍDO/CERTIFICADO** | run `34791237542`, 126 source / 730 PASS |
| V2-18.10 | Security + Performance + DR | **CONCLUÍDO/CERTIFICADO** | run `34791936752`, Bandit + pip-audit + 741 PASS |
| V2-18.11 | Release Candidate Closure | **CONCLUÍDO/CERTIFICADO** | `2.18.0-rc.1` / gate final abaixo |

## Certificação final interna V2

HEAD final certificado antes da promoção:

`5ffa561e6459177f97829c223fdd2faf7b36415a`

Gate final:

- run `34792183667`;
- job `103818329390`;
- Install PASS;
- Ruff PASS;
- Mypy PASS — **126 source files**;
- Bandit PASS;
- pip-audit PASS — **No known vulnerabilities found**;
- Pytest **741 PASS em 7.34s**.

Durante V2-18.10, o dependency audit detectou vulnerabilidades reais em `cryptography 47.0.0`. A faixa de runtime foi corrigida para `cryptography>=50,<51`; o gate final executou com `cryptography 50.0.1` e permaneceu totalmente verde.

## Promoção de código para `main`

Antes da promoção, o compare `main` → `v2/commercial-independent-product` comprovou:

- **723 commits à frente**;
- **0 commits atrás**;
- merge-base exatamente no antigo `main` `ed6c91deac5c0f160f6564328bb5b35bab8c5ae5`.

A PR cumulativa **#24 — `FM Fiscal V2 — promote certified 2.18.0-rc.1 to main`** foi mergeada com o HEAD esperado travado em `5ffa561e6459177f97829c223fdd2faf7b36415a`.

Merge commit em `main`:

`5c9cbb6b42d715f5686be5a4e8d2cb622f8d3c97`

O compare pós-merge confirmou `main` exatamente **1 commit à frente** do HEAD certificado, **0 atrás**, merge-base no próprio HEAD certificado e **nenhum arquivo divergente**. O commit adicional é apenas o merge da PR #24.

As PRs históricas stacked V2-00..V2-18 foram reconciliadas como incorporadas pela promoção cumulativa. Não há PR permanente antiga aberta no repositório do Core após a reconciliação.

## V2-15 — homologação externa

Todo o trabalho interno B0-B6 está certificado. Continuam externos, quando aplicáveis:

- certificados privados reais;
- CSC real;
- provider credentials reais;
- conectividade/ambientes/respostas oficiais;
- evidência oficial por jurisdição/documento/operação;
- pilotos externos autorizados.

Nenhum provider, UF ou município foi declarado oficialmente homologado sem evidência.

Documento: `docs/V2_15_CLOSURE_CERTIFICATION.md`.

## V2-16 — consumidores após promoção

### Kordena

PR `faabio3131/fm-ai-platform#118` permanece **OPEN/DRAFT**, HEAD `9ee10a08cf445cc7233cde5b70564f8feade315c`, situação funcional **PARCIAL**. Os workflows do HEAD estão verdes, porém Web Premium/FISC-20 e a conclusão funcional do consumidor permanecem blockers reais. Portanto **não foi mergeada nem promovida como pronta**.

### Iron Fit

PR `faabio3131/iron-fit-backend#48` foi mergeada após gate certificado e auditoria de workflow sem deploy automático.

Merge em `main`: `9763f9a3fd41cad1a9cf67ea36ae9bf67189bd24`.

Gate pós-merge em `main`: run `34793571834` — **SUCCESS**.

O handoff fiscal continua fail-closed em `PENDING_CAPABILITY` até existir readiness fiscal aplicável.

### Vendedor IA

PR `faabio3131/ai-sales-saas-vendedor-ia#1` foi mergeada após gate certificado e auditoria de workflow sem deploy automático.

Merge em `main`: `ec13fee2829ffe17c1e25c1dbffcc76070caee5c`.

Gate pós-merge em `main`: run `34793618320` — **SUCCESS**.

Permanece bloqueada a emissão efetiva enquanto faltarem CPF/CNPJ/endereço fiscal e fatos suficientes para seleção segura NF-e versus NFC-e. O adapter preserva `PENDING_FISCAL_CLASSIFICATION` / fail-closed.

### CampaIA

PR `faabio3131/CampaIA#1` foi mergeada após gate certificado e auditoria de workflow sem deploy automático.

Merge em `main`: `fba7fccf1b1e6808a75f41bc6f8b971b60c9f2b8`.

Gate pós-merge em `main`: run `34793636144` — **SUCCESS**.

Permanece bloqueada a integração runtime enquanto não existir fato real/autoritativo de faturamento/pagamento próprio da CampaIA. Verba de campanha/media spend continua explicitamente fora dessa autoridade.

## V2-17 — convergência e cutover

V2-17.1..V2-17.5 estão internamente certificadas: readiness/single authority, migration + rollback rehearsal, cutover/authority-transfer rehearsal, consumer reauditoria e final readiness.

HEAD histórico final V2-17:

`cfd58c3249a5601dc62088eee7327dfe02759646`

Gate final V2-17:

- run `34787708874`;
- job `103806110253`;
- Install/Ruff/Mypy PASS;
- **118 source files**;
- Pytest **675 PASS**.

A PR histórica #19 foi fechada como **incorporada pela promoção cumulativa #24**, não como trabalho descartado.

## V2-18 — produto comercial independente

Release Candidate técnico:

`FM Fiscal 2.18.0-rc.1`

Manifesto: `docs/V2_18_RELEASE_CANDIDATE_MANIFEST.md`  
Closure: `docs/V2_18_CLOSURE_CERTIFICATION.md`  
Auditoria 0–100%: `docs/V2_FINAL_0_100_AUDIT.md`

A PR histórica #22 foi fechada como **incorporada pela promoção cumulativa #24**. O código do RC está em `main`; isso não significa que um release produtivo foi realizado.

## Auditoria de prontidão

Última classificação formal:

- Engenharia interna: **100%**;
- Produto comercial técnico interno: **100%**;
- Integrações: **80%** antes da promoção; código certificado de Iron/Vendedor/CampaIA agora está em `main`, mas blockers funcionais de Kordena/Vendedor/CampaIA continuam governando a prontidão real;
- Homologação/operação: **60%**;
- Total ponderado para produção real na auditoria final: **89%**.

O merge de código não transforma automaticamente essas métricas em 100% de produção.

## Gate de produção/cutover — AINDA NÃO SATISFEITO

A V2 está internamente construída e o código certificado foi promovido para `main`, porém **produção/cutover real continuam BLOQUEADOS** enquanto qualquer pré-condição obrigatória permanecer pendente.

Pendências reais atuais:

1. concluir Kordena/Web Premium/FISC-20 e colocar o consumidor em estado funcional compatível;
2. concluir os fatos/dados fiscais de destinatário e classificação no Vendedor IA;
3. criar no CampaIA, quando o produto realmente precisar, uma authority real de own billing/payment;
4. obter evidência/homologação externa oficial aplicável;
5. provisionar certificados/CSC/provider credentials reais por canal seguro;
6. inventariar writers reais e preparar freeze governado;
7. executar snapshot/dry-run/migração produtiva somente em janela autorizada;
8. realizar reconciliação final e Go/No-Go operacional;
9. obter autorização humana específica para deploy/cutover produtivo.

Até lá, continuam proibidos: desativar legado, congelar writers reais, migrar banco produtivo, alterar DNS/endpoint produtivo, usar segredos reais fora de provisioning autorizado, emitir documento fiscal real sem readiness/homologação, ou promover `PRODUCTION_APPROVED` por inferência.

## Próximo ponto de continuidade

**Não há bloco interno V2-00..V2-18 pendente nem PR histórica do Core esquecida sem reconciliação.**

A próxima frente é resolver as pré-condições reais acima e, somente quando todas estiverem verdes, executar um novo **Go/No-Go de Produção + Cutover Real** com evidência atualizada.
