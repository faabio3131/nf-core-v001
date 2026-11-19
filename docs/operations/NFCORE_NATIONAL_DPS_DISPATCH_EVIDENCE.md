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

## Integridade do despacho

A assinatura XMLDSig do DPS de saída é agora validada antes do arquivamento e HTTP, incluindo vínculo ao certificado A1 efetivamente resolvido no Vault, RSA >= 2048, digest, referência e uso de chave. O transporte de baixo nível também compara o certificado configurado com a assinatura. A releitura do DPS arquivado usa o instante local persistido pelo arquivo apenas para validade temporal do certificado desse DPS, preservando a verificação matemática. Não usa esse instante para aceitar signatário SEFIN vencido/revogado nem para simular carimbo de tempo confiável. LTV/OCSP oficial, revisão independente e CI seguem pendentes. Testes escritos sem execução.
