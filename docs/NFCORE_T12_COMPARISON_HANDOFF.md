# T12 — comparação anual multi-regime (24/11/2026)

Base certificada: main 7e1d797a40c444db90a18eb66506d9fa5d025bf3, #598, CI 45394058836 e governança 45394058967. A issue #599 é a autoridade do estado de execução. Branch feat/nfcore-economy-t12-comparison.

## Primeiro incremento (não certificado)
Motor tax/annual_regime_comparison.py, schema nfcore.annual-regime-comparison/v1. Reutiliza T07 assess_segregated e T11 simulate sem alterar alíquotas. Compara quatro trimestres de 2026 e 12 competências; exige 2025 completo para RBT12 e Fator R, receita ordinária doméstica, empresa estabelecida, apuração por competência, comércio/serviços gerais, elegibilidade revisada e janela abaixo do sublimite. O modelo de sensibilidade exige três cenários revisados explícitos, mantendo receita, atividade, UF e histórico anterior; não inventa custos, créditos nem novos fatos. PIS/Cofins ordinários com créditos negativos não alocados bloqueiam. Tributos fora do DAS e impacto líquido adicional RTC exigem evidência revisada; saldo bruto RTC é mostrado separadamente. Ranking de carga tributária não é autorização de opção nem previsão de lucro ou fluxo de caixa. Valores de outros tributos e compensações são entradas revisadas, não calculadas pelo motor inicial. Cenário de folha deve reconciliar resultado contábil e contribuições por regime com a revisão. Não há dedução automática de créditos ou de benefícios territoriais.

## Pendências internas (T12 não entregue)
- Executar e revisar os testes focais; verificar Ruff/Mypy e CI integral do HEAD.
- Revisar escopo fiscal, reconciliação do resultado e dos créditos/ajustes anuais, base temporal e tratamento explícito de elegibilidade. Conferir números com referência contábil independente.
- Integrar importação T01 imutável por tenant/unidade/ambiente/emitente, bind de referências, autorização/CSRF, API e Portal com explicação de lacunas. Testar RLS, replay, RBAC, PostgreSQL, E2E e regressão.
- Revisão independente, autorização específica de merge, CI pós-merge e atualização do cronograma; T13 permanece bloqueada.
- Expansão de outros escopos/competências/territórios no backlog, sem fabricar cobertura. Uso real e validação contábil externa não comprovados.

Não alterar main/production, sem deploy, transmissão, pagamento ou mudança de regime. Testes sintéticos ainda não executados no momento deste registro.
