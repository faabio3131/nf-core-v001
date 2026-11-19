# NAT-MG-W1-00 — auditoria de componentes reais antes de ampliar a cobertura

**Reconciliado em:** 11/11/2026, referência `main@545b7606208eedf77b3fd6b852ccb82b4716f6b8`. **Estado:** auditoria de código e testes versionados, sem execução de certificado/ambiente oficial nesta revisão. Esta nota registra presença/ausência de provas, não autoriza um provedor.

## Componentes encontrados na main

| Área | Código / evidência existente | Leitura correta |
|---|---|---|
| Endpoints MG NF-e/NFC-e | `src/kordena_fiscal/control_plane/sefaz_endpoint_catalog.py`, `_sefaz_endpoint_data.py`, `mg_official_homologation_catalog.py` | Catálogo versionado de referências por operação, ambiente e modelo. **Não** configura automaticamente provider binding nem certifica transmissão. |
| NF-e 55 MG assinatura/autorização | `src/kordena_fiscal/gateway/nfe_sp_homologation.py`, testes `tests/gateway/test_mg_homologation_authorization.py` | Testes verificam escopo, alvo MG, validador XSD obrigatório, XMLDSig, consistência de resposta e recusa de redirect; utilizam material sintético e transporte controlado, não são autorização SEFAZ real. |
| Consulta/cancelamento/inutilização MG 55 | `src/kordena_fiscal/gateway/nfe_sp_operations_homologation.py`, `tests/gateway/test_mg_lifecycle_operations.py` | Há cenários de XSD/assinatura/evento, escolha de gateway com vínculo explícito, negativas por UF/modelo, reprodução e envelope. **Não** implica ciclo final certificado em runtime produtivo. |
| A1 e isolamento de provider | `src/kordena_fiscal/runtime/provider_issuance_handler.py`, `tests/control_plane/test_nat_priority_durable_provider_binding.py` | A execução exige pedido preparado e escopo coerente; metadados de prioridade não são autoridade de emissão. |
| DPS/NFS-e Nacional | `src/kordena_fiscal/issuance/nfse_dps_builder.py` e `src/kordena_fiscal/gateway/nfse_nacional_homologation.py` | Há builder com validação XSD/assinatura e transporte mTLS configurável. **Risco identificado no próprio código:** numeração nDPS derivada provisoriamente de hash, declarada ali como inadequada para virar autoridade de numeração fiscal definitiva. |
| Municipio BH e outros polos | `src/kordena_fiscal/control_plane/national_priority_inventory.py` + novos 20 municípios do inventário W1 | BH é referência de pesquisa NFS-e Nacional; demais polos W1 não têm contrato/canal do emissor certificado. Não há justificativa para 20 bindings automáticos. |
| Web e operação end-to-end | ledger nacional e composição fiscal | Existe jornada genérica preparada; **não foi encontrada evidência de certificação ponta a ponta específica para 20 municípios MG, portal e PostgreSQL/concorrência no SHA atual**. Isso é pendência de auditoria, não declaração de inexistência de código. |

## Lacunas que impedem MG-W1-INTERNAL_COMPLETE

1. **MG55:** reconciliar a implementação já existente com composição de runtime, autoridade fiscal por unidade/ambiente, consulta e recuperação de estado ambíguo; rodar testes atuais em CI no SHA do incremento.
2. **MG65:** provar operação real de código 65 distinta de 55, CSC/QR, regras de credenciamento, assinatura/XML, contingência quando aplicável, consulta e cancelamento; o catálogo 65 não prova essas funções.
3. **BH NFS-e:** validar contrato atual da cidade e canal emissor por competência/regime/contribuinte, usar builder DPS com **numeração fiscal governada**, confirmar XSD e binding explícito; resolver o risco de nDPS provisório antes de declarar saída fiscal interna.
4. **19 polos restantes:** identificar para cada município contrato oficial, canal e datas de vigência, operações, ISS/IM e suas particularidades; não inferir que todas as prefeituras usam a API nacional apenas por adesão ao ADN.
5. **Gates horizontais:** certificar testes por documento/operação, isolamento entre escritórios, empresas e unidades, PostgreSQL/concorrência, API/Web/E2E, rollback, métricas, PR/CI exatos e revisão independente quando habilitada.

## Coordenação paralela e status

- Esta branch/PR #423 trata prioridade MG, inventário de pesquisa e auditoria; **não altera handlers produtivos, provider bindings, credenciais nem banco**, para preservar o trabalho paralelo Bling/release.
- A PR #413 possui diff concorrente nos três documentos canônicos. Foi informado ali o novo sequenciamento MG W1 → DF → GO → MT → MS; resolver seu merge sem sobrescrever decisões.
- `MG-W1-00`: **AUDITED_PARTIAL** (componentes conhecidos; falta certificação por fluxo e contrato municipal).
- `MG-W1-01..07`: **PENDING** para o escopo W1; zero município promovido a `INTERNAL_COMPLETE` ou `EXTERNAL_HOMOLOGATED` apenas por este registro.
- Evidência de testes anteriores de 05/11 em `docs/NFV1_MG_LIFECYCLE_CONTINUITY_2026-11-05.md` (265 PASS locais) pertence à revisão histórica e não é automaticamente prova da presente PR/HEAD.
