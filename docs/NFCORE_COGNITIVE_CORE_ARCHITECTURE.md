# NFCore — Core Cognitivo Fiscal V1: arquitetura

**Estado:** `IMPLEMENTED_NOT_EXTERNALLY_CERTIFIED` — fundação, classificação, conciliação, adaptador central FM (contrato proposto), governança/métricas, rota do Portal e painel implementados e testados; sem IA real conectada, sem homologação externa.
**Repositório:** `faabio3131/cognitivo-nfcore-inteligencia-fiscal` (cópia de `nf-core-v001@207fbf2`).
**Regra-mestre:** *o Core coordena e raciocina; os serviços determinísticos validam e executam.*
**Pacote:** `src/kordena_fiscal/cognitive/`.

## 1. Objetivo

Dar ao NFCore a maior capacidade cognitiva possível **sem** dar autoridade fiscal à IA.
O core entende rejeições, classificação tributária, conciliação e dúvidas do contador, sempre
com evidência e proveniência, e continua útil mesmo com a IA desligada.

## 2. Princípios (invariantes testados)

1. **Fatos são determinísticos.** Seções `FACT` e `SOURCE` nascem do catálogo e das evidências
   autorizadas. O modelo **nunca** escreve fatos; só hipóteses e ações sugeridas.
2. **Consultivo.** Nenhum caminho de escrita: a IA não emite, assina, transmite, cancela,
   inutiliza, altera imposto nem salva classificação. O resultado é `advisory_only`.
3. **Fail-open da operação, fail-closed da segurança.** Falha, timeout, circuito aberto, quota
   ou ausência de provedor => resposta **determinística** (baseline). Falha de autorização,
   escopo ou tenant => `DENIED`, sem dados.
4. **Tenant/unidade isolados.** Toda evidência carrega `tenant_id`/`unit_id`; divergência do
   escopo da requisição aborta antes de qualquer chamada ao modelo.
5. **Minimização e redação.** CNPJ, CPF, chave de acesso, e-mail, telefone, PEM, tokens e PAN
   são mascarados antes de sair do processo e também na saída (defesa em profundidade).
6. **Dado não confiável é dado.** Texto de XML, retorno de provedor e a pergunta do usuário
   entram em blocos cercados por *nonce*, nunca em instruções.
7. **Resposta do modelo é validada.** Cada seção precisa citar evidências existentes; números e
   códigos não presentes na evidência são descartados; alegações de execução e vazamento são
   barradas. Se nada sobra, volta ao baseline.
8. **Sem inventar norma.** O catálogo declara `review_status`. Entradas sem revisão normativa
   humana são apresentadas como tal. Código desconhecido => `INSUFFICIENT_BASIS`.
9. **Sem segredo, sem credencial de IA do cliente.** A credencial é da FM, central, via
   Vault/Secret Reference. Nenhuma chave de modelo neste repositório.
10. **Auditável.** Cada uso gera evento de auditoria (ids e hashes, nunca prompt integral) e
    registro de uso/custo idempotente por `request_id`.

## 3. Camadas

```
Portal/API (sessão, RBAC, tenant/unidade)            [T04: POST /v1/portal/cognitive/advise]
        │
        ▼
CognitiveAdviceService  ── orquestra e nunca levanta por falha de IA
  1 autorização de capability (fail-closed)
  2 isolamento de escopo das evidências (fail-closed)
  3 redação + ContextPack (fatos confiáveis × blocos não confiáveis)
  4 baseline determinístico (catálogo + evidências)   ← sempre calculado
  5 entitlement/quota (nega só a IA)
  6 auditoria de início (sem ela, sem IA)
  7 chamada ao modelo: bulkhead + circuit breaker + deadline
  8 OutputGuard (grounding, ações proibidas, vazamento)
  9 fusão: FACT/SOURCE do baseline + HYPOTHESIS/ACTION validadas
 10 ledger de uso + auditoria final
        │
        ▼
Portas (Protocols): AdvisoryModelPort · EntitlementPort · UsageLedgerPort · AuditSinkPort
        │
        ▼
Adaptadores: Null (padrão, IA desligada) · Central FM S2S (T01/T03, após contrato aprovado)
```

## 4. Capacidades

| Capability | Jornada | Evidência determinística |
|---|---|---|
| `cognitive.explain_rejection` | T04 | código/status de rejeição, estado do documento, catálogo |
| `cognitive.suggest_classification` | T05 | `TaxRuleOutcome`, catálogo CST/cClassTrib/NCM vigente, regime |
| `cognitive.explain_reconciliation` | T06 | `ReconciliationIssueCode`, estados e divergências |
| `cognitive.answer_accountant_question` | T06 | evidências fornecidas; sem base => incerteza explícita |

A fundação implementa contratos, segurança e a jornada de **rejeição** de ponta a ponta
(baseline + modelo). As demais entram em PRs seguintes, reutilizando a mesma base.

## 5. Contrato de resposta

`AdviceResult`: `status`, `sections[]` (`FACT` / `HYPOTHESIS` / `ACTION` / `SOURCE`, cada uma
com `evidence_ids`), `provenance` (correlationId, requestId, schemaVersion, hash do contexto,
evidências, provedor/modelo/versão, achados do guard, motivo de degradação, latência, uso),
`advisory_only=True`, `requires_human_approval=True`.

Status: `ADVISED` (modelo validado) · `BASELINE_ONLY` (determinístico; IA indisponível/negada)
· `INSUFFICIENT_BASIS` (sem evidência para responder) · `DENIED` (sem autorização/escopo).

## 6. Estado por item e o que depende de humanos

| Item | Estado | Depende de |
|---|---|---|
| Fundação, rejeição, classificação, conciliação, pergunta do contador | implementado e testado | — |
| Modelo próprio do NFCore (OpenAI-compatível; Gemini e OpenAI com troca automática) | implementado e testado com transporte simulado; chave lida só em tempo de chamada, enviada só no cabeçalho Authorization | chave **independente do NFCore** injetada pelo secret store (variáveis `NFCORE_COGNITIVE_AI_{PRIMARY,SECONDARY}_*`); limite de gasto no console de cada provedor |
| Ligação com o FM Command (métricas do core, somente leitura) | **lado NFCore implementado**: `GET /v1/command/cognitive/metrics` (token de control-plane dedicado, correlação obrigatória, contadores sem conteúdo). Especificação em `docs/NFCORE_COGNITIVE_COMMAND_METRICS_V1.md` | **conector do lado do Command** (hoje o NFCore é `UNSUPPORTED` lá) e o segredo `NFCORE_COMMAND_CONTROL_PLANE_TOKEN` no secret store |
| Auditoria durável | **implementada** no ledger `fm_control_plane_audit` existente (ação `cognitive_advice.recorded`), sem migration, só ids/hashes; sem ledger disponível = sem modelo, resposta determinística. O log (`LoggingAuditSink`) é só fallback de desenvolvimento | — |
| Cota de IA do piloto | teto diário por empresa/unidade e capacidade (`NFCORE_COGNITIVE_AI_DAILY_LIMIT`, padrão 100); estourou = só a IA é negada, a operação segue | plano comercial real no lugar da política fixa de piloto; cota em memória (reinício zera) |
| Credencial central de IA | não conectada | **Fábio** coloca no cofre; nenhum segredo neste repositório |
| Quota/plano/métricas (T07) | implementado (quota branda, em memória) | política de preço aprovada por Fábio; ledger persistente |
| Rota do Portal e painel (T04) | implementado; ligado só com `NFCORE_COGNITIVE_ENABLED=true`, sem modelo (determinístico) | ligar o adaptador central na composição após contrato + cofre |
| Bateria de avaliação golden/adversarial (T08) | implementada (`tests/cognitive/test_evaluation.py`) | ampliar com casos reais revisados por contador |
| Tabelas oficiais NCM (Siscomex, vigente 31/10/2026, Res. Gecex 926/2026, 10.516 NCMs de 8 dígitos) e cClassTrib CBS/IBS (Calculadora RTC, base V0066 de 28/10/2026, **ambiente piloto**, 170 códigos) | carregadas em `knowledge/official/` com manifesto e SHA-256 verificado na carga; ligadas na rota do Portal | revisão normativa humana; reatualizar quando o Gecex/Receita publicarem nova versão (o cClassTrib ainda é piloto) |
| Catálogos de rejeição, CST/CSOSN, PIS/COFINS e conciliação | sementes `PENDING_NORMATIVE_REVIEW` | revisão normativa humana por contador |

Limitações conhecidas: a projeção `errors` do Portal não expõe o `rejection_code` de emissão; não há projeção de leitura de decisão tributária (classificação fica sem evidência do Portal até existir); quota é process-local.

## 7. Evolução

Concluído: fundação → classificação → conciliação/contador → adaptador central → governança/métricas → rota e painel do Portal → avaliação. Próximos passos: injetar a chave própria do NFCore, expor métricas ao Command no padrão do Integration Fabric, persistir ledger/auditoria, curadoria normativa dos catálogos e certificação integrada após sincronizar com `nf-core-v001`.

## 8. Não objetivos

Emitir, assinar, transmitir, decidir imposto, substituir contador, fazer homologação externa,
deploy, migration. Nada aqui altera o motor fiscal determinístico existente.
