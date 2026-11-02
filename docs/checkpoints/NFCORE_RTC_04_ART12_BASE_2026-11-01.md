# RTC-04 — Composição não emitível da base geral do art. 12 da LC 214/2025

**Data:** 2026-11-01; **CURRENT de partida:** `main@6a6a4a1e5fb15fa58e4b64815e6b378afbe4b597`. PR #308 MERGED, governança pós-merge #41374080048 SUCCESS; CI pós-merge #41374080105 em andamento na auditoria inicial desta entrega. `production@d7cf5e4d58cce8ab43105b17e13b2237edc551fb` inalterada.

## Norma e célula delimitada

Fonte primária: [LC 214/2025, texto atualizado pela Câmara dos Deputados](https://www2.camara.leg.br/legin/fed/leicom/2025/leicomplementar-214-16-janeiro-2025-796905-normaatualizada-pl.html), art. 12 caput, §§1º–5º, 7º; arts. 343, 346 e 348. O valor da operação compreende encargos e descontos condicionais (§1º), e o §2º exclui IBS/CBS, IPI, desconto incondicional, reembolso de terceiro condicionado à documentação, tributos legados durante 2026–2032 e contribuição do art. 149-A. O §4º prevê casos de valor de mercado; o §7º fixa base da devolução/cancelamento igual à original. A implementação **não** trata esses casos especiais: rejeita contextos não comprovados.

## Delta de código

- `Rtc2026Art12BasePreview` e `calculate_2026_art12_base_preview` em `src/kordena_fiscal/compliance/rtc_calculation_preview.py`, **o mesmo módulo de prévias RTC**, sem segunda regra de negócio nem API. Soma exclusões individualizadas sobre valor bruto **que comprovadamente já as contém**. Para evitar soma e subtração duplicadas, as parcelas condicionais já estão embutidas no valor integral cobrado; todos os descontos abatidos são declarados incondicionais e constam do documento fiscal. A validade dessa declaração ainda é obrigação do integrador/verificador e não foi autonomizada.
- Campos explícitos: valor integral, desconto incondicional, IPI, IBS/CBS, tributos legados 2026, contribuição de iluminação pública. Casos de reembolso por terceiro e valor de mercado são bloqueados em vez de inferidos. Não aceitar base negativa, entrada não Money, flags de confirmação diferentes do booleano `True`, ano fora de 2026, Simples, regra ausente/ambígua ou cClassTrib divergente.
- O resultado de base alimenta somente `calculate_2026_nominal_reference_preview`, preexistente, e continua **Decimal não arredondado / não emitível**. Não cria documento XML, `ReformTaxComponentSnapshot` emitível, tributo recolhível ou lançamento contábil.
- Testes sintéticos em `tests/tax/test_rule_engine.py`: base nominal R$ 1.000 menos R$ 100 desconto, R$ 20 IPI e R$ 80 tributos legados = R$ 800; CBS nominal R$ 7,20 e IBS estadual nominal R$ 0,80, **sem tratamento fiscal de arredondamento**. Negativas para base inválida, excedente, regime/ano, requisitos de evidência, ambiguidade. Testes não substituem golden files governamentais.

## Riscos e dependências para cálculo emitível

1. Declarações de que `gross_operation_value` representa o preço integral *antes* das exclusões e que descontos/tributos foram realmente embutidos não têm evidência de DF-e ligada. A API emissora não consome essa prévia. Exigir autoridade determinística de documento/itens, rastreabilidade, validação de datas, competência e cálculo por item antes de qualquer integração.
2. **Arredondamento:** NT 2025.002, versão e anexos XSD vigentes, campos (`vBC`, `pIBSUF`, `pCBS`, `vIBSUF`, `vCBS`), regras/tolerâncias diferentes por campo devem ser validados contra os bytes oficiais e golden cases. Não aplicar `ROUND_HALF_UP` ou `ROUND_HALF_EVEN` genérico ao valor fiscal por intuição. Apenas `calculate_evidenced_rtc_preview` aceita rounding pinado, ainda em contexto sintético.
3. Regimes diferenciados, combustíveis, serviços específicos, exportação/importação, devoluções, descontos/reembolsos, IS, créditos, compensação/recolhimento e mudanças normativas de 2027–2033 permanecem **fora da célula**. Não converter `art12` em autorização universal.
4. A tabela `config/rtc/official-baseline-2026-10-30.json` contém URLs, **não** bytes/hash oficiais dos códigos. Falta normalização com proveniência e verificação de CST/cClassTrib por operação.

**Classificação:** RTC-04 `IMPLEMENTED_PARTIAL` / nova entrega `IMPLEMENTED_NOT_CERTIFIED` até CI/Gov do HEAD e revisão. Merge RTC exige autorização humana específica. Sem deploy, migration, credencial real ou homologação.
