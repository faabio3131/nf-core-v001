# RTC-04 B3 — Composição auditável de incidência, art. 12 e rounding candidato

**Data:** 2026-11-01; B3 construído sobre B1 (commit `16c51e6d2687b65fada846f5abb9ca880fa24d0f`) com dependências explícitas do B2 (`a15f2c0aea1193a249e97d0b0634c8219008fe92`), antes dos respectivos merges. PR empilhada: **não integrar B3 antes de B1 e B2 integrarem e passarem CI pós-merge**.

- Contrato `calculate_2026_audited_preview_bundle` usa o mesmo `TaxRuleEngine`, `TaxRuleContext`, conjunto congelado de regras e catálogo verificado para seleção e base do art. 12; exige igualdade da decisão/classificação nas duas etapas.
- Rounding sobre `vCBS` executado só depois de validação do pin da nota técnica por hash/versão/vigência. O payload de teste é **SYNTHETIC-v1**, não o XSD/NT de produção.
- Resultado `Rtc2026AuditedPreviewBundle(authoritative=False)`, com `RtcRoundedFieldCandidate(authoritative=False)`; sem valores emitíveis, XML, APIs, persistência ou side effects. Negativos para regra ampla, revisão ausente, policy corrompida, ano incorreto, iterador único.
- Referência oficial para pesquisa: https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=04BIflQt1aY%3D; A SVRS lista NT 2025.002 v1.53 publicada em 30/10/2026 (https://dfe-portal.svrs.rs.gov.br/NFe/Documentos), posterior à v1.52 de 01/10/2026; exigir PDF original v1.53/hash, diff normativo, XSD e golden cases aprovados antes de usar em documentos reais. A entrada de v1.53 ainda não prova sua implantação em cada autorizador.
- Dependências próximas: normalização oficial cClassTrib, elegibilidade factual de incidência por regime/UF/item/benefício, base fidedigna ao DF-e, precision por campo NT/XSD vigente, testes golden, IS, créditos, transição, homologação por autorizador.
- Prontidão global RTC-04: **IMPLEMENTED_PARTIAL**; pronta apenas uma cadeia interna de análise não fiscal. Segurança fail-closed, merge sujeito a CI/Gov verdes e autorização deste pacote de três blocos; produção Contabo intocada.
