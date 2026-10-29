import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import RetentionPolicyMetadata
from kordena_fiscal.documents import CanonicalFiscalDocument, FiscalLineSnapshot
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    ElectronicInvoiceModel,
    ExecutionScope,
    FiscalAddress,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalProductProfile,
    FiscalProfile,
    FiscalUnitCode,
    FiscalValidationError,
    Gtin,
    Money,
    NcmCode,
    ProductOrigin,
    SourceReference,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.gateway import FakeFiscalGateway, FakeGatewayMode, FiscalGatewayClient
from kordena_fiscal.issuance import (
    NfceIssuanceCommand,
    NfceIssuanceContractError,
    NfceIssuanceOrchestrator,
    NfeIssuanceCommand,
    NfeIssuanceEnvelope,
    NfeIssuanceOrchestrator,
)
from kordena_fiscal.lifecycle import (
    FiscalDocumentState,
    IdempotencyCoordinator,
    InMemoryIdempotencyStore,
    IssuanceAttemptStatus,
)
from kordena_fiscal.numbering import FiscalSequenceManager, InMemoryFiscalSequenceStore
from kordena_fiscal.persistence import (
    PersistenceConflictError,
    PersistenceStateError,
    SqliteFiscalDatabase,
)
from kordena_fiscal.runtime.observability import MetricsRegistry
from kordena_fiscal.runtime.provider_issuance_handler import build_provider_issuance_handler
from kordena_fiscal.security import (
    CertificateReference,
    FiscalSignerKind,
    FiscalSigningService,
    SignatureEnvelope,
    SigningRequest,
)
from kordena_fiscal.tax import TaxDecision, TaxRuleOutcome
from kordena_fiscal.xml import (
    AccessKeyInput,
    NfceXmlPayload,
    NfeAccessKey,
    SchemaResource,
    SchemaSet,
    XmlSchemaValidator,
    build_access_key,
)

_NAMESPACE = "http://www.portalfiscal.inf.br/nfe"
_SCHEMA = f"""<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           targetNamespace="{_NAMESPACE}"
           xmlns="{_NAMESPACE}"
           elementFormDefault="qualified">
  <xs:element name="NFe">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="infNFe">
          <xs:complexType>
            <xs:sequence>
              <xs:element name="synthetic" type="xs:string"/>
            </xs:sequence>
            <xs:attribute name="Id" type="xs:string" use="required"/>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
""".encode()


def _instant() -> datetime:
    return datetime(2026, 9, 10, 22, 0, tzinfo=UTC)


def _scope(*, unit: str = "unit-a") -> ExecutionScope:
    return ExecutionScope(
        tenant_id="tenant-a",
        unit_id=unit,
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-nfce-1",
    )


def _issuer(scope: ExecutionScope) -> FiscalProfile:
    return FiscalProfile(
        profile_id="issuer-1",
        scope=scope,
        cnpj=Cnpj("12.345.678/0001-95"),
        legal_name="Empresa Fiscal Sintetica Ltda",
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        state_registration=StateRegistration("SP", "123456789"),
        primary_cnae=CnaeCode("5611-2/01"),
        address=FiscalAddress(
            street="Rua Sintetica",
            number="100",
            district="Centro",
            municipality_name="Sao Paulo",
            jurisdiction=BrazilianJurisdiction("SP", "3550308"),
            postal_code="01001000",
        ),
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _product(scope: ExecutionScope) -> FiscalProductProfile:
    return FiscalProductProfile(
        profile_id="product-profile-1",
        product_id="product-1",
        scope=scope,
        commercial_code="SKU-001",
        description="Produto fiscal sintetico",
        ncm=NcmCode("21069090"),
        commercial_unit=FiscalUnitCode("UN"),
        taxable_unit=FiscalUnitCode("UN"),
        origin=ProductOrigin.NATIONAL,
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        gtin=Gtin("SEM GTIN"),
    )


def _tax_decision() -> TaxDecision:
    return TaxDecision(
        rule_id="rule-synthetic-1",
        rule_version=1,
        source_normative="NORMA-SINTETICA",
        outcome=TaxRuleOutcome(
            cfop="5102",
            icms_code="102",
            pis_cst="49",
            cofins_cst="49",
            ibs_cbs_classification_code="000001",
        ),
        rank=(1, 1, 1),
    )


def _document(**overrides: object) -> CanonicalFiscalDocument:
    scope = _scope()
    values: dict[str, object] = {
        "document_id": "doc-nfce-1",
        "scope": scope,
        "source": SourceReference("sale", "sale-100"),
        "document_kind": FiscalDocumentKind.NFCE,
        "issued_at": _instant(),
        "issuer": _issuer(scope),
        "items": (
            FiscalLineSnapshot(
                line_number=1,
                product=_product(scope),
                quantity=Decimal("1.000"),
                unit_price=Money(Decimal("10.00")),
                gross_amount=Money(Decimal("10.00")),
                tax_decision=_tax_decision(),
            ),
        ),
    }
    values.update(overrides)
    return CanonicalFiscalDocument(**values)  # type: ignore[arg-type]


def _certificate(scope: ExecutionScope | None = None) -> CertificateReference:
    target = scope or _scope()
    return CertificateReference(
        tenant_id=target.tenant_id,
        unit_id=target.unit_id,
        reference_id="vault://synthetic/certificate-1",
        signer_kind=FiscalSignerKind.A1_PFX,
        not_before=_instant() - timedelta(days=30),
        expires_at=_instant() + timedelta(days=300),
        subject_identifier="synthetic-certificate",
    )


class _FixedNumericCodeProvider:
    def __init__(self, code: int = 12345678) -> None:
        self.code = code
        self.calls = 0

    def code_for(self, document, attempt, number) -> int:  # type: ignore[no-untyped-def]
        del document, attempt, number
        self.calls += 1
        return self.code


class _SyntheticXmlBuilder:
    def build(
        self,
        document: CanonicalFiscalDocument,
        access_key: NfeAccessKey,
    ) -> NfceXmlPayload:
        del document
        xml = (
            f'<NFe xmlns="{_NAMESPACE}"><infNFe Id="NFe{access_key.value}">'
            "<synthetic>ok</synthetic></infNFe></NFe>"
        ).encode()
        return NfceXmlPayload(access_key=access_key, xml=xml)


class _FakeSigner:
    def sign(self, request: SigningRequest) -> SignatureEnvelope:
        return SignatureEnvelope(
            certificate_reference_id=request.certificate.reference_id,
            signer_kind=request.certificate.signer_kind,
            algorithm=request.algorithm,
            signature_value=hashlib.sha256(b"signature:" + request.payload).digest(),
            payload_sha256=request.payload_sha256,
            signed_at=request.signing_time,
        )


class _SyntheticSignedXmlAssembler:
    def assemble(
        self,
        payload: NfceXmlPayload,
        signature: SignatureEnvelope,
    ) -> bytes:
        marker = (
            '<Signature xmlns="urn:kordena:synthetic">'
            f"{signature.signature_value.hex()}"
            "</Signature></NFe>"
        )
        return payload.xml.replace(b"</NFe>", marker.encode())


class _UnsafePassthroughAssembler:
    def assemble(
        self,
        payload: NfceXmlPayload,
        signature: SignatureEnvelope,
    ) -> bytes:
        del signature
        return payload.xml


def _validator() -> XmlSchemaValidator:
    resource = SchemaResource.from_bytes("synthetic-nfce.xsd", _SCHEMA)
    return XmlSchemaValidator(
        SchemaSet(
            version="synthetic-fisc-12-v1",
            root_schema=resource.name,
            resources=(resource,),
            source_uri="https://example.invalid/fisc-12-synthetic-schema",
        )
    )


def _system(
    mode: FakeGatewayMode,
    *,
    assembler=None,  # type: ignore[no-untyped-def]
    metrics: MetricsRegistry | None = None,
    application: FiscalApplicationService | None = None,
    family: FiscalDocumentKind = FiscalDocumentKind.NFCE,
):
    idempotency_store = InMemoryIdempotencyStore()
    numbering_store = InMemoryFiscalSequenceStore()
    numbering = FiscalSequenceManager(numbering_store)
    gateway_adapter = FakeFiscalGateway(mode)
    numeric_code_provider = _FixedNumericCodeProvider()
    orchestrator_type = (
        NfeIssuanceOrchestrator if family is FiscalDocumentKind.NFE else NfceIssuanceOrchestrator
    )
    orchestrator = orchestrator_type(
        idempotency=IdempotencyCoordinator(idempotency_store) if application is None else None,
        numbering=numbering if application is None else None,
        application=application,
        archive_retention=RetentionPolicyMetadata("synthetic-test", 1) if application else None,
        numeric_code_provider=numeric_code_provider,
        xml_builder=_SyntheticXmlBuilder(),
        xml_validator=_validator(),
        signing=FiscalSigningService(_FakeSigner()),
        signed_xml_assembler=assembler or _SyntheticSignedXmlAssembler(),
        gateway=FiscalGatewayClient(gateway_adapter),
        metrics=metrics,
    )
    return orchestrator, gateway_adapter, numbering, numeric_code_provider


def _command(document: CanonicalFiscalDocument | None = None) -> NfceIssuanceCommand:
    target = document or _document()
    return NfceIssuanceCommand(
        document=target,
        series=3,
        certificate=_certificate(target.scope),
        signing_algorithm="synthetic-signature-v1",
    )


def test_authorized_nfce_composes_all_previous_boundaries_once() -> None:
    orchestrator, gateway, numbering, numeric_codes = _system(FakeGatewayMode.AUTHORIZE)
    document = _document()

    result = orchestrator.issue(_command(document))

    assert result.replay is False
    assert result.number_reservation is not None
    assert result.number_reservation.number == 1
    assert result.access_key is not None
    assert result.access_key.model is ElectronicInvoiceModel.NFCE
    assert result.access_key.series == 3
    assert result.access_key.invoice_number == 1
    assert result.access_key.value.startswith("35260912345678000195")
    assert result.attempt.status is IssuanceAttemptStatus.AUTHORIZED
    assert result.attempt.result_reference == "SYNTHETIC-PROTOCOL-1"
    assert result.lifecycle is not None
    assert result.lifecycle.state is FiscalDocumentState.AUTHORIZED
    assert result.lifecycle.version == 6
    assert len(gateway.calls) == 1
    assert numeric_codes.calls == 1
    assert numbering.last_reserved(
        document.scope,
        model=ElectronicInvoiceModel.NFCE,
        series=3,
    ) == 1


def test_rejected_nfce_closes_attempt_and_lifecycle_as_rejected() -> None:
    orchestrator, gateway, _, _ = _system(FakeGatewayMode.REJECT)

    result = orchestrator.issue(_command())

    assert result.attempt.status is IssuanceAttemptStatus.REJECTED
    assert result.attempt.rejection_reason == (
        "SYNTHETIC-REJECTION: synthetic rejection for contract test"
    )
    assert result.lifecycle is not None
    assert result.lifecycle.state is FiscalDocumentState.REJECTED
    assert result.authorization is not None
    assert result.authorization.rejection_code == "SYNTHETIC-REJECTION"
    assert len(gateway.calls) == 1


def test_pending_nfce_is_not_retransmitted_by_plain_retry() -> None:
    orchestrator, gateway, numbering, numeric_codes = _system(FakeGatewayMode.PENDING)
    command = _command()

    first = orchestrator.issue(command)
    replay = orchestrator.issue(command)

    assert first.attempt.status is IssuanceAttemptStatus.RESERVED
    assert first.lifecycle is not None
    assert first.lifecycle.state is FiscalDocumentState.TRANSMITTING
    assert replay.replay is True
    assert replay.attempt.status is IssuanceAttemptStatus.RESERVED
    assert replay.authorization is None
    assert len(gateway.calls) == 1
    assert numeric_codes.calls == 1
    assert numbering.last_reserved(
        command.document.scope,
        model=ElectronicInvoiceModel.NFCE,
        series=3,
    ) == 1


def test_authorized_retry_is_replay_without_new_number_or_gateway_call() -> None:
    orchestrator, gateway, numbering, _ = _system(FakeGatewayMode.AUTHORIZE)
    command = _command()

    first = orchestrator.issue(command)
    replay = orchestrator.issue(command)

    assert first.attempt.status is IssuanceAttemptStatus.AUTHORIZED
    assert replay.replay is True
    assert replay.attempt.status is IssuanceAttemptStatus.AUTHORIZED
    assert replay.attempt.result_reference == "SYNTHETIC-PROTOCOL-1"
    assert len(gateway.calls) == 1
    assert numbering.last_reserved(
        command.document.scope,
        model=ElectronicInvoiceModel.NFCE,
        series=3,
    ) == 1


def test_changed_content_after_safe_rejection_opens_new_generation_and_number() -> None:
    orchestrator, gateway, numbering, _ = _system(FakeGatewayMode.REJECT)
    first_document = _document()
    second_document = replace(first_document, document_id="doc-nfce-2", schema_version=2)

    first = orchestrator.issue(_command(first_document))
    second = orchestrator.issue(_command(second_document))

    assert first.attempt.generation == 1
    assert second.attempt.generation == 2
    assert second.replay is False
    assert second.number_reservation is not None
    assert second.number_reservation.number == 2
    assert len(gateway.calls) == 2
    assert numbering.last_reserved(
        first_document.scope,
        model=ElectronicInvoiceModel.NFCE,
        series=3,
    ) == 2


def test_unsigned_passthrough_is_blocked_before_gateway() -> None:
    orchestrator, gateway, _, _ = _system(
        FakeGatewayMode.AUTHORIZE,
        assembler=_UnsafePassthroughAssembler(),
    )

    with pytest.raises(NfceIssuanceContractError, match="unsigned payload"):
        orchestrator.issue(_command())

    assert gateway.calls == ()


def test_command_blocks_non_nfce_and_cross_scope_certificate_before_execution() -> None:
    document = replace(_document(), document_kind=FiscalDocumentKind.NFE)
    with pytest.raises(FiscalValidationError, match="only NFCE"):
        NfceIssuanceCommand(
            document=document,
            series=1,
            certificate=_certificate(document.scope),
            signing_algorithm="synthetic",
        )

    nfce_document = _document()
    with pytest.raises(Exception, match="does not belong to scope"):
        NfceIssuanceCommand(
            document=nfce_document,
            series=1,
            certificate=_certificate(_scope(unit="unit-b")),
            signing_algorithm="synthetic",
        )


def test_nfce_rejection_metric_is_safe_and_not_counted_on_replay() -> None:
    metrics = MetricsRegistry()
    orchestrator, _, _, _ = _system(FakeGatewayMode.REJECT, metrics=metrics)
    command = _command()
    result = orchestrator.issue(command)
    assert result.attempt.status is IssuanceAttemptStatus.REJECTED
    assert metrics.as_dicts() == [
        {"name": "nfcore_fiscal_authorizations_finalized_total", "value": 1.0,
         "labels": {"outcome": "rejected"}},
        {"name": "nfcore_fiscal_rejections_total", "value": 1.0,
         "labels": {"outcome": "rejected"}},
    ]


def test_nfce_gateway_exception_records_provider_error_without_changing_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics = MetricsRegistry()
    orchestrator, _, _, _ = _system(FakeGatewayMode.AUTHORIZE, metrics=metrics)

    def outage(_request: object) -> None:
        raise ConnectionError("private gateway detail")

    monkeypatch.setattr(orchestrator._gateway, "authorize", outage)
    with pytest.raises(ConnectionError, match="private gateway detail"):
        orchestrator.issue(_command())
    assert metrics.as_dicts() == [
        {"name": "nfcore_provider_errors_total", "value": 1.0,
         "labels": {"outcome": "error"}}
    ]


@pytest.mark.parametrize("mode", list(FakeGatewayMode))
def test_durable_pipeline_archives_signed_request_and_restarts_without_resend(tmp_path, mode):
    db = SqliteFiscalDatabase(tmp_path / "pipeline.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    pipeline, provider, _, numeric = _system(mode, application=app)
    command = _command()
    result = pipeline.issue(command)
    restarted = FiscalApplicationService(SqliteFiscalDatabase(db.path))
    request = restarted.load_prepared_authorization(
        command.document.scope, command.document.document_id
    )
    assert request == provider.calls[0]
    assert hashlib.sha256(request.signed_xml).hexdigest() == result.signed_xml_sha256
    handler = build_provider_issuance_handler(
        restarted,
        resolve_prepared=restarted.load_prepared_authorization,
        gateway=FiscalGatewayClient(provider),
    )
    response = handler(
        command.document.scope, {"document_id": command.document.document_id}, "http-uuid"
    )
    assert response["replay"] is True
    assert response["recovery_required"] is (mode is FakeGatewayMode.PENDING)
    retry, _, _, retry_numeric = _system(mode, application=restarted)
    assert retry.issue(command).replay is True
    assert retry_numeric.calls == 0
    assert numeric.calls == 1
    assert len(provider.calls) == 1
    with db() as uow:
        entries = uow.archive.list_for_document(
            command.document.scope, command.document.document_id
        )
        assert len(entries) == 1
        assert entries[0].kind.value == "other"
        assert uow.lifecycle.get(command.document.document_id) == result.lifecycle


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "other-tenant"),
        ("unit_id", "other-unit"),
        ("environment", FiscalEnvironment.PRODUCTION),
        ("host_namespace", "other-host"),
    ],
)
def test_prepared_archive_resolver_rejects_cross_scope(tmp_path, field, value):
    db = SqliteFiscalDatabase(tmp_path / "scope.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    pipeline, _, _, _ = _system(FakeGatewayMode.AUTHORIZE, application=app)
    command = _command()
    pipeline.issue(command)
    with pytest.raises(PersistenceConflictError, match="scope"):
        app.load_prepared_authorization(
            replace(command.document.scope, **{field: value}), command.document.document_id
        )


def test_durable_preparation_failure_never_dispatches_or_reallocates_on_retry(tmp_path):
    db = SqliteFiscalDatabase(tmp_path / "failure.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    pipeline, provider, _, numeric = _system(
        FakeGatewayMode.AUTHORIZE, application=app, assembler=_UnsafePassthroughAssembler()
    )
    command = _command()
    with pytest.raises(NfceIssuanceContractError, match="unsigned"):
        pipeline.issue(command)
    assert pipeline.issue(command).replay is True
    assert len(provider.calls) == 0
    assert numeric.calls == 1
    with db() as uow:
        assert uow.lifecycle.get(command.document.document_id).state is FiscalDocumentState.SIGNING
        assert (
            uow.archive.list_for_document(command.document.scope, command.document.document_id)
            == ()
        )
    with pytest.raises(PersistenceStateError, match="one current"):
        app.load_prepared_authorization(command.document.scope, command.document.document_id)


def test_archive_and_ready_transition_rollback_together(tmp_path, monkeypatch):
    from kordena_fiscal.persistence.sqlite_core import SqliteLifecycleRepository

    db = SqliteFiscalDatabase(tmp_path / "atomic.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    pipeline, provider, _, _ = _system(FakeGatewayMode.AUTHORIZE, application=app)
    original_save = SqliteLifecycleRepository.save

    def fail_ready(self, snapshot, *, expected_version):
        if snapshot.state is FiscalDocumentState.READY_TO_TRANSMIT:
            raise RuntimeError("synthetic commit boundary failure")
        return original_save(self, snapshot, expected_version=expected_version)

    monkeypatch.setattr(SqliteLifecycleRepository, "save", fail_ready)
    command = _command()
    with pytest.raises(RuntimeError, match="synthetic commit"):
        pipeline.issue(command)
    with db() as uow:
        assert uow.lifecycle.get(command.document.document_id).state is FiscalDocumentState.SIGNING
        assert (
            uow.archive.list_for_document(command.document.scope, command.document.document_id)
            == ()
        )
    assert not provider.calls


def test_prepared_request_survives_crash_before_dispatch(tmp_path, monkeypatch):
    db = SqliteFiscalDatabase(tmp_path / "before-dispatch.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    pipeline, provider, _, _ = _system(FakeGatewayMode.AUTHORIZE, application=app)
    command = _command()

    def crash(**kwargs):
        raise RuntimeError("synthetic process exit")

    monkeypatch.setattr(app, "authorize_prepared_document", crash)
    with pytest.raises(RuntimeError, match="synthetic process exit"):
        pipeline.issue(command)
    assert not provider.calls
    restarted = FiscalApplicationService(SqliteFiscalDatabase(db.path))
    handler = build_provider_issuance_handler(
        restarted,
        resolve_prepared=restarted.load_prepared_authorization,
        gateway=FiscalGatewayClient(provider),
    )
    response = handler(
        command.document.scope, {"document_id": command.document.document_id}, "http-uuid"
    )
    assert response["status"] == "authorized"
    assert response["replay"] is False
    assert len(provider.calls) == 1


def test_timeout_preserves_signed_request_without_automatic_retry(tmp_path):
    db = SqliteFiscalDatabase(tmp_path / "timeout.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    pipeline, provider, _, _ = _system(FakeGatewayMode.AUTHORIZE, application=app)
    command = _command()

    class TimeoutProvider:
        def authorize(self, request):
            raise TimeoutError("synthetic timeout")

    pipeline._gateway = FiscalGatewayClient(TimeoutProvider())
    with pytest.raises(TimeoutError):
        pipeline.issue(command)
    restarted = FiscalApplicationService(SqliteFiscalDatabase(db.path))
    handler = build_provider_issuance_handler(
        restarted,
        resolve_prepared=restarted.load_prepared_authorization,
        gateway=FiscalGatewayClient(provider),
    )
    response = handler(
        command.document.scope, {"document_id": command.document.document_id}, "http-uuid"
    )
    assert response["status"] == "transmitting"
    assert response["recovery_required"] is True
    assert not provider.calls


def _pending_recovery(tmp_path):
    db = SqliteFiscalDatabase(tmp_path / "recovery.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    pipeline, provider, _, _ = _system(FakeGatewayMode.PENDING, application=app)
    command = _command()
    pipeline.issue(command)
    return db, app, provider, command


@pytest.mark.parametrize("query_status", ["authorized", "pending", "not_found", "cancelled"])
def test_query_recovers_only_confirmed_authorization_and_archives_evidence(tmp_path, query_status):
    from kordena_fiscal.operations import (
        FakeFiscalOperationsGateway,
        FiscalOperationsClient,
        FiscalQueryStatus,
    )
    from kordena_fiscal.runtime.provider_issuance_handler import (
        build_provider_reconciliation_handler,
    )

    db, app, issuance, command = _pending_recovery(tmp_path)
    provider = FakeFiscalOperationsGateway(query_status=FiscalQueryStatus(query_status))
    handler = build_provider_reconciliation_handler(
        app,
        client=FiscalOperationsClient(provider),
        archive_retention=RetentionPolicyMetadata("synthetic-recovery", 1),
    )
    response = handler(
        command.document.scope, {"document_id": command.document.document_id}, "http-uuid"
    )
    authorized = query_status == "authorized"
    assert response["status"] == ("authorized" if authorized else "transmitting")
    assert response["recovery_required"] is not authorized
    assert response["query_status"] == query_status
    assert len(issuance.calls) == 1
    assert len(provider.query_calls) == 1
    with db() as uow:
        entries = uow.archive.list_for_document(
            command.document.scope, command.document.document_id
        )
        assert len(entries) == 2
        assert sum(e.kind.value == "provider_response" for e in entries) == 1
    if authorized:
        restarted = FiscalApplicationService(SqliteFiscalDatabase(db.path))
        replay = restarted.reconcile_prepared_authorization(
            scope=command.document.scope,
            document_id=command.document.document_id,
            client=FiscalOperationsClient(provider),
            occurred_at=command.document.issued_at,
            retention=RetentionPolicyMetadata("synthetic-recovery", 1),
        )
        assert replay.replay is True
        assert replay.attempt.result_reference == "SYNTHETIC-AUTH-PROTOCOL"
        assert len(provider.query_calls) == 1


@pytest.mark.parametrize("failure", ["timeout", "wrong_scope", "wrong_key"])
def test_untrusted_or_failed_query_never_finalizes_issuance(tmp_path, failure):
    from kordena_fiscal.operations import (
        FakeFiscalOperationsGateway,
        FiscalOperationsClient,
        FiscalOperationsContractError,
    )

    db, app, _, command = _pending_recovery(tmp_path)

    class InvalidQuery(FakeFiscalOperationsGateway):
        def query(self, request):
            if failure == "timeout":
                raise TimeoutError("synthetic timeout")
            result = super().query(request)
            if failure == "wrong_scope":
                return replace(result, scope=replace(request.scope, tenant_id="other-tenant"))
            # A distinct valid access key from another prepared document.
            return replace(
                result,
                access_key=build_access_key(
                    AccessKeyInput(
                        state_ibge_code="35",
                        issued_at=command.document.issued_at,
                        issuer_cnpj=command.document.issuer.cnpj,
                        model=ElectronicInvoiceModel.NFCE,
                        series=99,
                        invoice_number=2,
                        emission_type=1,
                        numeric_code=12345678,
                    )
                ),
            )

    with pytest.raises((TimeoutError, FiscalOperationsContractError)):
        app.reconcile_prepared_authorization(
            scope=command.document.scope,
            document_id=command.document.document_id,
            client=FiscalOperationsClient(InvalidQuery()),
            occurred_at=command.document.issued_at,
            retention=RetentionPolicyMetadata("synthetic-recovery", 1),
        )
    with db() as uow:
        assert (
            uow.lifecycle.get(command.document.document_id).state
            is FiscalDocumentState.TRANSMITTING
        )
        assert (
            len(uow.archive.list_for_document(command.document.scope, command.document.document_id))
            == 1
        )


def test_recovery_evidence_failure_rolls_back_authorization(tmp_path, monkeypatch):
    from kordena_fiscal.operations import FakeFiscalOperationsGateway, FiscalOperationsClient
    from kordena_fiscal.persistence.sqlite_outbox_archive import SqliteFiscalArchiveStore

    db, app, _, command = _pending_recovery(tmp_path)
    request = app.load_prepared_authorization(command.document.scope, command.document.document_id)

    def fail_append(self, entry):
        raise RuntimeError("synthetic archive failure")

    monkeypatch.setattr(SqliteFiscalArchiveStore, "append", fail_append)
    with pytest.raises(RuntimeError, match="synthetic archive"):
        app.reconcile_prepared_authorization(
            scope=command.document.scope,
            document_id=command.document.document_id,
            client=FiscalOperationsClient(FakeFiscalOperationsGateway()),
            occurred_at=command.document.issued_at,
            retention=RetentionPolicyMetadata("synthetic-recovery", 1),
        )
    with db() as uow:
        assert (
            uow.lifecycle.get(command.document.document_id).state
            is FiscalDocumentState.TRANSMITTING
        )
        assert (
            uow.idempotency.attempts(request.idempotency_key)[-1].status
            is IssuanceAttemptStatus.RESERVED
        )


@pytest.mark.parametrize("same_protocol", [True, False])
def test_recovery_does_not_overwrite_concurrent_terminal_result(tmp_path, same_protocol):
    from kordena_fiscal.operations import FakeFiscalOperationsGateway, FiscalOperationsClient

    db, app, _, command = _pending_recovery(tmp_path)
    request = app.load_prepared_authorization(command.document.scope, command.document.document_id)

    class ConcurrentQuery(FakeFiscalOperationsGateway):
        def query(self, query):
            result = super().query(query)
            app.finalize_authorized(
                key=request.idempotency_key,
                generation=1,
                document_id=command.document.document_id,
                result_reference=result.protocol_reference
                if same_protocol
                else "different-protocol",
                occurred_at=command.document.issued_at,
                reason="synthetic concurrent result",
                correlation_id=command.document.scope.correlation_id,
            )
            return result

    def recover():
        return app.reconcile_prepared_authorization(
            scope=command.document.scope,
            document_id=command.document.document_id,
            client=FiscalOperationsClient(ConcurrentQuery()),
            occurred_at=command.document.issued_at,
            retention=RetentionPolicyMetadata("synthetic-recovery", 1),
        )

    if same_protocol:
        assert recover().replay is True
    else:
        with pytest.raises(PersistenceConflictError, match="conflicts"):
            recover()
    with db() as uow:
        assert (
            len(uow.archive.list_for_document(command.document.scope, command.document.document_id))
            == 1
        )


def test_reconciliation_rejects_browser_outcome_before_provider_io(tmp_path):
    from kordena_fiscal.operations import FakeFiscalOperationsGateway, FiscalOperationsClient
    from kordena_fiscal.runtime.provider_issuance_handler import (
        build_provider_reconciliation_handler,
    )

    _, app, _, command = _pending_recovery(tmp_path)
    provider = FakeFiscalOperationsGateway()
    handler = build_provider_reconciliation_handler(
        app,
        client=FiscalOperationsClient(provider),
        archive_retention=RetentionPolicyMetadata("synthetic-recovery", 1),
    )
    with pytest.raises(FiscalValidationError, match="only a prepared"):
        handler(
            command.document.scope,
            {"document_id": command.document.document_id, "status": "authorized"},
            "http-uuid",
        )
    assert not provider.query_calls


@pytest.mark.parametrize("mode", list(FakeGatewayMode))
def test_nfe_reuses_durable_preparation_and_model55_envelope(tmp_path, mode):
    db = SqliteFiscalDatabase(tmp_path / "nfe-preparation.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    document = replace(_document(), document_kind=FiscalDocumentKind.NFE, document_id="doc-nfe-1")
    command = NfeIssuanceCommand(
        document=document,
        series=3,
        certificate=_certificate(document.scope),
        signing_algorithm="synthetic-signature-v1",
    )
    pipeline, provider, _, numeric = _system(mode, application=app, family=FiscalDocumentKind.NFE)
    purposes = []

    class RecordingSigner(_FakeSigner):
        def sign(self, request):
            purposes.append(request.purpose)
            return super().sign(request)

    pipeline._signing = FiscalSigningService(RecordingSigner())
    result = pipeline.issue(command)
    assert result.access_key.model is ElectronicInvoiceModel.NFE
    assert result.access_key.invoice_number == 1
    assert purposes == ["nfe_xml"]
    request = FiscalApplicationService(SqliteFiscalDatabase(db.path)).load_prepared_authorization(
        document.scope, document.document_id
    )
    envelope = NfeIssuanceEnvelope.build(document, result.access_key, request.signed_xml)
    assert envelope.to_gateway_request() == request == provider.calls[0]
    restarted, _, _, _ = _system(
        mode, application=FiscalApplicationService(db), family=FiscalDocumentKind.NFE
    )
    assert restarted.issue(command).replay is True
    assert numeric.calls == len(provider.calls) == 1


def test_shared_pipeline_keeps_model_numbering_separate(tmp_path):
    db = SqliteFiscalDatabase(tmp_path / "model-numbering.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    nfce, _, _, _ = _system(FakeGatewayMode.AUTHORIZE, application=app)
    nfe, _, _, _ = _system(
        FakeGatewayMode.AUTHORIZE, application=app, family=FiscalDocumentKind.NFE
    )
    nfce_result = nfce.issue(_command())
    doc = replace(_document(), document_kind=FiscalDocumentKind.NFE, document_id="doc-nfe-1")
    nfe_result = nfe.issue(
        NfeIssuanceCommand(
            document=doc,
            series=3,
            certificate=_certificate(doc.scope),
            signing_algorithm="synthetic-signature-v1",
        )
    )
    assert nfe_result.number_reservation.number == nfce_result.number_reservation.number == 1
    assert nfe_result.access_key.model is ElectronicInvoiceModel.NFE
    assert nfce_result.access_key.model is ElectronicInvoiceModel.NFCE
    assert nfe_result.attempt.key != nfce_result.attempt.key


@pytest.mark.parametrize("family", [FiscalDocumentKind.NFE, FiscalDocumentKind.NFCE])
def test_family_entry_points_reject_mismatched_command_before_effects(tmp_path, family):
    db = SqliteFiscalDatabase(tmp_path / "family.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    pipeline, provider, _, numeric = _system(
        FakeGatewayMode.AUTHORIZE, application=app, family=family
    )
    if family is FiscalDocumentKind.NFE:
        command = _command()
    else:
        doc = replace(_document(), document_kind=FiscalDocumentKind.NFE)
        command = NfeIssuanceCommand(
            document=doc,
            series=3,
            certificate=_certificate(doc.scope),
            signing_algorithm="synthetic-signature-v1",
        )
    with pytest.raises(FiscalValidationError, match="family"):
        pipeline.issue(command)
    assert not provider.calls
    assert numeric.calls == 0
    with db() as uow:
        assert uow.lifecycle.get(command.document.document_id) is None
