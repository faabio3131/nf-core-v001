# Reviewed documentary deductions — 2026-11-19

MF-04 / REC-04. Reuse the scoped operator-installed national fiscal policy,
immutable prepared request archive, fiscal fingerprint and signed DPS builder.
A document-specific reviewed rule contains deduction_source_type,
deduction_source_id and deduction_documents in treatment. Each item contains
kind (nfe/nfse), access_key, legacy_code, nt009_code, issued_on, eligible_amount,
applied_amount, evidence_sha256 and description (nullable). Values are exact
BRL cents. The two adjustment codes must be separately reviewed, not inferred.
The existing policy review/installation authority is responsible for checking the
actual underlying fiscal document, legal deductibility, eligible value and hash.
The digest is an attestation, not proof of automatic official retrieval.

An exact source-specific rule takes precedence over a general rule for the same
selector and competence. Ambiguous specific matches fail. Duplicate fiscal
document keys in a single installed policy fail. Canonical validation rejects
missing required BH documentation, source mismatch, duplicates, future documents
and sums not matching the requested deduction. The API uses the installed
policy, never an unreviewed browser document list. Archive and fingerprint
retain the reviewed evidence, including its digest. Both February and NT009
layouts preserve individual references rather than only the aggregate amount.

Limitations: document-specific evidence must be reviewed and installed through
the existing fiscal policy mechanism; no automatic external NF-e/NFS-e lookup,
full municipal document-type catalog is certified. Within the same scope and
legal issuer, the existing durable configuration-command ledger now reserves
one fiscal evidence key for exactly one canonical issuance, including across
policy revisions; the reservation and fiscal preparation commit atomically.
No automatic reuse after rejection/cancellation or partial sharing is enabled.
Cross-unit/tenant legal ownership and external allocations require separate
review; the allocation ledger is deliberately scoped.
No municipality, fiscal production or official homologation is promoted.
Tests authored, not executed in this construction round.
