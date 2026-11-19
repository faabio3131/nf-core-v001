"""Atomic archive of recovered NFS-e XML in the existing canonical UoW.

Entirely synthetic: proves storage and idempotent recovery, NOT SEFIN acceptance.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from kordena_fiscal.application import FiscalApplicationService
from kordena_fiscal.archive import FiscalArchiveKind, RetentionPolicyMetadata
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    ExecutionScope,
    FiscalAddress,
    FiscalEnvironment,
    FiscalProfile,
    Money,
    SourceReference,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.gateway import AuthorizationStatus, GatewayProviderMetadata
from kordena_fiscal.issuance import (
    NfseAuthorizationRequest,
    NfseAuthorizationResult,
    NfseCanonicalDocument,
    NfseGatewayClient,
    NfseQueryClient,
    NfseServiceLine,
)
from kordena_fiscal.issuance.nfe_nfse import NfseRejectionDetail
from kordena_fiscal.lifecycle import FiscalDocumentState
from kordena_fiscal.persistence import SqliteFiscalDatabase

_NOW = datetime(2026, 11, 12, 11, 0, tzinfo=UTC)
_RETENTION = RetentionPolicyMetadata("nfcore-test-recovered-nfse", 1)
_RECEIPT = (
    b'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">'
    b'<infNFSe Id="NFSsynthetic-only"/></NFSe>'
)


def _document() -> NfseCanonicalDocument:
    scope = ExecutionScope(
        tenant_id="tenant-receipt", unit_id="unit-receipt",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-receipt", host_namespace="host-receipt",
    )
    jurisdiction = BrazilianJurisdiction("SP", "3550308")
    profile = FiscalProfile(
        profile_id="issuer-receipt",
        scope=scope,
        cnpj=Cnpj("12345678000195"),
        legal_name="Empresa Sintetica de Servicos Ltda",
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        state_registration=StateRegistration("SP", "123456789"),
        primary_cnae=CnaeCode("6201501"),
        address=FiscalAddress(
            street="Rua Sintetica", number="1", district="Centro",
            municipality_name="Sao Paulo", jurisdiction=jurisdiction,
            postal_code="01001000",
        ),
        effective_from=_NOW,
    )
    return NfseCanonicalDocument(
        document_id="nfse-recovered-receipt", scope=scope,
        source=SourceReference("service-order", "synthetic-receipt-order"),
        issued_at=_NOW, competence_date=_NOW.date(), issuer=profile,
        service_jurisdiction=jurisdiction,
        services=(NfseServiceLine(
            line_number=1, municipal_service_code="0107",
            national_taxation_code="010701",
            description="Servico sintetico de tecnologia",
            gross_amount=Money(Decimal("100.00")),
            iss_amount=Money(Decimal("3.00")),
        ),),
        service_taker_reference="synthetic-taker",
    )


def _result(
    request: NfseAuthorizationRequest, *, status: AuthorizationStatus,
) -> NfseAuthorizationResult:
    return NfseAuthorizationResult(
        status=status, scope=request.document.scope,
        document_id=request.document.document_id,
        idempotency_key=request.idempotency_key,
        request_fingerprint=request.request_fingerprint,
        provider=GatewayProviderMetadata("synthetic-receipt", "1"),
        invoice_reference=(
            "synthetic-access-key" if status is AuthorizationStatus.AUTHORIZED else None
        ),
        authorized_xml=_RECEIPT if status is AuthorizationStatus.AUTHORIZED else None,
    )


class _PendingTransport:
    calls = 0

    def authorize(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        self.calls += 1
        return _result(request, status=AuthorizationStatus.PENDING)


class _AuthorizingQuery:
    calls = 0

    def query(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        self.calls += 1
        return _result(request, status=AuthorizationStatus.AUTHORIZED)


def test_recovery_commits_xml_and_terminal_state_together_without_second_post(tmp_path) -> None:
    database = SqliteFiscalDatabase(tmp_path / "authorized-nfse-receipt.sqlite")
    database.initialize()
    app = FiscalApplicationService(database)
    document = _document()
    prepared = app.prepare_nfse_authorization(document, occurred_at=_NOW, retention=_RETENTION)
    transport = _PendingTransport()
    issued = app.authorize_prepared_document(
        document_id=document.document_id, request=prepared.request,
        gateway=NfseGatewayClient(transport), occurred_at=_NOW,
    )
    assert issued.recovery_required
    query = _AuthorizingQuery()
    recovered = app.reconcile_prepared_nfse_authorization(
        scope=document.scope, document_id=document.document_id,
        client=NfseQueryClient(query), occurred_at=_NOW, retention=_RETENTION,
    )
    assert recovered.lifecycle.state is FiscalDocumentState.AUTHORIZED
    assert transport.calls == 1 and query.calls == 1
    with database() as uow:
        entries = uow.archive.list_for_document(document.scope, document.document_id)
        official = [e for e in entries if e.kind is FiscalArchiveKind.AUTHORIZED_XML]
        assert len(official) == 1
        assert official[0].content == _RECEIPT
        assert any(e.kind is FiscalArchiveKind.PROVIDER_RESPONSE for e in entries)

    replay = app.reconcile_prepared_nfse_authorization(
        scope=document.scope, document_id=document.document_id,
        client=NfseQueryClient(query), occurred_at=_NOW, retention=_RETENTION,
    )
    assert replay.replay
    assert query.calls == 1 and transport.calls == 1


class _AuthorizedTransport:
    calls = 0

    def authorize(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        self.calls += 1
        return _result(request, status=AuthorizationStatus.AUTHORIZED)


def test_direct_issuance_archives_received_xml_in_same_finalization(tmp_path) -> None:
    database = SqliteFiscalDatabase(tmp_path / "direct-nfse-receipt.sqlite")
    database.initialize()
    app = FiscalApplicationService(database)
    document = _document()
    prepared = app.prepare_nfse_authorization(
        document, occurred_at=_NOW, retention=_RETENTION,
    )
    transport = _AuthorizedTransport()
    outcome = app.authorize_prepared_document(
        document_id=document.document_id,
        request=prepared.request, gateway=NfseGatewayClient(transport),
        occurred_at=_NOW,
    )
    assert outcome.lifecycle.state is FiscalDocumentState.AUTHORIZED
    assert not outcome.recovery_required
    assert transport.calls == 1

    with database() as uow:
        entries = uow.archive.list_for_document(document.scope, document.document_id)
        official = [e for e in entries if e.kind is FiscalArchiveKind.AUTHORIZED_XML]
        assert len(official) == 1
        assert official[0].content == _RECEIPT

    replay = app.authorize_prepared_document(
        document_id=document.document_id,
        request=prepared.request, gateway=NfseGatewayClient(transport),
        occurred_at=_NOW,
    )
    assert replay.replay
    assert transport.calls == 1


_REJECTION_RAW = "  Campo de ISS recusado: " + ("detalhamento fiscal legítimo; " * 45)


def _rejected_result(request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
    rejection = NfseRejectionDetail(
        code="XSD-ISS-001", origin="SEFIN_NACIONAL", raw_message=_REJECTION_RAW,
    )
    return NfseAuthorizationResult(
        status=AuthorizationStatus.REJECTED,
        scope=request.document.scope,
        document_id=request.document.document_id,
        idempotency_key=request.idempotency_key,
        request_fingerprint=request.request_fingerprint,
        provider=GatewayProviderMetadata("synthetic-rejection", "1"),
        rejection_code=rejection.code,
        rejection_message=rejection.raw_message.strip(),
        rejections=(rejection,),
    )


class _RejectingTransport:
    calls = 0

    def authorize(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        self.calls += 1
        return _rejected_result(request)


class _RejectingQuery:
    calls = 0

    def query(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        self.calls += 1
        return _rejected_result(request)


def _assert_exact_rejection_archived(
    database: SqliteFiscalDatabase, document: NfseCanonicalDocument,
) -> None:
    with database() as uow:
        entries = uow.archive.list_for_document(document.scope, document.document_id)
        raw = [
            x for x in entries
            if x.kind is FiscalArchiveKind.PROVIDER_RESPONSE
            and x.media_type == "application/vnd.nfcore.nfse-rejection.v1+json"
        ]
        assert len(raw) == 1
        payload = json.loads(raw[0].content)
        assert payload["status"] == "rejected"
        assert payload["rejections"] == [{
            "code": "XSD-ISS-001",
            "origin": "SEFIN_NACIONAL",
            "raw_message": _REJECTION_RAW,
        }]
        assert len(payload["rejections"][0]["raw_message"]) > 512
        assert not any(x.kind is FiscalArchiveKind.AUTHORIZED_XML for x in entries)


def test_direct_rejection_archives_exact_message_without_leaking_authorization(tmp_path) -> None:
    database = SqliteFiscalDatabase(tmp_path / "rejected-nfse-evidence.sqlite")
    database.initialize()
    app = FiscalApplicationService(database)
    document = _document()
    prepared = app.prepare_nfse_authorization(
        document, occurred_at=_NOW, retention=_RETENTION,
    )
    transport = _RejectingTransport()
    outcome = app.authorize_prepared_document(
        document_id=document.document_id, request=prepared.request,
        gateway=NfseGatewayClient(transport), occurred_at=_NOW,
    )
    assert outcome.lifecycle.state is FiscalDocumentState.REJECTED
    assert not outcome.recovery_required
    assert transport.calls == 1
    _assert_exact_rejection_archived(database, document)
    replay = app.authorize_prepared_document(
        document_id=document.document_id, request=prepared.request,
        gateway=NfseGatewayClient(transport), occurred_at=_NOW,
    )
    assert replay.replay
    assert transport.calls == 1
    _assert_exact_rejection_archived(database, document)


def test_recovery_rejection_archives_raw_evidence_without_resending_dps(tmp_path) -> None:
    database = SqliteFiscalDatabase(tmp_path / "rejected-recovery-evidence.sqlite")
    database.initialize()
    app = FiscalApplicationService(database)
    document = _document()
    prepared = app.prepare_nfse_authorization(
        document, occurred_at=_NOW, retention=_RETENTION,
    )
    first = _PendingTransport()
    ambiguous = app.authorize_prepared_document(
        document_id=document.document_id, request=prepared.request,
        gateway=NfseGatewayClient(first), occurred_at=_NOW,
    )
    assert ambiguous.recovery_required
    query = _RejectingQuery()
    result = app.reconcile_prepared_nfse_authorization(
        scope=document.scope, document_id=document.document_id,
        client=NfseQueryClient(query), occurred_at=_NOW, retention=_RETENTION,
    )
    assert result.lifecycle.state is FiscalDocumentState.REJECTED
    assert query.calls == 1 and first.calls == 1
    _assert_exact_rejection_archived(database, document)
    replay = app.reconcile_prepared_nfse_authorization(
        scope=document.scope, document_id=document.document_id,
        client=NfseQueryClient(query), occurred_at=_NOW, retention=_RETENTION,
    )
    assert replay.replay
    assert query.calls == 1 and first.calls == 1
