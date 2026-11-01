# RTC-04 — Microentrega: prévia Decimal ligada ao TaxRuleEngine canônico

**Data:** 2026-11-01 · **Escopo:** construção interna, sem cálculo fiscal oficial, sem emissão e sem produção.

## Current / Target

- `main@5bb3b2fbbf4d75ef5ee23c4d55393cc1ecbdc997`: PR #289 integrada, `calculate_evidenced_rtc_preview` isolada com classificação fornecida pelo caller, rate table/JSON sintéticos pinados e verificação temporal. CI pós-merge #41361422482 ainda em execução ao abrir este incremento (conferir GitHub antes de promover).
- **Target deste recorte:** composição adicional `calculate_rule_bound_rtc_preview` seleciona uma `TaxDecision` **exclusivamente** pelo `TaxRuleEngine` e `resolve_rule_with_verified_rtc_catalog` já existentes. Extrai classificação e `instant` do mesmo `TaxRuleContext`; chama a prévia `Decimal` existente e retorna decisão + snapshot, sem segunda autoridade.
- Testes sintéticos positivos e negativos: match CST/cClassTrib, ausência de regra, empate, classificação incompleta e regra vencida. Nenhum código de regime/UF, alíquota ou benefício é inferido para execução fiscal real.

## Fontes, vigência e limites

- Legislação base: [RFB, RTC legislação](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria-do-consumo/legislacao/) (LC 214/2025 e LC 227/2026, além de atos posteriores).
- [RFB: cronograma documentos atualizado 28/10/2026](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria-do-consumo/orientacoes-da-reforma-tributaria/cronograma) diferencia publicação de layout, vigência, obrigação por documento, regime e setor.
- [RFB: explicação das alíquotas de transição 2026](https://www.gov.br/fazenda/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria/perguntas-e-respostas/como-sera-a-transicao-para) cita alíquotas testes IBS 0,1% e CBS 0,9% em 2026. **Isso não autoriza usar a alíquota indistintamente para Simples, combustíveis ou cenários com incidência/benefício específicos.** A tabela técnica por versão, o fundamento legal de cada célula, a base de cálculo e os arredondamentos precisam de verificação e golden cases.
- O arquivo `config/rtc/official-baseline-2026-10-30.json` contém **links sem bytes SHA das tabelas oficiais**, portanto **nenhum cálculo oficial novo fica habilitado**. Prévia é *SYNTHETIC_ONLY* no teste; hash do payload revisado não atesta sua aderência à fonte governamental.

## Segurança, evidências e gates

- Não tocar em `FiscalApplicationService`, serializadores, `runtime/api`, UI, persistência, PostgreSQL ou Worker; não publicar taxas/política de arredondamento no código produtivo.
- A autoridade continua sendo `TaxRuleEngine` com `TaxRuleContext` escopado; ausência, empate e classificação desconforme rejeitam, sem fallback.
- Gate mínimo: Ruff, Mypy, Pytest, E2E/build/containers e CI/Governança do HEAD exato, com documentação do diff. **Esta trilha RTC não possui autorização de merge automático; aguardar autorização específica.**
- Próxima implementação RTC-04: fonte original por célula, checksum, revisão normativa, CST/cClassTrib aplicável, base/alíquota/benefício/vigência/caso golden e conexão fiscal somente após aceite. RTC-05/06/07 continuam dependentes.
