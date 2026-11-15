# PR #446 vs #468 — reconciliation of SP-22 regression coverage (2026-11-15)

This checkpoint records the source of the imported synthetic regression tests. It is not an external municipal homologation, a change to Contabo, a migration, or a release authorization.

- Source #446: `d72ef9ff8c6a46cb01756b324b454e745e85fa68`; target #468: `e8fc2928ffbc82ae2124bee6a51766d1b435129e`.
- Comparison of 82 changed paths in #446 against #468: 36 identical blobs; 32 newer/different blobs; 14 absent paths (3 historical checkpoints, 1 historical readiness JSON, 1 superseded national-query gateway, 9 tests).
- This branch carries nine relevant independent test modules (seven from PR #446 and two from PR #461) from #446 (SP-22 national eligibility, municipal canonical authorization, issuer preflight, reviewed runtime composition, SP4 provider routing, SP4 RPS request factories, and historical matrix integrity), plus the historical matrix JSON.
- The old successful-authorization test under `test_sp_three_city_national_issuer_preflight.py` used unsigned synthetic NFS-e XML. It was deliberately omitted because the #468 canonical national POST/GET receipt validator now requires XMLDSig. It must not be used as evidence that unsigned invoices are accepted. The strict receipt tests are in the canonical national gateway suites.
- `test_sp4_national_nfse_recovery.py` was NOT blindly copied: it imports `gateway.nfse_nacional_query`, an older alternate implementation absent from #468. The current signed national GET/POST pipeline must be used instead.
- `test_sp_inutilization_direct_guard.py` was NOT blindly copied: it requires outright denial of inutilization from 2026-11-01, contrary to SEFAZ-SP's express transition allowance until March 2027. Do not hardcode an unjustified denial.
- The #446 municipal readiness JSON is a **historical snapshot (2026-11-12) only**, with `is_runtime_authority=false`; it does not represent the evolving code readiness in #468 and cannot certify or de-certify a municipality by itself. The SP inutilization descriptor was corrected to reflect the explicit transition.
- Historical documentation `NFCORE_SP22_ACCOUNTING_PRIORITY_2026-11-12.md`, `NFCORE_SP3_ACCOUNTING_PILOT_2026-11-13.md` and `NFCORE_SP4_ENGINEERING_ACCEPTANCE_2026-11-12.md` remains in #446 provenance, rather than copying stale statuses into the current #468 integration.
- Preserve untouched the other agent's Santana #496, MG checkpoints #423/#440 and unrelated cognitive engine #486. Incorporation into #468 only after CI of this patch's HEAD and review, then re-certify #468 before a production-candidate sync.

Official rule: [SEFAZ-SP NF-e portal](https://portal.fazenda.sp.gov.br/servicos/nfe/Paginas/Sobre.aspx) states inutilization is dispensed from 2026-11-01 but the web services remain operational until March 2027. [Receita Federal / Resolução CGSN 191/2026](https://www.gov.br/receitafederal/pt-br/assuntos/noticias/2026/agosto/simples-nacional-nfs-e-nacional-sera-obrigatoria-para-me-e-epp-a-partir-de-1o-de-novembro-de-2026) confirms National NFS-e for ME/EPP from 2026-11-01.

## Further reconciliation of #461 and #466

Two additional SP4 regression test files absent from #468 but available in #461 are carried in this candidate: `tests/issuance/test_sp4_original_rps_durability.py` (single durable original RPS/UoW, replay/tenant isolation) and `tests/runtime/test_sp4_production_composition.py` (reviewed provider installation). These are synthetic tests, not homologation.

**Do not transplant** the legacy #466 `docs/operations/OSASCO_RTC_RUNTIME_PROVISIONING.md` verbatim. It describes `NFCORE_OSASCO_RTC_CONFIG_PATH`, but the current #468 `src/kordena_fiscal/runtime/osasco_environment.py` reads `NFCORE_OSASCO_WCF_CONFIG_PATH`, and expects `wsdl`/`schemas` or `official_xsd_package`, not the historical manifest groups. An operator runbook must be freshly derived from the current schema; the #466 document stays in the original PR's history for provenance. Its underlying Osasco codepaths are present in #468 and have evolved.
