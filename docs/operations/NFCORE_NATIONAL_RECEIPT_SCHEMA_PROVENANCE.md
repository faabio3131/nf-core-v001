# National receipt schema reconciliation — 2026-11-19

Scope: recover the missing February NFSe root and isolate February vs NT009
receipt validation; no production activation, no change to the production
cutover gate, no new routing or bypass of receipt integrity or trust checks.

## Evidence

- Primary source catalog: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual
- February archive: nfse-esquemas_xsd-v1-01-20260209.zip. Direct ZIP retrieval
  was unavailable in this session; archive hash is **not independently verified**.
- The existing four February DPS resources were introduced in
  13db28c32cedbfe56db5c4d136c6a42cf2364a30. Their pinned hashes and the single
  TSSerieDPS derivation are preserved without modification.
- Independent February mirror:
  https://github.com/rumbleh/laravel-nfse/tree/aaf413f3aa87cca827f5c815efafb6aa07efcd25/resources/xsd/1.01
  All four shared files match the existing February resources after stripping
  trailing horizontal whitespace, normalizing line endings and final trailing
  whitespace, and applying the already pinned TSSerieDPS erratum to the
  February simple types. No other content difference was found.
- NFSe_v1.01.xsd is the exact same Git blob
  171ac2bbd9dd3b60a43c455518c8d124af70a09a in that February mirror,
  the official NT009 package already acquired on 2026-11-16, and the
  independent Simpliss municipal bundle. SHA-256:
  af0bd2d8c50acba3d9c3f3f515426eca083b3f66e3211ce8dd48a7cf101818b8.
  It is only a root wrapper importing local XMLDSig and including local complex
  types; no NT009 type definition is used for February receipts.
- February event wrapper and type blobs already present match the February
  mirror and the official NT009 bundle byte-for-byte (evento, pedRegEvento,
  tiposEventos). Their existing pinning and mirror provenance are preserved.

## Acceptance and limits

The explicit February receipt profile now uses its own preexisting types and
the verified common root. NT009 continues to use its separately pinned bundle.
Negative tests cover cross-profile rejection and unknown profiles. No
certificate trust or correlation check is removed. This is implementation
evidence, not a successful test run or external homologation. Direct ZIP
provenance comparison remains open; no claim of byte identity for an entire
February archive is made. No productive network or activation decision changes.
