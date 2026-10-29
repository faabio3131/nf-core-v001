from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from kordena_fiscal.documents import (
    CanonicalFiscalDocument,
    FiscalLineSnapshot,
    FiscalPaymentSnapshot,
    PaymentMethodKind,
)
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
from kordena_fiscal.gateway import AuthorizationStatus, GatewayProviderMetadata
from kordena_fiscal.issuance import (
    NfeIssuanceContractError,
    NfeIssuanceEnvelope,
    NfseAuthorizationRequest,
    NfseAuthorizationResult,
    NfseCanonicalDocument,
    NfseGatewayClient,
    NfseGatewayContractError,
    NfseServiceLine,
    build_nfse_issuance_key,
    build_nfse_request_fingerprint,
)
from kordena_fiscal.tax import TaxDecision, TaxRuleOutcome
from kordena_fiscal.xml import AccessKeyInput, build_access_key


def _instant() -> datetime:
    return datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def _scope(*, correlation: str = "corr-fisc-18") -> ExecutionScope:
    return ExecutionScope(
        tenant_id="tenant-a",
        unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id=correlation,
    )


def _issuer(scope: ExecutionScope | None = None) -> FiscalProfile:
    actual_scope = scope or _scope()
    return FiscalProfile(
        profile_id="issuer-profile-1",
        scope=actual_scope,
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
        rule_id="rule-nfe-1",
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


def _nfe_document(*, kind: FiscalDocumentKind = FiscalDocumentKind.NFE) -> CanonicalFiscalDocument:
    scope = _scope()
    return CanonicalFiscalDocument(
        document_id="nfe-doc-1",
        scope=scope,
        source=SourceReference("sale", "sale-100"),
        document_kind=kind,
        issued_at=_instant(),
        issuer=_issuer(scope),
        items=(
            FiscalLineSnapshot(
                line_number=1,
                product=_product(scope),
                quantity=Decimal("1"),
                unit_price=Money(Decimal("100.00")),
                gross_amount=Money(Decimal("100.00")),
                tax_decision=_tax_decision(),
            ),
        ),
        payments=(
            FiscalPaymentSnapshot(
                method=PaymentMethodKind.PIX,
                amount=Money(Decimal("100.00")),
            ),
        ),
    )


def _access_key(model: ElectronicInvoiceModel):
    return build_access_key(
        AccessKeyInput(
            state_ibge_code="35",
            issued_at=_instant(),
            issuer_cnpj=Cnpj("12.345.678/0001-95"),
            model=model,
            series=1,
            invoice_number=123,
            emission_type=1,
            numeric_code=87654321,
        )
    )


def _service_line() -> NfseServiceLine:
    return NfseServiceLine(
        line_number=1,
        municipal_service_code="0107",
        national_taxation_code="010701",
        description="Servico sintetico de tecnologia",
        gross_amount=Money(Decimal("100.00")),
        deduction_amount=Money(Decimal("10.00")),
        iss_amount=Money(Decimal("4.50")),
        iss_withheld=False,
        rule_version=2,
        source_normative="REGRA-MUNICIPAL-SINTETICA-v2",
    )


def _nfse_document(
    *,
    document_id: str = "nfse-doc-1",
    correlation: str = "corr-fisc-18",
) -> NfseCanonicalDocument:
    scope = _scope(correlation=correlation)
    return NfseCanonicalDocument(
        document_id=document_id,
        scope=scope,
        source=SourceReference("service-order", "service-100"),
        issued_at=_instant(),
        competence_date=date(2026, 9, 11),
        issuer=_issuer(scope),
        service_jurisdiction=BrazilianJurisdiction("SP", "3550308"),
        services=(_service_line(),),
        service_taker_reference="customer-ref-synthetic",
    )


def _provider() -> GatewayProviderMetadata:
    return GatewayProviderMetadata(
        provider_name="synthetic-nfse-adapter",
        adapter_version="1.0",
    )


def test_nfe_envelope_accepts_model_55_and_builds_existing_gateway_request() -> None:
    document = _nfe_document()
    envelope = NfeIssuanceEnvelope.build(
        document,
        _access_key(ElectronicInvoiceModel.NFE),
        b"<signed-nfe-synthetic />",
    )

    request = envelope.to_gateway_request()

    assert request.scope == document.scope
    assert request.access_key.model is ElectronicInvoiceModel.NFE
    assert request.idempotency_key == envelope.idempotency_key
    assert request.request_fingerprint == envelope.request_fingerprint


def test_nfe_envelope_rejects_wrong_document_family_or_access_key_model() -> None:
    with pytest.raises(NfeIssuanceContractError, match="document_kind"):
        NfeIssuanceEnvelope.build(
            _nfe_document(kind=FiscalDocumentKind.NFCE),
            _access_key(ElectronicInvoiceModel.NFE),
            b"<signed-nfe-synthetic />",
        )

    with pytest.raises(NfeIssuanceContractError, match="model 55"):
        NfeIssuanceEnvelope.build(
            _nfe_document(),
            _access_key(ElectronicInvoiceModel.NFCE),
            b"<signed-nfe-synthetic />",
        )


def test_nfse_service_totals_are_deterministic_and_validated() -> None:
    document = _nfse_document()

    assert document.totals.gross_amount.amount == Decimal("100.00")
    assert document.totals.deduction_amount.amount == Decimal("10.00")
    assert document.totals.taxable_amount.amount == Decimal("90.00")
    assert document.totals.iss_amount.amount == Decimal("4.50")

    with pytest.raises(FiscalValidationError, match="cannot exceed taxable_amount"):
        NfseServiceLine(
            line_number=1,
            municipal_service_code="0107",
            description="Servico sintetico",
            gross_amount=Money(Decimal("100.00")),
            deduction_amount=Money(Decimal("10.00")),
            iss_amount=Money(Decimal("91.00")),
        )


def test_nfse_idempotency_and_fingerprint_ignore_transient_identity() -> None:
    first = _nfse_document(document_id="nfse-a", correlation="corr-a")
    second = _nfse_document(document_id="nfse-b", correlation="corr-b")

    assert build_nfse_issuance_key(first) == build_nfse_issuance_key(second)
    assert build_nfse_request_fingerprint(first) == build_nfse_request_fingerprint(second)


class _AuthorizedNfseGateway:
    def authorize(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        return NfseAuthorizationResult(
            status=AuthorizationStatus.AUTHORIZED,
            scope=request.document.scope,
            document_id=request.document.document_id,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.request_fingerprint,
            provider=_provider(),
            provider_request_id="provider-request-1",
            invoice_reference="nfse-authorized-reference-1",
            verification_code="verification-synthetic",
        )


class _WrongDocumentGateway:
    def authorize(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        return NfseAuthorizationResult(
            status=AuthorizationStatus.AUTHORIZED,
            scope=request.document.scope,
            document_id="other-document",
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.request_fingerprint,
            provider=_provider(),
            invoice_reference="nfse-authorized-reference-1",
        )


def test_nfse_gateway_authorization_is_provider_neutral_and_fail_closed() -> None:
    request = NfseAuthorizationRequest.build(_nfse_document())
    result = NfseGatewayClient(_AuthorizedNfseGateway()).authorize(request)

    assert result.status is AuthorizationStatus.AUTHORIZED
    assert result.invoice_reference == "nfse-authorized-reference-1"

    with pytest.raises(NfseGatewayContractError, match="different document_id"):
        NfseGatewayClient(_WrongDocumentGateway()).authorize(request)


def test_nfse_result_state_invariants_prevent_false_success() -> None:
    request = NfseAuthorizationRequest.build(_nfse_document())

    with pytest.raises(FiscalValidationError, match="pending NFS-e"):
        NfseAuthorizationResult(
            status=AuthorizationStatus.PENDING,
            scope=request.document.scope,
            document_id=request.document.document_id,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.request_fingerprint,
            provider=_provider(),
            invoice_reference="must-not-exist",
        )

    rejected = NfseAuthorizationResult(
        status=AuthorizationStatus.REJECTED,
        scope=request.document.scope,
        document_id=request.document.document_id,
        idempotency_key=request.idempotency_key,
        request_fingerprint=request.request_fingerprint,
        provider=_provider(),
        rejection_code="SYNTHETIC-001",
        rejection_message="Rejeicao sintetica",
    )
    assert rejected.status is AuthorizationStatus.REJECTED



def test_nfse_namespace_is_part_of_issuance_identity_and_fingerprint():
    base = _nfse_document()
    first_scope = replace(base.scope, host_namespace="host-a")
    second_scope = replace(base.scope, host_namespace="host-b")
    first = replace(base, scope=first_scope, issuer=replace(base.issuer, scope=first_scope))
    second = replace(base, scope=second_scope, issuer=replace(base.issuer, scope=second_scope))
    assert build_nfse_issuance_key(first) != build_nfse_issuance_key(second)
    assert build_nfse_request_fingerprint(first) != build_nfse_request_fingerprint(second)
    retry_scope = replace(first_scope, correlation_id="another-request")
    retry = replace(first, scope=retry_scope, issuer=replace(first.issuer, scope=retry_scope))
    assert build_nfse_issuance_key(first) == build_nfse_issuance_key(retry)
    assert build_nfse_request_fingerprint(first) == build_nfse_request_fingerprint(retry)


def test_nfse_issuer_cannot_cross_host_namespace():
    base = _nfse_document()
    with pytest.raises(FiscalValidationError, match="same scope"):
        replace(base, scope=replace(base.scope, host_namespace="other-host"))


def test_nfse_legacy_unscoped_identity_is_preserved():
    document = _nfse_document()
    assert build_nfse_issuance_key(document).value == (
        "deb58d1b308b781a9fcf972445d223b71176bc4f1b79ec2268832a81276a2760"
    )
    assert build_nfse_request_fingerprint(document) == (
        "8f425055c0bcffaac72cf713696774c4a556e452769819d4d84c8b9c4bcdf76b"
    )
