# NFCore SP5 — comparação reproduzível das PRs históricas #446, #449 e #450

**Data:** 2026-11-15. **CURRENT:** `#468@f331da56a50b55157f08bffd8d7d4d38c26eaa31`. Comparação por hash de blob Git (árvores completas, não truncadas), restrita aos arquivos alterados em cada PR de origem. **Este inventário é uma auditoria de identidade de arquivo, NÃO é, isoladamente, parecer de paridade semântica.**

A classificação `IDENTICO` atesta equivalência byte a byte; `EVOLUIDO` indica que o arquivo existe na candidata mas divergiu e precisa exame por função; `AUSENTE` precisa mapeamento de substituição/obsolescência. Jamais copiar uma branch inteira para corrigir `EVOLUIDO`.

## Autoridades atuais e correspondência de função

| Função/contrato | Histórico | Autoridade CURRENT verificada | Evidência de teste ou pendência |
|---|---|---|---|
| NFS-e GET nacional | `#446/#450:gateway/nfse_nacional_query.py` | `gateway/nfse_national_query.py`, usando `nfse_national_receipt.py::validate_official_nfse_receipt` compartilhado com POST | `tests/gateway/test_national_nfse_query_receipt_archive.py`, proteção XMLDSig; falta XSD/ICP independente |
| SP4 RPS municipal, autorização por city/binding | `#446:test_sp4_municipal_canonical_provider_routing.py` | `gateway/sp4_municipal_canonical.py` + `runtime/sp4_municipal_canonical_composition.py` + `runtime/canonical_fiscal_composition.py` | `test_sp4_municipal_canonical.py` (city/tenant/source/replay), `test_sp4_municipal_canonical_composition.py` (ports/reviewer) |
| Obrigatoriedade nacional SP (MEI/Simples) | `#446:test_sp_three_city_national_issuer_preflight.py` | `gateway/municipal_sp_routing.py::classify_sp_national_nfse_eligibility` e `gateway/sp4_municipal_canonical.py::_original` | `test_municipal_sp_routing_regime_guard.py`, `test_sp4_municipal_canonical.py`, `test_sp22_federal_nfse_channel.py` |
| Inutilização SP na transição de 2026 | `#446:test_sp_inutilization_direct_guard.py` exige bloqueio geral | `gateway/pilot_sp_jurisdiction.py::require_sp_jurisdiction_operation_policy` não confunde dispensa de obrigação com proibição | `test_pilot_sp_jurisdiction.py::test_sp_inutilization_remains_available_during_official_transition`; NÃO reintroduzir teste bloqueador obsoleto |
| Preparação NFS-e sem ERP | `#449/#450:portal/app.js` e `web/native_nfse_preparation.py` | Mesma UI, API, `FiscalApplicationService` e UoW por tenant/unidade | `test_native_nfse_preparation_http.py`, `test_nfv1_nfse_preparation_recovery.py`; MF-09 NF-e/NFC-e manual ainda não implementado |
| Emissor XMLDSig e séries DPS | `#449/#450:nfse_dps_builder.py` | `issuance/nfse_dps_builder.py` e `application/service.py` reserva durável v22 | `test_nfse_dps_builder.py`, `test_nfse_dps_numbering.py` |

## Inventário completo de blobs por PR

### PR #446, origem `d72ef9ff8c6a46cb01756b324b454e745e85fa68`

| Path alterado na origem | Estado na #468 | SHA de blob origem → atual |
|---|---|---|
| `docs/checkpoints/NFCORE_SP22_ACCOUNTING_PRIORITY_2026-11-12.md` | AUSENTE | `cbaa8fb1` → `—` |
| `docs/checkpoints/NFCORE_SP3_ACCOUNTING_PILOT_2026-11-13.md` | AUSENTE | `a6274b7a` → `—` |
| `docs/checkpoints/NFCORE_SP4_ENGINEERING_ACCEPTANCE_2026-11-12.md` | AUSENTE | `f18b203b` → `—` |
| `docs/coverage/NFCORE_SP22_OPERATION_READINESS_2026-11-12.json` | EVOLUIDO | `af64ae35` → `c4ab4c97` |
| `src/kordena_fiscal/control_plane/_sefaz_endpoint_data.py` | EVOLUIDO | `414bf53f` → `8259f08d` |
| `src/kordena_fiscal/gateway/barueri_official_invoice_xml.py` | IDENTICO | `298c0cb0` → `298c0cb0` |
| `src/kordena_fiscal/gateway/barueri_official_return_file.py` | EVOLUIDO | `4342e407` → `1a7bd44d` |
| `src/kordena_fiscal/gateway/barueri_pmb004_batch_builder.py` | IDENTICO | `15f89222` → `15f89222` |
| `src/kordena_fiscal/gateway/barueri_pmb004_cancellation_builder.py` | EVOLUIDO | `e4473dff` → `d5f3c079` |
| `src/kordena_fiscal/gateway/barueri_pmb004_homologation.py` | EVOLUIDO | `32c50c2d` → `34c05b76` |
| `src/kordena_fiscal/gateway/barueri_pmb004_record_builder.py` | IDENTICO | `769626ba` → `769626ba` |
| `src/kordena_fiscal/gateway/cajamar_geisweb_cancellation_builder.py` | EVOLUIDO | `83facaa3` → `3eaac784` |
| `src/kordena_fiscal/gateway/cajamar_geisweb_homologation.py` | EVOLUIDO | `41d2e69a` → `31849c8c` |
| `src/kordena_fiscal/gateway/cajamar_geisweb_invoice_interpreter.py` | EVOLUIDO | `bc459394` → `bb6c51c8` |
| `src/kordena_fiscal/gateway/cajamar_geisweb_issue_builder.py` | IDENTICO | `19a9c328` → `19a9c328` |
| `src/kordena_fiscal/gateway/cajamar_geisweb_lot_query_builder.py` | IDENTICO | `0614bf63` → `0614bf63` |
| `src/kordena_fiscal/gateway/cajamar_geisweb_request_builder.py` | IDENTICO | `7e335947` → `7e335947` |
| `src/kordena_fiscal/gateway/jundiai_giss_cancellation_builder.py` | IDENTICO | `285d3846` → `285d3846` |
| `src/kordena_fiscal/gateway/jundiai_giss_homologation.py` | IDENTICO | `8ac8dda4` → `8ac8dda4` |
| `src/kordena_fiscal/gateway/jundiai_giss_invoice_interpreter.py` | EVOLUIDO | `f3ddc15b` → `fd9d3e8f` |
| `src/kordena_fiscal/gateway/jundiai_giss_issue_builder.py` | EVOLUIDO | `8b2ba11e` → `416cabd3` |
| `src/kordena_fiscal/gateway/jundiai_giss_request_builder.py` | IDENTICO | `b6346d95` → `b6346d95` |
| `src/kordena_fiscal/gateway/jundiai_giss_rps_query_builder.py` | EVOLUIDO | `60fd10f0` → `ca98996d` |
| `src/kordena_fiscal/gateway/municipal_sp_routing.py` | EVOLUIDO | `9a460784` → `3b28e4a7` |
| `src/kordena_fiscal/gateway/nfe_sp_operations_homologation.py` | EVOLUIDO | `bfaaf3e5` → `f21f57c4` |
| `src/kordena_fiscal/gateway/nfse_nacional_event_homologation.py` | EVOLUIDO | `ece3a6ed` → `411610e2` |
| `src/kordena_fiscal/gateway/nfse_nacional_homologation.py` | EVOLUIDO | `c4f13038` → `e6b2f5eb` |
| `src/kordena_fiscal/gateway/nfse_nacional_query.py` | AUSENTE | `002248cd` → `—` |
| `src/kordena_fiscal/gateway/osasco_full_note_query_builder.py` | IDENTICO | `d89e52db` → `d89e52db` |
| `src/kordena_fiscal/gateway/osasco_rtc_cancellation_builder.py` | EVOLUIDO | `986666df` → `ee946da3` |
| `src/kordena_fiscal/gateway/osasco_rtc_homologation.py` | IDENTICO | `126a8450` → `126a8450` |
| `src/kordena_fiscal/gateway/osasco_rtc_issue_builder.py` | EVOLUIDO | `72c76c29` → `aeea0d07` |
| `src/kordena_fiscal/gateway/osasco_rtc_request_builder.py` | IDENTICO | `7a3a05e3` → `7a3a05e3` |
| `src/kordena_fiscal/gateway/pilot_sp_jurisdiction.py` | EVOLUIDO | `76a95088` → `ffc113c5` |
| `src/kordena_fiscal/gateway/sp4_municipal_canonical.py` | IDENTICO | `5c2ff19b` → `5c2ff19b` |
| `src/kordena_fiscal/issuance/nfse_dps_builder.py` | EVOLUIDO | `f25dddc2` → `d95f7ef2` |
| `src/kordena_fiscal/runtime/canonical_fiscal_composition.py` | EVOLUIDO | `4c429b35` → `e3a93d04` |
| `src/kordena_fiscal/runtime/sp4_municipal_canonical_composition.py` | EVOLUIDO | `5fa72709` → `f6a45203` |
| `src/kordena_fiscal/runtime/sp4_municipal_provider_bridges.py` | EVOLUIDO | `51958890` → `e890de93` |
| `src/kordena_fiscal/runtime/sp4_municipal_request_factories.py` | EVOLUIDO | `a177ba64` → `ea5c82da` |
| `tests/control_plane/test_sefaz_endpoint_catalog.py` | EVOLUIDO | `6a14203a` → `bc9211dc` |
| `tests/control_plane/test_sp22_operation_readiness_matrix.py` | EVOLUIDO | `886a556b` → `94b2d542` |
| `tests/gateway/test_barueri_official_invoice_xml.py` | IDENTICO | `0549bac4` → `0549bac4` |
| `tests/gateway/test_barueri_official_return_file.py` | IDENTICO | `47ded029` → `47ded029` |
| `tests/gateway/test_barueri_pmb004_batch_builder.py` | IDENTICO | `14880d0c` → `14880d0c` |
| `tests/gateway/test_barueri_pmb004_cancellation_builder.py` | EVOLUIDO | `a3adbee0` → `c5f8304c` |
| `tests/gateway/test_barueri_pmb004_homologation.py` | EVOLUIDO | `c3e88950` → `0ae52cc7` |
| `tests/gateway/test_barueri_pmb004_record_builder.py` | IDENTICO | `d101eb29` → `d101eb29` |
| `tests/gateway/test_cajamar_geisweb_cancellation_builder.py` | IDENTICO | `9cb4c2fc` → `9cb4c2fc` |
| `tests/gateway/test_cajamar_geisweb_homologation.py` | EVOLUIDO | `8ffe08ce` → `9d22c828` |
| `tests/gateway/test_cajamar_geisweb_invoice_interpreter.py` | EVOLUIDO | `59e7e17e` → `c85d7583` |
| `tests/gateway/test_cajamar_geisweb_issue_builder.py` | IDENTICO | `fd37fa6d` → `fd37fa6d` |
| `tests/gateway/test_cajamar_geisweb_lot_query_builder.py` | IDENTICO | `dadbb23d` → `dadbb23d` |
| `tests/gateway/test_cajamar_geisweb_request_builder.py` | IDENTICO | `00028b51` → `00028b51` |
| `tests/gateway/test_jundiai_giss_cancellation_builder.py` | IDENTICO | `1c701357` → `1c701357` |
| `tests/gateway/test_jundiai_giss_homologation.py` | IDENTICO | `ec65cca0` → `ec65cca0` |
| `tests/gateway/test_jundiai_giss_invoice_interpreter.py` | IDENTICO | `b100e1e5` → `b100e1e5` |
| `tests/gateway/test_jundiai_giss_issue_builder.py` | EVOLUIDO | `9ee458c9` → `b0aa260b` |
| `tests/gateway/test_jundiai_giss_request_builder.py` | IDENTICO | `1215b697` → `1215b697` |
| `tests/gateway/test_jundiai_giss_rps_query_builder.py` | EVOLUIDO | `6dd4e756` → `1112767f` |
| `tests/gateway/test_municipal_sp_routing_regime_guard.py` | IDENTICO | `5a3f2ea6` → `5a3f2ea6` |
| `tests/gateway/test_nfse_nacional_event_homologation.py` | IDENTICO | `bcb571c8` → `bcb571c8` |
| `tests/gateway/test_osasco_full_note_query_builder.py` | IDENTICO | `1b1cbb99` → `1b1cbb99` |
| `tests/gateway/test_osasco_rtc_cancellation_builder.py` | IDENTICO | `d53aacc6` → `d53aacc6` |
| `tests/gateway/test_osasco_rtc_homologation.py` | IDENTICO | `829fc0e4` → `829fc0e4` |
| `tests/gateway/test_osasco_rtc_issue_builder.py` | EVOLUIDO | `d787d4c7` → `7545d675` |
| `tests/gateway/test_osasco_rtc_request_builder.py` | IDENTICO | `43fc7770` → `43fc7770` |
| `tests/gateway/test_pilot_sp_jurisdiction.py` | EVOLUIDO | `646d28d9` → `7b6866c1` |
| `tests/gateway/test_sp22_federal_nfse_channel.py` | IDENTICO | `ddb75f74` → `ddb75f74` |
| `tests/gateway/test_sp4_municipal_canonical.py` | IDENTICO | `3bf93e96` → `3bf93e96` |
| `tests/gateway/test_sp4_national_nfse_recovery.py` | AUSENTE | `bc82b304` → `—` |
| `tests/gateway/test_sp_inutilization_direct_guard.py` | AUSENTE | `0e389738` → `—` |
| `tests/gateway/test_sp_three_city_national_issuer_preflight.py` | AUSENTE | `64afadec` → `—` |
| `tests/runtime/test_nfv1_nfse_preparation_recovery.py` | EVOLUIDO | `1c0d83df` → `c92812c7` |
| `tests/runtime/test_sp4_barueri_async_bridge.py` | IDENTICO | `7f91e1af` → `7f91e1af` |
| `tests/runtime/test_sp4_cajamar_bridge_limits.py` | IDENTICO | `2ab801b3` → `2ab801b3` |
| `tests/runtime/test_sp4_cajamar_lot_identity.py` | IDENTICO | `c73ff48c` → `c73ff48c` |
| `tests/runtime/test_sp4_jundiai_signed_rps_identity.py` | IDENTICO | `5e39570f` → `5e39570f` |
| `tests/runtime/test_sp4_municipal_canonical_composition.py` | EVOLUIDO | `eb8dcbc0` → `a22cf6e5` |
| `tests/runtime/test_sp4_municipal_canonical_provider_routing.py` | AUSENTE | `721bfd12` → `—` |
| `tests/runtime/test_sp4_municipal_request_factories.py` | IDENTICO | `a35bb641` → `a35bb641` |
| `tests/runtime/test_sp4_osasco_receipt_lifecycle.py` | IDENTICO | `b4cf46fb` → `b4cf46fb` |

### PR #449, origem `d6f8f1c37377e5dcb4077410ee035cb5b7ede0a4`

| Path alterado na origem | Estado na #468 | SHA de blob origem → atual |
|---|---|---|
| `portal/app.js` | EVOLUIDO | `729fb04f` → `fad77726` |
| `pyproject.toml` | EVOLUIDO | `c739d501` → `78929f87` |
| `src/kordena_fiscal/archive/danfse_pdf.py` | IDENTICO | `a9790819` → `a9790819` |
| `src/kordena_fiscal/archive/records.py` | IDENTICO | `eca289dd` → `eca289dd` |
| `src/kordena_fiscal/gateway/nfse_nacional_homologation.py` | EVOLUIDO | `22ad5ff7` → `e6b2f5eb` |
| `src/kordena_fiscal/issuance/__init__.py` | EVOLUIDO | `ff126776` → `afa01837` |
| `src/kordena_fiscal/issuance/nfe_nfse.py` | EVOLUIDO | `e2e7ab91` → `c01ab918` |
| `src/kordena_fiscal/issuance/nfse_archive.py` | EVOLUIDO | `f8e6a202` → `9c38904b` |
| `src/kordena_fiscal/issuance/nfse_dps_builder.py` | EVOLUIDO | `08151b90` → `d95f7ef2` |
| `src/kordena_fiscal/runtime/composition.py` | IDENTICO | `da9a5bb1` → `da9a5bb1` |
| `src/kordena_fiscal/runtime/provider_issuance_handler.py` | IDENTICO | `be28d030` → `be28d030` |
| `src/kordena_fiscal/web/fiscal_intent_recovery.py` | EVOLUIDO | `127f99ee` → `12d494b6` |
| `src/kordena_fiscal/web/native_nfse_preparation.py` | EVOLUIDO | `07f5dbf7` → `f21fe6c1` |
| `src/kordena_fiscal/web/portal_api.py` | EVOLUIDO | `aff70f2d` → `38b8b73c` |
| `src/kordena_fiscal/web/portal_runtime.py` | EVOLUIDO | `7d887b0a` → `ec000ab3` |
| `tests/archive/test_national_danfse_pdf_renderer.py` | IDENTICO | `62255d91` → `62255d91` |
| `tests/issuance/test_nfse_dps_builder.py` | EVOLUIDO | `e14be766` → `d065463d` |
| `tests/runtime/test_nfv1_nfse_dps_builder_and_preaudit_wiring.py` | EVOLUIDO | `2eeeb134` → `afc5f872` |
| `tests/runtime/test_nfv1_nfse_preparation_recovery.py` | EVOLUIDO | `580b1fab` → `c92812c7` |
| `tests/runtime/test_p02_t07_fiscal_recovery.py` | EVOLUIDO | `721532f9` → `0d43106a` |
| `tests/web/test_native_nfse_preparation_http.py` | EVOLUIDO | `2a888232` → `2d406e41` |

### PR #450, origem `64e8f582985463e9ccb0dfea5f44e6e4d904bc6b`

| Path alterado na origem | Estado na #468 | SHA de blob origem → atual |
|---|---|---|
| `docs/checkpoints/NFCORE_FISCAL_SP4_NATIVE_INTEGRATION_2026-11-12.md` | AUSENTE | `b5c1ff51` → `—` |
| `docs/checkpoints/NFCORE_SP22_ACCOUNTING_PRIORITY_2026-11-12.md` | AUSENTE | `cbaa8fb1` → `—` |
| `docs/checkpoints/NFCORE_SP3_ACCOUNTING_PILOT_2026-11-13.md` | AUSENTE | `a6274b7a` → `—` |
| `docs/checkpoints/NFCORE_SP4_ENGINEERING_ACCEPTANCE_2026-11-12.md` | AUSENTE | `63b8581e` → `—` |
| `docs/coverage/NFCORE_SP22_OPERATION_READINESS_2026-11-12.json` | EVOLUIDO | `af64ae35` → `c4ab4c97` |
| `portal/app.js` | EVOLUIDO | `729fb04f` → `fad77726` |
| `pyproject.toml` | EVOLUIDO | `c739d501` → `78929f87` |
| `src/kordena_fiscal/archive/danfse_pdf.py` | IDENTICO | `a9790819` → `a9790819` |
| `src/kordena_fiscal/archive/records.py` | IDENTICO | `eca289dd` → `eca289dd` |
| `src/kordena_fiscal/control_plane/_sefaz_endpoint_data.py` | EVOLUIDO | `414bf53f` → `8259f08d` |
| `src/kordena_fiscal/gateway/barueri_pmb004_homologation.py` | EVOLUIDO | `e096df6e` → `34c05b76` |
| `src/kordena_fiscal/gateway/cajamar_geisweb_homologation.py` | EVOLUIDO | `4d5f7a22` → `31849c8c` |
| `src/kordena_fiscal/gateway/jundiai_giss_homologation.py` | IDENTICO | `8ac8dda4` → `8ac8dda4` |
| `src/kordena_fiscal/gateway/municipal_sp_routing.py` | EVOLUIDO | `9a460784` → `3b28e4a7` |
| `src/kordena_fiscal/gateway/nfe_sp_operations_homologation.py` | EVOLUIDO | `bfaaf3e5` → `f21f57c4` |
| `src/kordena_fiscal/gateway/nfse_nacional_event_homologation.py` | EVOLUIDO | `ece3a6ed` → `411610e2` |
| `src/kordena_fiscal/gateway/nfse_nacional_homologation.py` | EVOLUIDO | `c4f13038` → `e6b2f5eb` |
| `src/kordena_fiscal/gateway/nfse_nacional_query.py` | AUSENTE | `002248cd` → `—` |
| `src/kordena_fiscal/gateway/osasco_rtc_homologation.py` | EVOLUIDO | `9b15aa09` → `126a8450` |
| `src/kordena_fiscal/gateway/pilot_sp_jurisdiction.py` | EVOLUIDO | `76a95088` → `ffc113c5` |
| `src/kordena_fiscal/gateway/sp4_municipal_canonical.py` | EVOLUIDO | `bed20444` → `5c2ff19b` |
| `src/kordena_fiscal/issuance/__init__.py` | EVOLUIDO | `ff126776` → `afa01837` |
| `src/kordena_fiscal/issuance/nfe_nfse.py` | EVOLUIDO | `e2e7ab91` → `c01ab918` |
| `src/kordena_fiscal/issuance/nfse_archive.py` | EVOLUIDO | `f8e6a202` → `9c38904b` |
| `src/kordena_fiscal/issuance/nfse_dps_builder.py` | EVOLUIDO | `f37afbad` → `d95f7ef2` |
| `src/kordena_fiscal/runtime/canonical_fiscal_composition.py` | EVOLUIDO | `4c429b35` → `e3a93d04` |
| `src/kordena_fiscal/runtime/composition.py` | IDENTICO | `da9a5bb1` → `da9a5bb1` |
| `src/kordena_fiscal/runtime/provider_issuance_handler.py` | IDENTICO | `be28d030` → `be28d030` |
| `src/kordena_fiscal/runtime/sp4_municipal_canonical_composition.py` | EVOLUIDO | `5fa72709` → `f6a45203` |
| `src/kordena_fiscal/runtime/sp4_municipal_provider_bridges.py` | EVOLUIDO | `eaff7f3a` → `e890de93` |
| `src/kordena_fiscal/web/fiscal_intent_recovery.py` | EVOLUIDO | `127f99ee` → `12d494b6` |
| `src/kordena_fiscal/web/native_nfse_preparation.py` | EVOLUIDO | `07f5dbf7` → `f21fe6c1` |
| `src/kordena_fiscal/web/portal_api.py` | EVOLUIDO | `aff70f2d` → `38b8b73c` |
| `src/kordena_fiscal/web/portal_runtime.py` | EVOLUIDO | `7d887b0a` → `ec000ab3` |
| `tests/archive/test_national_danfse_pdf_renderer.py` | IDENTICO | `62255d91` → `62255d91` |
| `tests/control_plane/test_sefaz_endpoint_catalog.py` | EVOLUIDO | `6a14203a` → `bc9211dc` |
| `tests/control_plane/test_sp22_operation_readiness_matrix.py` | EVOLUIDO | `886a556b` → `94b2d542` |
| `tests/gateway/test_barueri_pmb004_homologation.py` | EVOLUIDO | `2191566d` → `0ae52cc7` |
| `tests/gateway/test_cajamar_geisweb_homologation.py` | EVOLUIDO | `6f912318` → `9d22c828` |
| `tests/gateway/test_jundiai_giss_homologation.py` | IDENTICO | `ec65cca0` → `ec65cca0` |
| `tests/gateway/test_municipal_sp_routing_regime_guard.py` | IDENTICO | `5a3f2ea6` → `5a3f2ea6` |
| `tests/gateway/test_nfse_nacional_event_homologation.py` | IDENTICO | `bcb571c8` → `bcb571c8` |
| `tests/gateway/test_osasco_rtc_homologation.py` | EVOLUIDO | `b405fb0e` → `829fc0e4` |
| `tests/gateway/test_pilot_sp_jurisdiction.py` | EVOLUIDO | `646d28d9` → `7b6866c1` |
| `tests/gateway/test_sp22_federal_nfse_channel.py` | IDENTICO | `ddb75f74` → `ddb75f74` |
| `tests/gateway/test_sp4_municipal_canonical.py` | EVOLUIDO | `a45726ad` → `3bf93e96` |
| `tests/gateway/test_sp4_national_nfse_recovery.py` | AUSENTE | `bc82b304` → `—` |
| `tests/gateway/test_sp_inutilization_direct_guard.py` | AUSENTE | `0e389738` → `—` |
| `tests/gateway/test_sp_three_city_national_issuer_preflight.py` | AUSENTE | `64afadec` → `—` |
| `tests/issuance/test_nfse_dps_builder.py` | EVOLUIDO | `46ce0d08` → `d065463d` |
| `tests/runtime/test_nfv1_nfse_dps_builder_and_preaudit_wiring.py` | EVOLUIDO | `2eeeb134` → `afc5f872` |
| `tests/runtime/test_nfv1_nfse_preparation_recovery.py` | EVOLUIDO | `7874edf1` → `c92812c7` |
| `tests/runtime/test_p02_t07_fiscal_recovery.py` | EVOLUIDO | `721532f9` → `0d43106a` |
| `tests/runtime/test_sp4_municipal_canonical_composition.py` | EVOLUIDO | `eb8dcbc0` → `a22cf6e5` |
| `tests/runtime/test_sp4_municipal_canonical_provider_routing.py` | AUSENTE | `721bfd12` → `—` |
| `tests/web/test_native_nfse_preparation_http.py` | EVOLUIDO | `2a888232` → `2d406e41` |

## Conclusão controlada

O inventário prova a proveniência e identifica substituições, mas **não certifica EGM ou prova funcional completa** de cada `EVOLUIDO`. Para encerrar o item de reconciliação por função, o owner deve revisar os arquivos evoluídos que alteraram contratos, com testes no HEAD final; nunca substituir trabalho mais novo por código legado. Os testes de bloqueio geral SP são históricos e contradizem a política CURRENT; sua não incorporação é deliberada.
