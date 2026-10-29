"""Synthetic prepared XML and provider responses confined to browser tests."""

from kordena_fiscal.archive import RetentionPolicyMetadata
from kordena_fiscal.domain import Cnpj, ElectronicInvoiceModel
from kordena_fiscal.gateway import (
    AuthorizationRequest,
    FakeFiscalGateway,
    FakeGatewayMode,
    FiscalGatewayClient,
)
from kordena_fiscal.lifecycle import FiscalDocumentState, IdempotencyKey
from kordena_fiscal.operations import FakeFiscalOperationsGateway, FiscalOperationsClient
from kordena_fiscal.runtime.provider_issuance_handler import build_provider_reconciliation_handler
from kordena_fiscal.xml import AccessKeyInput, build_access_key


def seed_and_handler(application, scope, now):
    document_id = "PREPARED-RECOVERY-a"
    retention = RetentionPolicyMetadata("synthetic-browser-only", 1)
    request = AuthorizationRequest(
        scope=scope,
        access_key=build_access_key(
            AccessKeyInput(
                state_ibge_code="35",
                issued_at=now,
                issuer_cnpj=Cnpj("12345678000195"),
                model=ElectronicInvoiceModel.NFCE,
                series=3,
                invoice_number=1,
                emission_type=1,
                numeric_code=12345678,
            )
        ),
        signed_xml=b"<synthetic-browser-test-only/>",
        idempotency_key=IdempotencyKey("e" * 64),
        request_fingerprint="f" * 64,
    )
    application.reserve_issuance(
        scope=scope,
        key=request.idempotency_key,
        request_fingerprint=request.request_fingerprint,
        document_id=document_id,
        created_at=now,
    )
    for state in (
        FiscalDocumentState.VALIDATING,
        FiscalDocumentState.READY_TO_SIGN,
        FiscalDocumentState.SIGNING,
    ):
        application.transition_lifecycle(
            document_id,
            state,
            occurred_at=now,
            reason="synthetic browser preparation",
            correlation_id=scope.correlation_id,
        )
    application.persist_prepared_authorization(
        document_id=document_id,
        request=request,
        occurred_at=now,
        retention=retention,
    )
    application.authorize_prepared_document(
        document_id=document_id,
        request=request,
        occurred_at=now,
        gateway=FiscalGatewayClient(FakeFiscalGateway(FakeGatewayMode.PENDING)),
    )
    return build_provider_reconciliation_handler(
        application,
        client=FiscalOperationsClient(FakeFiscalOperationsGateway()),
        archive_retention=retention,
    )
