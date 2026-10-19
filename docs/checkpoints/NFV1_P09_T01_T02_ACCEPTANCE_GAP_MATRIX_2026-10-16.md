# NFV1 — P09-T01/T02 — Matriz de aceite e continuidade sem retrabalho

Data: 2026-10-16. Base auditada: main `95cd0a852aea001c7bde0a84e5e0c2b4ac111be6`.
Escopo: reconciliação documental *read-only* de evidências já publicadas; **não** certifica novas entregas, execução de testes, runtime ou homologação externa. Cronograma canônico: `docs/NFCORE_V1_COMPLETION_MASTER_EXECUTION_SCHEDULE_2026-10-05.md`; ledger: `docs/NFCORE_V1_EXECUTION_LEDGER.md`.

## P09-T01 — Tracing
Critério oficial: **traces de API, DB, chamadas externas e Worker, ativados e provados**.

| Critério | Evidência conhecida | Estado |
|---|---|---|
| API | PRs #172/#187 integradas segundo checkpoint antirretrabalho | IMPLEMENTED_NOT_CERTIFIED — provar trace/exporter |
| DB | não há nesta reconciliação demonstração runtime/exporter por span | EVIDENCIA_INSUFICIENTE |
| Chamadas externas | não há nesta reconciliação demonstração de traces externos end-to-end | EVIDENCIA_INSUFICIENTE |
| Worker | instrumentação existente deve ser verificada contra #172/#187 e runtime | IMPLEMENTED_NOT_CERTIFIED |
| Exporter real / staging | checkpoint vigente informa pendência de prova operacional | EVIDENCIA_INSUFICIENTE |

**Conclusão:** manter [ ] e investigar provas faltantes, não recriar tracing.

## P09-T02 — Métricas
Critério oficial: **HTTP/error/latency; commercial events; fulfillment; worker backlog; retries; dead-letter; provider errors; fiscal rejection; reconciliation; activation**.

| Eixo | Evidência a reaproveitar | Classificação |
|---|---|---|
| HTTP/error/latency | PRs integradas #193–#200; PR #188 histórica parcial | IMPLEMENTED_NOT_CERTIFIED; comparar diff #188 contra main |
| Commercial events | checkpoint informa instrumentação da oferta e webhook | IMPLEMENTED_NOT_CERTIFIED; matriz evento por evento |
| Fulfillment | não demonstrado integralmente | EVIDENCIA_INSUFICIENTE |
| Worker backlog | PRs integradas incluem dispatch; verificar gauge real de backlog por partição | IMPLEMENTED_NOT_CERTIFIED |
| Retries / dead-letter | conferir contador, labels e cenários reais de Worker | EVIDENCIA_INSUFICIENTE |
| Provider errors | cobertura específica de falhas de provider não certificada | EVIDENCIA_INSUFICIENTE |
| Fiscal rejection | nome de métrica em teste **não** prova evento fiscal instrumentado | EVIDENCIA_INSUFICIENTE |
| Reconciliation | prova de emissão observável não identificada | EVIDENCIA_INSUFICIENTE |
| Activation | PRs integradas instrumentam tentativas; comprovar sucesso/falha e isolamento | IMPLEMENTED_NOT_CERTIFIED |
| Integridade de counter | PR #201 HEAD `d76e538e84db93315c0960a4835fd51d986c29e0` | CI #952 SUCCESS, Governance #373 SUCCESS; **OPEN, não mergeada** |

### Integridade #201 — avaliação do delta
Diff: `runtime/observability.py` calcula valor acumulado sob lock, verifica `math.isfinite(updated)` antes de gravar, preservando sample anterior em overflow. Dois testes: overflow não corrompe snapshot e incrementos válidos acumulam. Escopo limitado, sem novos adapters, schemas ou segredos. **Não representa instrumentação fiscal real**. CI e Governança foram conferidas para o HEAD acima; revalidar HEAD/mergeability e CI contra main no gate final. Merge em main requer autorização específica.

## Dívidas / PRs abertas que NÃO podem desaparecer
- #201 — candidata corretiva de contador, CI/Governança verdes no HEAD consultado; sem merge.
- #188 — instrumentação HTTP antiga e parcial; comparar contra main antes de qualquer integração.
- #189 — relatório de paridade Web não integrado; gaps informados: handlers fiscais vazios, checkout/acquisition/trial/receivers não compostos, pricing não publicado, release indisponível. Validar contra CURRENT, não refazer blocos sem evidência.
- #165 — documento GSM histórico; supersedência precisa ser demonstrada antes de fechar.
- #182 — melhorias de senha do Portal; verificar se já integradas ou ainda pendentes.
- #204 — complemento documental P05; não executar novamente Worker/GSM/migration17/deploy.

## Preservação P05
PR #203 mergeada na main deste checkpoint. Checkpoint `NFV1_P05_T01_T02_CLOSEOUT_RECONCILIATION_2026-10-16.md` comprova T02 same-SHA `2f3689838cfbec1c6d2ffac614cb0eb364d91633` em API/Portal/Worker. T01 ainda demanda **prova**, não repetição automática: SQL de versões atuais 1..17/Cakto 1..2, adequação de backup/baseline após migration, quando exigido. Provas operacionais posteriores: T03 smoke, T04 E2E autenticado, T05 rollback real. Não executar operações de cloud sem autorização.

## Ordem técnica mínima a partir deste documento
1. Validar integração efetiva e CI do HEAD da #201; sem novo código para corrigir overflow.
2. Auditar diretamente na main os consumidores de métricas, eventos e testes existentes, fechando cada linha da tabela por **código + teste + CI + runtime se aplicável**.
3. Implementar somente o delta real para fulfillment, retry/dead-letter, provider/fiscal/reconciliation e tracing, em recortes pequenos.
4. Promover [x] apenas quando todos os requisitos da tarefa forem comprovados segundo o cronograma; manter zero overclaim e nenhuma duplicação.
5. Prosseguir com as demais pendências internas do ledger e com paridade Web, mantendo homologação fiscal externa como bloqueio separado e explícito.

Estados: `PRODUCTION_APPROVED=NO`; `COMMERCIAL_LIVE=NO`.
