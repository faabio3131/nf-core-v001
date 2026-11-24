# T12 — comparação anual multi-regime (24/11/2026)

Base certificada: main 7e1d797a40c444db90a18eb66506d9fa5d025bf3, #598, CI 45394058836 e governança 45394058967. A issue #599 é a autoridade do estado de execução. Branch feat/nfcore-economy-t12-comparison.

## Primeiro incremento (não certificado)
Motor tax/annual_regime_comparison.py, schema nfcore.annual-regime-comparison/v1. Reutiliza T07 assess_segregated e T11 simulate sem alterar alíquotas. Compara quatro trimestres de 2026 e 12 competências; exige 2025 completo para RBT12 e Fator R, receita ordinária doméstica, empresa estabelecida, apuração por competência, comércio/serviços gerais, elegibilidade revisada e janela abaixo do sublimite. O modelo de sensibilidade exige três cenários revisados explícitos, mantendo receita, atividade, UF e histórico anterior; não inventa custos, créditos nem novos fatos. PIS/Cofins ordinários com créditos negativos não alocados bloqueiam. Tributos fora do DAS e impacto líquido adicional RTC exigem evidência revisada; saldo bruto RTC é mostrado separadamente. Ranking de carga tributária não é autorização de opção nem previsão de lucro ou fluxo de caixa. Valores de outros tributos e compensações são entradas revisadas, não calculadas pelo motor inicial. Cenário de folha deve reconciliar resultado contábil e contribuições por regime com a revisão. Não há dedução automática de créditos ou de benefícios territoriais.

## Segundo incremento (não certificado)

Importador de homologação scripts/nfcore_annual_regime_comparison_import.py BUNDLE --tenant TENANT --unit UNIT. Bundle {tenant, unit, issuer_cnpj, version, facts}; ambiente development/test/staging, banco já provisionado e papel T01, limite de 1 MiB. Validação de emitente, UF e perfil mensal, digest e versão imutável, sem DDL. API POST /v1/portal/cognitive/economy/annual-regime-comparison usa apenas unidade, ambiente e competence=2026-01-01, sessão, audit.read, CSRF, escopo autorizado, T01 read-only; devolve base insuficiente sem snapshot. A tela Reforma Tributária apresenta ranking e variações de margem/folha, sem JSON bruto. Dados são cenários anuais revisados, não afirmação de que as 12 competências de 2026 já transcorreram. Restrição adicional: não aceitar outras receitas tributáveis nem compensações de prejuízo sem conciliação anual. A base PIS/Cofins revisada pode ser inferior à receita (exclusões); não pode excedê-la no recorte. Nenhum ajuste de regra fiscal nova.

## Terceiro incremento (não certificado)

Fixture sintética compartilhada tests/tax/fixtures/t12_reviewed_annual_example.json; teste PostgreSQL exercita importação, replay, conflito de versão, versão sucessora, preservação histórica e quatro eixos RLS. Referência aritmética: Anexo V, primeira faixa, RBT12 R$ 120 mil, folha qualificada 20%, receita mensal R$ 10 mil. A partição T07 arredonda PIS e CPP por tributo (R$ 1.550,01/mês de DAS), total R$ 18.600,12; Presumido R$ 20.796,00 e Real trimestral R$ 21.180,00 incluem os tributos externos sintéticos. Variação do resultado Real em R$ 3 mil gera R$ 720 de IRPJ/CSLL. Nenhuma dessas entradas sintéticas é orientação de alíquota local ou homologação contábil. Exigir abertura comprovada até janeiro/2025, sem majoração das bases de presunção ou compensação de perdas neste recorte inicial; novas células precisam de reconciliação anual. Expor margem contábil e razão de folha qualificada em pontos-base, sensibilidade do ranking e resultados com precisão inteira.

## Pendências internas (T12 não entregue)
- Executar e revisar os testes focais; verificar Ruff/Mypy e CI integral do HEAD.
- Revisar escopo fiscal, reconciliação do resultado e dos créditos/ajustes anuais, base temporal e tratamento explícito de elegibilidade. Conferir números com referência contábil independente.
- Certificar importação T01, bind de referências e autorização/CSRF; testes RLS, replay, RBAC, PostgreSQL, E2E e regressão adicionados ou ampliados, ainda sem execução comprovada.
- Revisão independente, autorização específica de merge, CI pós-merge e atualização do cronograma; T13 permanece bloqueada.
- Expansão de outros escopos/competências/territórios no backlog, sem fabricar cobertura. Uso real e validação contábil externa não comprovados.

Não alterar main/production, sem deploy, transmissão, pagamento ou mudança de regime. Testes sintéticos ainda não executados no momento deste registro.
