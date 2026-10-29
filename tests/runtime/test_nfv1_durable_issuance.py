"""Real durable state and synthetic provider boundary; no external fiscal calls."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import RetentionPolicyMetadata
from kordena_fiscal.domain import Cnpj, ElectronicInvoiceModel, ExecutionScope, FiscalEnvironment
from kordena_fiscal.gateway import (
    AuthorizationRequest,
    AuthorizationResult,
    AuthorizationStatus,
    FiscalGatewayClient,
    GatewayContractError,
    GatewayProviderMetadata,
)
from kordena_fiscal.lifecycle import FiscalDocumentState, IdempotencyKey, IssuanceAttemptStatus
from kordena_fiscal.persistence import (
    PersistenceConflictError,
    PersistenceStateError,
    SqliteFiscalDatabase,
)
from kordena_fiscal.runtime.fiscal_runtime import CanonicalFiscalOperationPath
from kordena_fiscal.runtime.provider_issuance_handler import build_provider_issuance_handler
from kordena_fiscal.xml import AccessKeyInput, build_access_key

NOW = datetime(2026, 10, 26, tzinfo=UTC)


def prepared(tmp_path, model=ElectronicInvoiceModel.NFE, db=None, archive=False):
    db = db or SqliteFiscalDatabase(tmp_path / "issuance.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    scope = ExecutionScope("tenant-test", "unit-test", FiscalEnvironment.HOMOLOGATION, "corr-test")
    request = AuthorizationRequest(
        scope=scope,
        access_key=build_access_key(
            AccessKeyInput(
                state_ibge_code="35",
                issued_at=NOW,
                issuer_cnpj=Cnpj("12345678000195"),
                model=model,
                series=1,
                invoice_number=1,
                emission_type=1,
                numeric_code=12345678,
            )
        ),
        signed_xml=b"<synthetic-test-only/>",
        idempotency_key=IdempotencyKey("a" * 64),
        request_fingerprint="b" * 64,
    )
    app.reserve_issuance(
        scope=scope,
        key=request.idempotency_key,
        request_fingerprint=request.request_fingerprint,
        document_id="doc-test",
        created_at=NOW,
    )
    for state in (
        FiscalDocumentState.VALIDATING,
        FiscalDocumentState.READY_TO_SIGN,
        FiscalDocumentState.SIGNING,
        FiscalDocumentState.READY_TO_TRANSMIT,
    ):
        if archive and state is FiscalDocumentState.READY_TO_TRANSMIT:
            app.persist_prepared_authorization(
                document_id="doc-test",
                request=request,
                occurred_at=NOW,
                retention=RetentionPolicyMetadata("synthetic-test", 1),
            )
            continue
        app.transition_lifecycle(
            "doc-test",
            state,
            occurred_at=NOW,
            reason="synthetic preparation",
            correlation_id=scope.correlation_id,
        )
    return db, app, request


class Provider:
    def __init__(self, status=AuthorizationStatus.AUTHORIZED, failure=None):
        self.calls = 0
        self.status = status
        self.failure = failure

    def authorize(self, request):
        self.calls += 1
        if self.failure:
            raise self.failure
        return AuthorizationResult(
            status=self.status,
            scope=request.scope,
            access_key=request.access_key,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.request_fingerprint,
            provider=GatewayProviderMetadata("synthetic-test", "1"),
            protocol_reference="protocol-test"
            if self.status is AuthorizationStatus.AUTHORIZED
            else None,
            rejection_code="TEST" if self.status is AuthorizationStatus.REJECTED else None,
            rejection_message="Synthetic rejection"
            if self.status is AuthorizationStatus.REJECTED
            else None,
        )


@pytest.mark.parametrize("model", list(ElectronicInvoiceModel))
@pytest.mark.parametrize("status", list(AuthorizationStatus))
def test_canonical_path_persists_result_and_restart_never_resends(tmp_path, model, status):
    db, app, request = prepared(tmp_path, model)
    provider = Provider(status)
    gateway = FiscalGatewayClient(provider)
    handler = build_provider_issuance_handler(
        app, resolve_prepared=lambda s, d: request, gateway=gateway
    )
    path = CanonicalFiscalOperationPath(app, handlers={"issueFiscalDocument": handler})
    result = path.execute(
        operation_id="issueFiscalDocument",
        scope=request.scope,
        payload={"document_id": "doc-test"},
        idempotency_key=request.idempotency_key.value,
    )
    assert result["status"] == (
        "transmitting" if status is AuthorizationStatus.PENDING else status.value
    )
    assert result["recovery_required"] is (status is AuthorizationStatus.PENDING)
    restarted = FiscalApplicationService(SqliteFiscalDatabase(db.path))
    outcome = restarted.authorize_prepared_document(
        document_id="doc-test", request=request, gateway=gateway, occurred_at=NOW
    )
    assert outcome.replay
    assert provider.calls == 1
    assert outcome.lifecycle.history[-1].correlation_id == request.scope.correlation_id


@pytest.mark.parametrize(
    "failure", [TimeoutError("timeout"), GatewayContractError("invalid response")]
)
def test_unknown_result_is_persistently_blocked_after_restart(tmp_path, failure):
    db, app, request = prepared(tmp_path)
    provider = Provider(failure=failure)
    with pytest.raises(type(failure)):
        app.authorize_prepared_document(
            document_id="doc-test",
            request=request,
            gateway=FiscalGatewayClient(provider),
            occurred_at=NOW,
        )
    restarted = FiscalApplicationService(SqliteFiscalDatabase(db.path))
    result = restarted.authorize_prepared_document(
        document_id="doc-test",
        request=request,
        gateway=FiscalGatewayClient(provider),
        occurred_at=NOW,
    )
    assert result.recovery_required and result.replay
    assert provider.calls == 1


@pytest.mark.parametrize(
    "field,value",
    [("tenant_id", "other"), ("unit_id", "other"), ("environment", FiscalEnvironment.PRODUCTION)],
)
def test_scope_mismatch_never_calls_provider(tmp_path, field, value):
    db, app, request = prepared(tmp_path)
    provider = Provider()
    wrong = replace(request, scope=replace(request.scope, **{field: value}))
    with pytest.raises(PersistenceConflictError):
        app.authorize_prepared_document(
            document_id="doc-test",
            request=wrong,
            gateway=FiscalGatewayClient(provider),
            occurred_at=NOW,
        )
    assert provider.calls == 0
    with db.unit_of_work() as uow:
        assert uow.lifecycle.get("doc-test").state is FiscalDocumentState.READY_TO_TRANSMIT


@pytest.mark.parametrize("authorized", [True, False])
def test_terminal_result_cannot_finalize_another_document(tmp_path, authorized):
    db, app, request = prepared(tmp_path)
    app.reserve_issuance(
        scope=request.scope,
        key=IdempotencyKey("c" * 64),
        request_fingerprint="d" * 64,
        document_id="other-doc",
        created_at=NOW,
    )
    app.transition_lifecycle(
        "doc-test",
        FiscalDocumentState.TRANSMITTING,
        occurred_at=NOW,
        reason="synthetic dispatch",
        correlation_id="test",
    )
    common = dict(
        key=IdempotencyKey("c" * 64),
        generation=1,
        document_id="doc-test",
        occurred_at=NOW,
        correlation_id="test",
    )
    with pytest.raises(PersistenceStateError, match="does not match"):
        if authorized:
            app.finalize_authorized(**common, result_reference="protocol", reason="synthetic")
        else:
            app.finalize_rejected(**common, rejection_reason="synthetic")
    with db.unit_of_work() as uow:
        assert uow.lifecycle.get("doc-test").state is FiscalDocumentState.TRANSMITTING
        assert (
            uow.idempotency.attempts(IdempotencyKey("c" * 64))[-1].status
            is IssuanceAttemptStatus.RESERVED
        )


@pytest.mark.parametrize("status", list(AuthorizationStatus))
def test_nfse_uses_its_canonical_contract_and_durable_state(tmp_path, status):
    from kordena_fiscal.issuance import (
        NfseAuthorizationRequest,
        NfseAuthorizationResult,
        NfseGatewayClient,
    )

    db = SqliteFiscalDatabase(tmp_path / "nfse.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    from kordena_fiscal.domain import (
        BrazilianJurisdiction,
        CnaeCode,
        FiscalAddress,
        FiscalProfile,
        Money,
        SourceReference,
        StateRegistration,
        TaxRegimeCode,
    )
    from kordena_fiscal.issuance import NfseCanonicalDocument, NfseServiceLine

    scope = ExecutionScope("tenant-test", "unit-test", FiscalEnvironment.HOMOLOGATION, "corr")
    jurisdiction = BrazilianJurisdiction("SP", "3550308")
    issuer = FiscalProfile(
        profile_id="synthetic",
        scope=scope,
        cnpj=Cnpj("12345678000195"),
        legal_name="Synthetic Test",
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        state_registration=StateRegistration("SP", "123456789"),
        primary_cnae=CnaeCode("5611201"),
        address=FiscalAddress(
            street="Synthetic",
            number="1",
            district="Test",
            municipality_name="Sao Paulo",
            jurisdiction=jurisdiction,
            postal_code="01001000",
        ),
        effective_from=NOW,
    )
    request = NfseAuthorizationRequest.build(
        NfseCanonicalDocument(
            document_id="nfse-test",
            scope=scope,
            source=SourceReference("test", "1"),
            issued_at=NOW,
            competence_date=NOW.date(),
            issuer=issuer,
            service_jurisdiction=jurisdiction,
            services=(
                NfseServiceLine(
                    line_number=1,
                    municipal_service_code="0107",
                    description="Synthetic service",
                    gross_amount=Money(Decimal("10.00")),
                ),
            ),
        )
    )
    doc = request.document
    app.reserve_issuance(
        scope=doc.scope,
        key=request.idempotency_key,
        request_fingerprint=request.request_fingerprint,
        document_id=doc.document_id,
        created_at=NOW,
    )
    for state in (
        FiscalDocumentState.VALIDATING,
        FiscalDocumentState.READY_TO_SIGN,
        FiscalDocumentState.SIGNING,
        FiscalDocumentState.READY_TO_TRANSMIT,
    ):
        app.transition_lifecycle(
            doc.document_id,
            state,
            occurred_at=NOW,
            reason="synthetic preparation",
            correlation_id=doc.scope.correlation_id,
        )

    class NfseProvider:
        calls = 0

        def authorize(self, received):
            self.calls += 1
            return NfseAuthorizationResult(
                status=status,
                scope=doc.scope,
                document_id=doc.document_id,
                idempotency_key=received.idempotency_key,
                request_fingerprint=received.request_fingerprint,
                provider=GatewayProviderMetadata("synthetic-nfse", "1"),
                invoice_reference="nfse-test" if status is AuthorizationStatus.AUTHORIZED else None,
                rejection_code="TEST" if status is AuthorizationStatus.REJECTED else None,
                rejection_message="synthetic" if status is AuthorizationStatus.REJECTED else None,
            )

    provider = NfseProvider()
    gateway = NfseGatewayClient(provider)
    result = app.authorize_prepared_document(
        document_id=doc.document_id, request=request, gateway=gateway, occurred_at=NOW
    )
    replay = FiscalApplicationService(SqliteFiscalDatabase(db.path)).authorize_prepared_document(
        document_id=doc.document_id, request=request, gateway=gateway, occurred_at=NOW
    )
    assert result.recovery_required is (status is AuthorizationStatus.PENDING)
    assert replay.replay and provider.calls == 1


def test_concurrent_dispatch_calls_provider_only_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    db, app, request = prepared(tmp_path)
    provider = Provider(AuthorizationStatus.PENDING)
    barrier = Barrier(4)

    def dispatch(_):
        barrier.wait(timeout=10)
        return FiscalApplicationService(SqliteFiscalDatabase(db.path)).authorize_prepared_document(
            document_id="doc-test",
            request=request,
            gateway=FiscalGatewayClient(provider),
            occurred_at=NOW,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(dispatch, range(4)))
    assert provider.calls == 1
    assert sum(not result.replay for result in results) == 1
    assert all(result.recovery_required for result in results)


@pytest.mark.parametrize(
    "payload,key",
    [
        ({"document_id": "doc-test", "signed_xml": "injected"}, "a" * 64),
        ({"document_id": "doc-test"}, ""),
        ({}, "a" * 64),
    ],
)
def test_handler_rejects_untrusted_material_and_wrong_identity(tmp_path, payload, key):
    from kordena_fiscal.domain import FiscalValidationError

    db, app, request = prepared(tmp_path)
    provider = Provider()
    handler = build_provider_issuance_handler(
        app, resolve_prepared=lambda s, d: request, gateway=FiscalGatewayClient(provider)
    )
    with pytest.raises(FiscalValidationError):
        handler(request.scope, payload, key)
    assert provider.calls == 0


def test_postgres_concurrent_claim_and_restart(tmp_path):
    import os
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
    from uuid import uuid4

    import psycopg
    from psycopg.sql import SQL, Identifier

    from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase

    dsn = os.environ.get("NFCORE_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("NFCORE_TEST_POSTGRES_DSN required for disposable PostgreSQL test")
    schema = "issuance_test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(SQL("CREATE SCHEMA {}").format(Identifier(schema)))
    uri = urlsplit(dsn)
    query = dict(parse_qsl(uri.query))
    query["options"] = f"-c search_path={schema}"
    isolated_dsn = urlunsplit(uri._replace(query=urlencode(query, quote_via=quote)))
    database = None
    try:
        database = PostgresFiscalDatabase(isolated_dsn, min_pool_size=1, max_pool_size=8)
        db, app, request = prepared(tmp_path, db=database, archive=True)
        provider = Provider(AuthorizationStatus.PENDING)
        barrier = Barrier(4)

        def dispatch(_):
            barrier.wait(timeout=10)
            try:
                return FiscalApplicationService(database).authorize_prepared_document(
                    document_id="doc-test",
                    request=request,
                    gateway=FiscalGatewayClient(provider),
                    occurred_at=NOW,
                )
            except PersistenceConflictError:
                return None  # CAS loser does not cross the external boundary.

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(dispatch, range(4)))
        assert provider.calls == 1
        assert sum(result is not None and not result.replay for result in results) == 1
        replay = FiscalApplicationService(database).authorize_prepared_document(
            document_id="doc-test",
            request=request,
            gateway=FiscalGatewayClient(provider),
            occurred_at=NOW,
        )
        assert replay.recovery_required and replay.replay
        assert provider.calls == 1
        from kordena_fiscal.operations import FakeFiscalOperationsGateway, FiscalOperationsClient

        query_provider = FakeFiscalOperationsGateway()
        recovered = FiscalApplicationService(database).reconcile_prepared_authorization(
            scope=request.scope,
            document_id="doc-test",
            client=FiscalOperationsClient(query_provider),
            occurred_at=NOW,
            retention=RetentionPolicyMetadata("synthetic-test", 1),
        )
        assert recovered.lifecycle.state is FiscalDocumentState.AUTHORIZED
        assert recovered.attempt.status is IssuanceAttemptStatus.AUTHORIZED
        assert recovered.recovery_required is False
        assert len(query_provider.query_calls) == 1
        assert provider.calls == 1
        with database() as uow:
            artifacts = uow.archive.list_for_document(request.scope, "doc-test")
            assert len(artifacts) == 2
            assert sum(e.kind.value == "provider_response" for e in artifacts) == 1
    finally:
        if database is not None:
            database.close()
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(SQL("DROP SCHEMA {} CASCADE").format(Identifier(schema)))


def test_http_uuid_does_not_replace_domain_issuance_identity(tmp_path):
    from uuid import uuid4

    db, app, request = prepared(tmp_path)
    provider = Provider()
    handler = build_provider_issuance_handler(
        app, resolve_prepared=lambda s, d: request, gateway=FiscalGatewayClient(provider)
    )
    first = handler(request.scope, {"document_id": "doc-test"}, str(uuid4()))
    second = handler(request.scope, {"document_id": "doc-test"}, str(uuid4()))
    assert first["status"] == second["status"] == "authorized"
    assert second["replay"] and provider.calls == 1


def test_unified_wiring_issues_and_recovers_through_same_durable_authority(tmp_path):
    from kordena_fiscal.operations import FakeFiscalOperationsGateway, FiscalOperationsClient
    from kordena_fiscal.runtime.provider_operation_wiring import build_provider_operation_handlers

    _, app, request = prepared(tmp_path, archive=True)
    provider = Provider(AuthorizationStatus.PENDING)
    query = FakeFiscalOperationsGateway()
    handlers = build_provider_operation_handlers(
        FiscalOperationsClient(query),
        application=app,
        prepared_xml_gateway=FiscalGatewayClient(provider),
        archive_retention=RetentionPolicyMetadata("synthetic-unified-wiring", 1),
    )
    path = CanonicalFiscalOperationPath(app, handlers=handlers)

    def execute(operation):
        return path.execute(
            operation_id=operation,
            scope=request.scope,
            payload={"document_id": "doc-test"},
            idempotency_key="http-uuid",
        )

    assert execute("issueFiscalDocument")["recovery_required"] is True
    assert execute("reconcileFiscalOperation")["status"] == "authorized"
    assert execute("issueFiscalDocument")["replay"] is True
    assert provider.calls == 1
    assert len(query.query_calls) == 1
