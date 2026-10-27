"""Durable provider-neutral NFS-e preparation and restart recovery."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kordena_fiscal.application import FiscalApplicationService
from kordena_fiscal.archive import RetentionPolicyMetadata
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    ExecutionScope,
    FiscalAddress,
    FiscalEnvironment,
    FiscalProfile,
    FiscalValidationError,
    Money,
    SourceReference,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.gateway import AuthorizationStatus, FiscalGatewayClient, GatewayProviderMetadata
from kordena_fiscal.issuance import (
    NfseAuthorizationRequest,
    NfseAuthorizationResult,
    NfseCanonicalDocument,
    NfseGatewayClient,
    NfseQueryClient,
    NfseServiceLine,
)
from kordena_fiscal.issuance.nfse_archive import decode_prepared_nfse, encode_prepared_nfse
from kordena_fiscal.lifecycle import FiscalDocumentState
from kordena_fiscal.operations import FakeFiscalOperationsGateway, FiscalOperationsClient
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.persistence.ports import PersistenceConflictError, PersistenceStateError
from kordena_fiscal.runtime.provider_operation_wiring import build_provider_operation_handlers

NOW = datetime(2026, 10, 27, 5, 30, tzinfo=UTC)
RETENTION = RetentionPolicyMetadata("nfse-test", 1)


def nfse_document(*, scope: ExecutionScope | None = None) -> NfseCanonicalDocument:
    scope = scope or ExecutionScope(
        "tenant-a", "unit-a", FiscalEnvironment.HOMOLOGATION, "corr-a", "host-a"
    )
    jurisdiction = BrazilianJurisdiction("SP", "3550308")
    issuer = FiscalProfile(
        profile_id="issuer-a",
        scope=scope,
        cnpj=Cnpj("12345678000195"),
        legal_name="Synthetic Services Ltda",
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        state_registration=StateRegistration("SP", "123456789"),
        primary_cnae=CnaeCode("6201501"),
        address=FiscalAddress(
            street="Rua Sintetica",
            number="1",
            district="Centro",
            municipality_name="Sao Paulo",
            jurisdiction=jurisdiction,
            postal_code="01001000",
        ),
        effective_from=NOW,
    )
    return NfseCanonicalDocument(
        document_id="nfse-prepared-a",
        scope=scope,
        source=SourceReference("service-order", "order-a"),
        issued_at=NOW,
        competence_date=NOW.date(),
        issuer=issuer,
        service_jurisdiction=jurisdiction,
        services=(
            NfseServiceLine(
                line_number=1,
                municipal_service_code="0107",
                national_taxation_code="010701",
                description="Synthetic software service",
                gross_amount=Money(Decimal("125.50")),
                iss_amount=Money(Decimal("2.51")),
            ),
        ),
        service_taker_reference="taker-a",
    )


def test_nfse_codec_round_trip_revalidates_identity_and_scope() -> None:
    request = NfseAuthorizationRequest.build(nfse_document())
    recovered = decode_prepared_nfse(encode_prepared_nfse(request), scope=request.document.scope)
    assert recovered == request

    tampered = json.loads(encode_prepared_nfse(request))
    tampered["services"][0]["gross_amount"] = "999.00"
    with pytest.raises(Exception, match="invalid prepared NFS-e artifact"):
        decode_prepared_nfse(json.dumps(tampered).encode(), scope=request.document.scope)


@pytest.mark.parametrize("operation", ["issueFiscalDocument", "reconcileFiscalOperation"])
def test_unconfigured_nfse_family_is_rejected_by_read_only_preflight(tmp_path, operation):
    database = SqliteFiscalDatabase(tmp_path / "family-preflight.sqlite")
    database.initialize()
    app = FiscalApplicationService(database)
    document = nfse_document()
    app.prepare_nfse_authorization(document, occurred_at=NOW, retention=RETENTION)

    class NoDispatch:
        def authorize(self, request):
            raise AssertionError("preflight must never contact a provider")

    handlers = build_provider_operation_handlers(
        FiscalOperationsClient(FakeFiscalOperationsGateway()),
        application=app,
        prepared_xml_gateway=FiscalGatewayClient(NoDispatch()),
        archive_retention=RETENTION,
    )
    with pytest.raises(FiscalValidationError, match="not configured"):
        handlers[operation].preflight(
            document.scope, {"document_id": document.document_id}, "http-preflight"
        )
    with database() as uow:
        state = uow.lifecycle.get(document.document_id).state
        assert state is FiscalDocumentState.READY_TO_TRANSMIT


def test_nfse_preparation_is_atomic_replayable_and_recoverable_after_restart(tmp_path) -> None:
    database = SqliteFiscalDatabase(tmp_path / "nfse-preparation.sqlite")
    database.initialize()
    document = nfse_document()
    prepared = FiscalApplicationService(database).prepare_nfse_authorization(
        document, occurred_at=NOW, retention=RETENTION
    )
    assert not prepared.replay
    assert prepared.lifecycle.state is FiscalDocumentState.READY_TO_TRANSMIT

    restarted = FiscalApplicationService(SqliteFiscalDatabase(database.path))
    recovered = restarted.load_prepared_nfse_authorization(document.scope, document.document_id)
    replay = restarted.prepare_nfse_authorization(document, occurred_at=NOW, retention=RETENTION)
    assert recovered == prepared.request
    assert replay.replay and replay.request == recovered
    with database() as uow:
        artifacts = uow.archive.list_for_document(document.scope, document.document_id)
        assert len(artifacts) == 1


def test_nfse_prepared_request_never_crosses_scope(tmp_path) -> None:
    database = SqliteFiscalDatabase(tmp_path / "nfse-scope.sqlite")
    database.initialize()
    document = nfse_document()
    app = FiscalApplicationService(database)
    app.prepare_nfse_authorization(document, occurred_at=NOW, retention=RETENTION)
    other = ExecutionScope("tenant-a", "unit-b", FiscalEnvironment.HOMOLOGATION, "corr-b", "host-a")
    with pytest.raises((PersistenceConflictError, PersistenceStateError)):
        app.load_prepared_nfse_authorization(other, document.document_id)


class _NfseProvider:
    def __init__(self, status: AuthorizationStatus) -> None:
        self.status = status
        self.calls = 0

    def authorize(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        self.calls += 1
        return NfseAuthorizationResult(
            status=self.status,
            scope=request.document.scope,
            document_id=request.document.document_id,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.request_fingerprint,
            provider=GatewayProviderMetadata("synthetic-nfse", "1"),
            invoice_reference=(
                "nfse-authorized-a" if self.status is AuthorizationStatus.AUTHORIZED else None
            ),
        )


class _NfseQueryProvider:
    def __init__(self, status: AuthorizationStatus) -> None:
        self.status = status
        self.calls = 0

    def query(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        self.calls += 1
        return NfseAuthorizationResult(
            status=self.status,
            scope=request.document.scope,
            document_id=request.document.document_id,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.request_fingerprint,
            provider=GatewayProviderMetadata("synthetic-nfse-query", "1"),
            invoice_reference=(
                "nfse-recovered-a" if self.status is AuthorizationStatus.AUTHORIZED else None
            ),
            rejection_code=(
                "SYNTHETIC_REJECTION" if self.status is AuthorizationStatus.REJECTED else None
            ),
            rejection_message=(
                "Synthetic rejection" if self.status is AuthorizationStatus.REJECTED else None
            ),
        )


def test_canonical_provider_factory_dispatches_prepared_nfse_without_xml_gateway(tmp_path) -> None:
    database = SqliteFiscalDatabase(tmp_path / "nfse-dispatch.sqlite")
    database.initialize()
    document = nfse_document()
    app = FiscalApplicationService(database)
    app.prepare_nfse_authorization(document, occurred_at=NOW, retention=RETENTION)
    provider = _NfseProvider(AuthorizationStatus.PENDING)
    handlers = build_provider_operation_handlers(
        FiscalOperationsClient(FakeFiscalOperationsGateway()),
        application=app,
        prepared_nfse_gateway=NfseGatewayClient(provider),
        archive_retention=RETENTION,
    )
    payload = {
        "document_id": document.document_id,
        "unit_id": document.scope.unit_id,
        "environment": document.scope.environment.value,
    }
    first = handlers["issueFiscalDocument"](document.scope, payload, "http-a")
    second = handlers["issueFiscalDocument"](document.scope, payload, "http-b")
    assert first["recovery_required"] is True
    assert second["replay"] is True and second["recovery_required"] is True
    assert provider.calls == 1


@pytest.mark.parametrize(
    ("query_status", "expected_state"),
    [
        (AuthorizationStatus.AUTHORIZED, FiscalDocumentState.AUTHORIZED),
        (AuthorizationStatus.REJECTED, FiscalDocumentState.REJECTED),
        (AuthorizationStatus.PENDING, FiscalDocumentState.TRANSMITTING),
    ],
)
def test_nfse_uncertain_result_is_recovered_by_query_without_resend(
    tmp_path, query_status, expected_state
) -> None:
    database = SqliteFiscalDatabase(tmp_path / f"nfse-recovery-{query_status.value}.sqlite")
    database.initialize()
    document = nfse_document()
    app = FiscalApplicationService(database)
    app.prepare_nfse_authorization(document, occurred_at=NOW, retention=RETENTION)
    issuance = _NfseProvider(AuthorizationStatus.PENDING)
    query = _NfseQueryProvider(query_status)
    handlers = build_provider_operation_handlers(
        FiscalOperationsClient(FakeFiscalOperationsGateway()),
        application=app,
        prepared_nfse_gateway=NfseGatewayClient(issuance),
        prepared_nfse_query_client=NfseQueryClient(query),
        archive_retention=RETENTION,
    )
    payload = {
        "document_id": document.document_id,
        "unit_id": document.scope.unit_id,
        "environment": document.scope.environment.value,
    }
    assert handlers["issueFiscalDocument"](document.scope, payload, "http-issue")[
        "recovery_required"
    ]
    recovered = handlers["reconcileFiscalOperation"](document.scope, payload, "http-reconcile")
    assert recovered["query_status"] == query_status.value
    assert recovered["status"] == expected_state.value
    assert issuance.calls == 1 and query.calls == 1

    if query_status is not AuthorizationStatus.PENDING:
        replay = handlers["reconcileFiscalOperation"](
            document.scope, payload, "http-reconcile-replay"
        )
        assert replay["replay"] is True
        assert query.calls == 1
