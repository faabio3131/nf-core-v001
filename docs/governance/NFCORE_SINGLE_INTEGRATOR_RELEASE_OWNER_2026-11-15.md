# NFCore V1 — Único Integrador e Gestor de Release

**ID:** NFCORE-GOV-RELEASE-001  
**Data:** 2026-11-15  
**Status:** DECISÃO APROVADA PELO PROPRIETÁRIO — protocolo de coordenação vigente  
**Fonte da decisão:** issue [#447, checkpoint de propriedade de integração](https://github.com/faabio3131/nf-core-v001/issues/447#issuecomment-6903641344).  
**Escopo:** projeto `faabio3131/nf-core-v001`; este documento não autoriza nem executa mudanças em `main`, `production` ou Contabo.

## 1. Regra de governança

**Somente um agente tem a responsabilidade técnica e operacional de inspecionar entregas, aceitar integrações, executar merges das PRs de origem nas candidatas e coordenar a promoção `main`/Web/`production`: o AGENTE INTEGRADOR / RELEASE MANAGER.**

A função está atribuída à **frente de arquitetura/core que executa a PR #504 e supervisiona as PRs #468 e #498 nesta conversa**, até reatribuição expressa do proprietário. O executor municipal não faz merge de PRs próprias no branch cumulativo e não promove releases. Outros agentes/revisores podem emitir pareceres e testes, mas não exercem uma segunda autoridade de integração.

### Papéis e fronteiras

| Ator | Faz | Não faz |
|---|---|---|
| **Agente A — executor municipal** | Pesquisa contratos, implementa um município/bloco em PR própria; executa testes e CI; entrega HEAD/evidências; corrige achados. | Merge na candidata #468, `main` ou `production`; promoção, deploy, migration e alterações em branches de outro executor. |
| **Agente Integrador / Release Manager — frente arquitetura/core** | Confere CURRENT, riscos, conflitos, testes e contratos; decide aceite técnico; efetua **unicamente os merges autorizados nas candidatas**, reconcilia #468 e #498; exige CI pós-merge no SHA final; organiza staging/rollback, prepara promoção e registra evidências. | Ignora rulesets, certifica sem CI, mascara regressões, declara revisão independente própria, amplia escopo de autorização humana ou publica sem gates. |
| **Revisor técnico independente / EGM** | Revisa os pontos críticos por função e evidência; pode reprovar e requisitar correções. | Faz merge ou promove release fora do Integrador. |
| **Proprietário (autoridade humana final)** | Autoriza expressamente gates protegidos, produção, secrets, certificado real, migration, DNS, emissão fiscal real e Go/No-Go. | — |

**Separação de deveres:** quando o Integrador também implementa (ex.: #504), a revisão independente deve ser de outro revisor; responsabilidade de coordenação única NÃO equivale à autocertificação.

## 2. Fluxo obrigatório de handoff e promoção

```text
AGENTE A (implementa em PR própria)
    → testes + CI do HEAD exato + checklist + documentação
    → HANDOFF registrado na issue #447
    → INTEGRADOR: revisão independente, diff, contratos, segurança e CI
        → pedir correções OU aceitar
        → merge SE autorizado na candidata interna #468
        → CI integral no NOVO HEAD da #468, verificar resultado
    → REPETIR para outras entregas sem paralelizar merges na mesma branch
    → fechar seis pendências internas, EGM e gates T2/T3
    → PROMOÇÃO #468 → main mediante gate/autorização humana aplicável
    → reconciliação #498 com main (preservar Bling/worker e demais infra)
    → staging, schema v22, backup real, A1, rollback/smoke e Go/No-Go
    → PROMOÇÃO #498 → production apenas após validação e aprovação humana
    → verificação no servidor, observabilidade e checkpoint final
```

### Modelo de HANDOFF (Agente A)

```text
HANDOFF MUNICIPAL → INTEGRADOR
PR origem: #<número>; branch: <nome>; HEAD exato: <SHA>
Município/bloco: <nome/IBGE/provedor>
CI: <link>; Ruff/Mypy/Pytest/UI/E2E/security: <estado>
Contrato oficial e SHA dos artefatos: <evidência>
Aceite: <casos positivos/negativos/tenant/idempotência>
Lacunas EXTERNAL_BLOCKED: <evidência e autoridade externa>
Conflitos/áreas protegidas: <paths>
Status: READY_FOR_INTEGRATION_REVIEW (não é MERGED nem PRODUCTION_APPROVED)
```

O Integrador só promove o status a `INTEGRATED_INTERNAL` depois de merge e CI cumulativa no SHA exato. Nenhum PR é considerado certificado se sua CI não corresponde ao HEAD final; branches com commits novos exigem reteste.

## 3. Linha única e anti-duplicação

- **#468** é a candidata cumulativa de engenharia fiscal para `main`. PRs municipais entregam a ela, jamais criam outro motor.
- **#504** é a PR de lacunas internas do núcleo/Portal; permanece Draft enquanto seus seis critérios não forem atendidos.
- **#498** é a candidata Web/infra para `production`; não é uma segunda autoridade fiscal e deve absorver a árvore reconciliada após #468/`main`.
- O Integrador é o único agente a realizar a operação de merge; assim evitam-se merges concorrentes, atualizações baseadas em CI antiga, perdas de código e SHA desatualizado.
- Merge sem conflito textual não prova compatibilidade semântica. Revisar arquivos compartilhados e reexecutar a matriz integrada.

## 4. Gates imutáveis

1. HEAD/branches/CI atualizados, nenhuma mudança cega.
2. Testes, contrato normativo, segurança, Auth/RBAC, tenant/unidade, idempotência e persistência conforme impacto.
3. Revisão independente onde exigida e pendências internas reais concluídas; `EXTERNAL_BLOCKED` somente para evidências genuinamente externas.
4. Sem desabilitar testes, regras de GitHub ou pré-flight para obter verde.
5. `main` e `production` protegidas. Migração em PostgreSQL real, cofre A1, backup/restore, staging, TLS/DNS e deploy real exigem aprovações humanas específicas e evidência.
6. Cada merge autoriza **somente aquele merge explicitamente aprovado**; a designação de Integrador não é delegação permanente de privilégios, nem substitui o Go/No-Go humano.

## 5. Aplicabilidade e enforcement

O checkpoint [#447](https://github.com/faabio3131/nf-core-v001/issues/447#issuecomment-6903641344) dá publicidade imediata à nova responsabilidade. Esta documentação orienta as duas frentes a partir de agora.

**Limite técnico confirmado:** a conta/app do GitHub pode não distinguir dois agentes de IA que atuem com a mesma identidade de conexão. Nesta data não foi encontrado `.github/CODEOWNERS` na `main`. Portanto, a exclusividade estabelecida aqui é **regra de processo**, não uma garantia de enforcement automático. Para impedimento por permissão, o proprietário deve configurar proteção de branches, exigência de aprovação e identidade exclusiva de merge (GitHub Settings/Rulesets), sem interromper os checks já existentes.

## 6. Baseline técnico de entrada

- `#503` Salto MERGED somente na #468; `#468@440f406552567135e1ffcfd6a64e64003448d3b6`, CI integral #43777083394 **SUCCESS**.
- `#504@4a31471cb1c093a42993e5ceeaeea36278f7646f` OPEN/DRAFT, CI #43762643929 **SUCCESS**, não integrada.
- `#498@798874e2f85c6b75b6eb995e2d6bbb6da7eaf628` OPEN/DRAFT, não publicada.
- `main@f23d2a050a4c1555de1bdbe8620bb69b6d983cc8` e `production@ea4bdd3bcb9b61e6522081a14e5cc9ad1ced9599`, não alteradas.
- Auditoria externa de DB v22/A1/Contabo continua distinta de CI da candidata e não é inferida como aprovada.

**Precedência:** esta decisão governa **responsabilidade de integração e promoção** e complementa (não revoga) as regras de arquitetura, o cronograma municipal e os gates de segurança anteriores.
