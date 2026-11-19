# National DPS dispatch and historical schema evidence — 2026-11-19

The existing Application and fiscal archive now capture the exact signed DPS,
selected schema profile, canonical request fingerprint and DPS/content hashes
under its durable TRANSMITTING claim, before SEFIN POST. Archive failure
prevents HTTP; no duplicate transmitter, sequence or external operation is
introduced. The canonical runtime wires the writer and reader to the same
FiscalApplicationService. GET and archived cancellation/replacement validation
prefer the immutable dispatch record and do not rebuild it under today's
schema. Historical records predating this evidence use a separate compatibility
path: the already cryptographically verified provider-reported dhProc selects
the historical schema, then full canonical DPS correlation and current signer
trust remain mandatory. If historical content cannot be reproduced, it fails
closed. No automatic retries or blind resend are introduced.

dhProc is not an RFC 3161 timestamp and cannot validate expired/revoked
certificates at an arbitrary historical instant. This closes schema and
outgoing-content provenance, not ICP-Brasil LTV, OCSP or external
homologation. Tests added but not executed during construction.
