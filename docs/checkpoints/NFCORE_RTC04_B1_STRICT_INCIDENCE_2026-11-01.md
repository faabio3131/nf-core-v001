# RTC-04 B1 — Seleção contextual determinística (não emitível)

**Data:** 2026-11-01. Base: `main@97742044ba497a7ef89babfbd24e9666dac3d005`, PR #309 MERGED, CI/Gov pós-merge SUCCESS. Escopo: candidate gating, **não** prova de incidência fiscal definitiva.

- Reutiliza o `TaxRuleEngine` e `resolve_rule_with_verified_rtc_catalog` para preservar classificação por CST/cClassTrib versionada e tie-break/ausência fail-closed.
- Novo `resolve_strict_rtc_2026_incidence_candidate` exige seletores explícitos de UF, regime, documento, operação, destinatário e prefixo NCM. A regra efetiva vencedora não pode ser genérica nesses campos. Não muda o motor existente nem altera o comportamento de outros clientes.
- Testa caso positivo e nega wildcard, UF errada, empate, catálogo inválido e competência 2027. Entrada iterable congelada antes da resolução.
- Normativa: LC 214/2025 e LC 227/2026 (https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria-do-consumo/legislacao/); as classificações reais e atos XSD permanecem dependências. Uma regra com seletores explícitos **não prova que a classificação legal esteja correta**; esse verificador é apenas um gate estrutural para estudo.
- Sem API, XML, emissão, migrations, deploy, Contabo ou segunda autoridade. RTC-04 continua parcial, sem oficialidade de cálculo.

**Critérios:** CI/Governança no SHA; revisão de diff; merge autorizado pelo proprietário para próximos 3 blocos deste pedido, condicionado a gates; nenhuma ativação de cálculo fiscal autoritativo.
