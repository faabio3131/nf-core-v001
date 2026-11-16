"""Atomic canonical preparation, including number allocation and signed archive.

No provider exchange occurs here. An exception rolls back number, lifecycle and
archive together; retries load the committed artifact rather than signing again.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime

from lxml import etree

from kordena_fiscal.archive import FiscalArchiveEntry, FiscalArchiveKind, RetentionPolicyMetadata
from kordena_fiscal.documents import CanonicalFiscalDocument, to_canonical_json
from kordena_fiscal.domain import ElectronicInvoiceModel, FiscalDocumentKind, FiscalValidationError
from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
from kordena_fiscal.lifecycle import (
    FiscalDocumentState,
    FiscalStateMachine,
    FiscalStateSnapshot,
    build_issuance_key,
)
from kordena_fiscal.numbering import FiscalSequenceKey, FiscalSequencePolicy
from kordena_fiscal.persistence.ports import (
    FiscalUnitOfWork,
    FiscalUnitOfWorkFactory,
    PersistenceStateError,
)
from kordena_fiscal.signing.nfe_xmldsig import (
    NfeSignatureProfile,
    sign_nfe_envi_xml,
    verify_official_nfe4_signature,
)
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.a1_preflight import validate_a1_for_issuer
from kordena_fiscal.xml import AccessKeyInput, build_access_key
from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

PREPARED_MEDIA_TYPE = "application/vnd.nfcore.prepared-xml.v1+json"


def prepare_nfe_sale(
    factory: FiscalUnitOfWorkFactory,
    document: CanonicalFiscalDocument,
    *,
    options: NfeSaleOptions,
    series: int,
    certificate: EphemeralCertificateMaterial | None,
    now: datetime,
    commit_preparation: Callable[[FiscalUnitOfWork, str], None] | None = None,
) -> str:
    """Commit a complete signed preparation, or replay its durable identity."""
    if document.document_kind not in {FiscalDocumentKind.NFE, FiscalDocumentKind.NFCE}:
        raise FiscalValidationError("sale preparation requires NF-e or NFC-e")
    model = (
        ElectronicInvoiceModel.NFCE
        if document.document_kind is FiscalDocumentKind.NFCE
        else ElectronicInvoiceModel.NFE
    )
    if type(series) is not int or not 0 <= series <= 999:
        raise FiscalValidationError("NF-e series must be between 0 and 999")
    if now.tzinfo is None or now.utcoffset() is None:
        raise FiscalValidationError("preparation instant must be timezone-aware")
    if document.issued_at > now:
        raise FiscalValidationError("document issuance cannot be in the future")
    snapshot = json.dumps(
        {
            "document": json.loads(to_canonical_json(document)),
            "options": asdict(options),
            "series": series,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    fingerprint = hashlib.sha256(snapshot).hexdigest()
    key = build_issuance_key(document)
    state_machine = FiscalStateMachine()
    with factory() as uow:
        reservation = uow.idempotency.reserve(key, fingerprint, document.document_id)
        persisted_id = reservation.attempt.document_id
        if reservation.replay:
            uow.lifecycle.assert_scope(persisted_id, document.scope)
            entries = uow.archive.list_for_document(document.scope, persisted_id)
            if not any(entry.media_type == PREPARED_MEDIA_TYPE for entry in entries):
                raise PersistenceStateError(
                    "issuance exists without an atomic preparation artifact"
                )
            if commit_preparation is not None:
                commit_preparation(uow, persisted_id)
                uow.commit()
            return persisted_id
        if certificate is None:
            raise FiscalValidationError("certificate material is not configured")
        validate_a1_for_issuer(
            certificate.pkcs12_bytes, certificate.password, issuer_cnpj=document.issuer.cnpj, at=now
        )
        number = uow.sequences.reserve_next(
            FiscalSequenceKey.from_scope(
                document.scope, model=model, series=series, issuer_cnpj=document.issuer.cnpj.value,
            ),
            FiscalSequencePolicy(),
        )
        municipality = document.issuer.address.jurisdiction.municipality_ibge_code
        if municipality is None:
            raise FiscalValidationError("issuer municipality code is required")
        access_key = build_access_key(
            AccessKeyInput(
                state_ibge_code=municipality[:2],
                issued_at=document.issued_at,
                issuer_cnpj=document.issuer.cnpj,
                model=model,
                series=series,
                invoice_number=number.number,
                emission_type=1,
                numeric_code=int(
                    hashlib.sha256((key.value + str(number.number)).encode()).hexdigest(), 16
                )
                % 100_000_000,
            )
        )
        unsigned = build_nfe_sale(document, access_key, options)
        signed = sign_nfe_envi_xml(
            unsigned, certificate, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
        )
        OfficialNfeEnvelopeValidator()(signed)
        verify_official_nfe4_signature(etree.fromstring(signed), certificate)
        lifecycle = FiscalStateSnapshot.initial(document.document_id, now)
        uow.lifecycle.add(lifecycle, scope=document.scope)
        for state in (
            FiscalDocumentState.VALIDATING,
            FiscalDocumentState.READY_TO_SIGN,
            FiscalDocumentState.SIGNING,
            FiscalDocumentState.READY_TO_TRANSMIT,
        ):
            updated = state_machine.transition(
                lifecycle,
                state,
                occurred_at=now,
                reason="canonical sale preparation",
                correlation_id=document.scope.correlation_id,
            )
            uow.lifecycle.save(updated, expected_version=lifecycle.version)
            lifecycle = updated
        prepared = json.dumps(
            {
                "access_key": access_key.value,
                "idempotency_key": key.value,
                "request_fingerprint": fingerprint,
                "signed_xml": base64.b64encode(signed).decode("ascii"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        for media_type, content in (
            ("application/vnd.nfcore.preparation-input.v1+json", snapshot),
            (PREPARED_MEDIA_TYPE, prepared),
        ):
            uow.archive.append(
                FiscalArchiveEntry.build(
                    scope=document.scope,
                    document_reference=document.document_id,
                    kind=FiscalArchiveKind.OTHER,
                    content=content,
                    media_type=media_type,
                    archived_at=now,
                    retention=RetentionPolicyMetadata("nfcore-nfe-preparation", 1),
                )
            )
        if commit_preparation is not None:
            commit_preparation(uow, document.document_id)
        uow.commit()
    return document.document_id
