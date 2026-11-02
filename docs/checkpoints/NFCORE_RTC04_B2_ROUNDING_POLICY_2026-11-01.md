# RTC-04 B2 — Política de arredondamento por campo, pinada e não emitível

**Data:** 2026-11-01. Base `main@97742044ba497a7ef89babfbd24e9666dac3d005`. Bloco B2 independente de B1, mas integração depende do merge e gates pós-merge anteriores.

- **Fonte oficial localizada:** Portal NF-e, NT 2025.002 v1.52 publicada 01/10/2026: https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=04BIflQt1aY%3D. Versão histórica v1.32 descreve precisão de `pAliqEfet` e validação por campo; **não se assume que seu conteúdo seja idêntico à v1.52**.
- **Implementação:** `calculate_pinned_rtc_field_rounding_candidate` no módulo existente. Só aceita campo fiscal explícito e política normalizada com `artifact_id`, versão, `effective_from`, `published_on`, SHA-256 e validação de byte exato via `verify_regulatory_artifact_bytes`. Não permite modo ou quantum implícitos. Distingue `ROUND_HALF_UP` de `ROUND_HALF_EVEN`; política de testes é **SYNTHETIC**, não representa revisão de NT atual.
- O resultado é `RtcRoundedFieldCandidate(authoritative=False)`, não valor fiscal emitível e nunca integrado ao serializador. Sem reinterpretação de `vBC`, `vIBSUF`, `vIBSMun`, `vCBS` ou `pAliqEfet` por heurística.
- **PENDÊNCIAS:** obter PDF original v1.52, SHA, XSD, revisão legal/validação por campo, golden cases oficiais, e aprovação humana antes de ativar qualquer arredondamento em produção.
- Sem deploy/Contabo, migration, secrets ou emissão real. CI/Gov no HEAD e merge condicionado aos gates. RTC-04 integral pendente.
