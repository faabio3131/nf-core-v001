# #625-03 — SELIC: conservação de centavos e resíduo (candidata em preparação)

## CURRENT — PREPARED_NOT_CERTIFIED — 27/11/2026 BRT

Base funcional certificada #631: `98e10ed6158a4d8e2c5b61175c48171297b0ae84`. #632 documental segue com gates próprios; não integrar ou certificar #625-03 antes da certificação documental e da revalidação da base. A construção interna foi autorizada a prosseguir sem aprovação externa pelo proprietário. Ver issue #625 e parecer técnico #issuecomment-7231951240.

### Decisão técnica interna

Preservar T17 (Fraction, arredondamento existente por parcela) e T18 (componentes inteiros não negativos e conservação por lote). Não redistribuir centavos, não permitir SELIC sem principal nem apagar residual. A reserva nova T19 federal, após validar fonte e valor, rejeita excesso de componente e a tentativa de consumir o último principal deixando SELIC residual. Parcela não terminal pode deixar diferença explícita. O relatório retorna diagnóstico por lote federal, inclusive legado avulso, comparando o saldo disponível com o cálculo T17 sobre o principal remanescente na data original de valoração e com o vínculo exato versão/digest. A diferença assinada não prova isoladamente arredondamento, não é crédito adicional e não entra nos agregados. Base indisponível não vira zero. Não revalorar pelo mês atual (#625-04). Permitir replay e desfazimento legítimo, sem retroalterar eventos; cancelar/rever a partição para liberar o saldo. A implementação não altera T17, o escritor T18, schema persistido, API externa, RBAC/MFA, política fiscal real ou workflows. Revisar impacto de leitura adicional por lote no #625-05.

### Gates internos

Testes unitários de partições positivas, negativas e exatas, saldo residual sem principal, base indisponível; PostgreSQL com fontes sintéticas T15/T16/T17 reais no ambiente de teste, rollback, replay, cancelamento e nova reserva. Ainda não executados no runtime nesta candidata. Exigir CI integral, análise de compatibilidade de histórico e E2E, revisão independente segregada, T2 efetiva e autorização específica de merge, certificação pós-merge. Reconciliar AGENTS.md, cronogramas, ledgers e XLSX com a nova ordem do proprietário em commit documental separado, sem reabrir a candidata #632. Não incrementar 20/51 nem desbloquear T21 antecipadamente.

- [ ] EXTERNAL_BLOCKED: validação da política de alocação em PER/DCOMP real por responsável fiscal/contábil; não bloqueia engenharia e certificação interna.

Toda a V1 deve poder ser construída/testada/certificada internamente sem aprovações de terceiros. Simulação não é homologação real. Sem deploy, reconhecimento ou operação fiscal real.
