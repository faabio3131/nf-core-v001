# RTC-04 — 2026: referência nominal legal IBS estadual + CBS (pré-arredondamento)

**Data:** 2026-11-01 · **Classe:** IMPLEMENTED_NOT_CERTIFIED (até CI no HEAD). Escopo restrito a referência interna, sem emissão, recolhimento ou homologação.

## CURRENT e prova

- `main@c36d363d6787ce1f90c947235c82287d057d7d3e`: #289 e #307 MERGED; CI pós-merge #41364330570 e governança #41364330597 SUCCESS.
- Arquitetura reutilizada: `TaxRuleEngine`, `TaxRuleContext`, `resolve_rule_with_verified_rtc_catalog`, `Money`, `RegulatoryBaselineError`; **não existe segundo motor**.
- Lei [LC 214/2025, texto atualizado Câmara dos Deputados](https://www2.camara.leg.br/legin/fed/leicom/2025/leicomplementar-214-16-janeiro-2025-796905-normaatualizada-pl.html), arts. **343** (IBS estadual 0,1%, 2026), **346** (CBS 0,9%, 2026), **348 III, alíneas a/b/c e §1º** (reduções, regimes específicos, exclusão Simples, dispensa condicionada de recolhimento). Texto público atualizado com LC 227/2026. Confirmação secundária: [RFB](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria-do-consumo/entenda).

## TARGET limitado

- `calculate_2026_nominal_reference_preview`: exige operação em 2026, `TaxRegimeCode.NORMAL`, `TaxRuleEngine` vencedor inequívoco e CST/cClassTrib verificados contra catálogo pinado; declarações expressas para caso normal não combustível, ausência de tratamento diferenciado/específico e base revisada. Nenhuma flag autoriza emissão nem substitui comprovação de origem.
- Aplica IBS **estadual** 0,1% e CBS 0,9% à base do cenário e retorna `Decimal` **bruto sem arredondamento**, separado da estrutura `ReformTaxComponentSnapshot` do fiscal real. Não calcula IBS municipal em 2026, IS, reduções, ajustes, recolhimento, crédito, compensação, PIS/Cofins, totalização, moeda fiscal ou XML. Não há comportamento permissivo para Simples.
- Gate de regressão: ano 2027 rejeitado, Simples rejeitado, flags de revisão ausentes ou inválidas rejeitadas, regra ausente/ambígua, classificação de versão discordante, base negativa. Cenários são sintéticos; a regra de alíquota é legal, mas a seleção da célula ainda **não é homologada**.

## Gaps para transformar em cálculo oficial

1. Confirmar artefatos normativos originais e mapeamento CST/cClassTrib real versão/hash; não confundir catálogo pinado sintético com fonte governamental.
2. Formalizar decisão de incidência para regime normal, operações específicas, NCM/NBS/destino, benefício, combustíveis e bases de cálculo; flags fornecidas pelo caller são **declarações, não prova independente**.
3. Confirmar nas NT/XSD oficiais regra de arredondamento por componente e totalização; elaborar golden cases oficiais, inclusive 0,1% estadual de 2026 versus repartição 2027+.
4. Implementar créditos, reduções, regimes específicos, compensação/recolhimento e IS em células próprias; ligar emissão somente após aceite e autorização.
5. RTC-05/06/07 continuam pendentes. Sem deploy, migration ou produção.

**Continuidade:** conferir CI/Governança no HEAD, corrigir a causa de falhas, revisar PR, obter autorização específica de merge RTC e executar pós-merge. Esta entrega não altera autoridade comercial, Web nem `production` Contabo.
