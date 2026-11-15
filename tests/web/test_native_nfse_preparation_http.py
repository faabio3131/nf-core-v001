"""Native National/Cajamar NFS-e preparation and synthetic HTTP fiscal journeys."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch
from xml.sax.saxutils import escape

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID, ObjectIdentifier
from fastapi.testclient import TestClient
from lxml import etree

from kordena_fiscal.application.cajamar_substitution_review import (
    review_cajamar_substitution,
)
from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import FiscalArchiveKind, RetentionPolicyMetadata
from kordena_fiscal.compliance.nfse_preaudit import nfse_preaudit
from kordena_fiscal.control_plane import (
    FiscalOrganization,
    FiscalUnitRegistration,
    SecretReference,
    SecretReferenceKind,
)
from kordena_fiscal.control_plane.commercial import (
    ConfiguredFiscalOperation,
    ProviderBinding,
)
from kordena_fiscal.control_plane.models import (
    ControlPlaneAuditAction,
    ControlPlaneAuditEvent,
)
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    ExecutionScope,
    FiscalAddress,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalProfile,
    FiscalValidationError,
    Money,
    MunicipalRegistration,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.cajamar_geisweb_cancellation_builder import (
    CajamarCancellationDecision,
    interpret_cajamar_cancel_response,
)
from kordena_fiscal.gateway.cajamar_geisweb_homologation import CajamarGeiswebResult
from kordena_fiscal.gateway.nfse_nacional_homologation import (
    NACIONAL_HOMOLOGATION_PROVIDER_ID,
    NfseNacionalHomologationGateway,
)
from kordena_fiscal.gateway.osasco_rtc_homologation import (
    OsascoRtcHomologationTransport,
    OsascoWcfContract,
)
from kordena_fiscal.gateway.osasco_rtc_tax_policy import (
    OsascoReviewedRtcPolicy,
    build_osasco_reviewed_tax_resolver,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4ProviderOutcome,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance import NfseAuthorizationRequest, NfseGatewayClient
from kordena_fiscal.issuance.nfse_dps_builder import build_signed_dps
from kordena_fiscal.lifecycle import FiscalDocumentState
from kordena_fiscal.operations import FakeFiscalOperationsGateway, FiscalOperationsClient
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.persistence.ports import PersistenceConflictError, PersistenceStateError
from kordena_fiscal.runtime.api import build_entrypoint_fiscal_handler_factory
from kordena_fiscal.runtime.barueri_environment import BarueriReviewedStartup
from kordena_fiscal.runtime.canonical_fiscal_composition import (
    _GovernedNationalNfseGateway,
    build_runtime_fiscal_handler_factory,
)
from kordena_fiscal.runtime.config import RuntimeSettings
from kordena_fiscal.runtime.fiscal_runtime import (
    CanonicalFiscalOperationPath,
    CanonicalPortalOperationExecutor,
)
from kordena_fiscal.runtime.osasco_operational_composition import (
    OsascoTrustedRuntimePorts,
)
from kordena_fiscal.runtime.provider_operation_wiring import build_provider_operation_handlers
from kordena_fiscal.runtime.sp4_municipal_canonical_composition import (
    Sp4ReviewedMunicipalPorts,
)
from kordena_fiscal.runtime.sp4_municipal_request_factories import (
    build_osasco_rtc_issue_request_factory,
)
from kordena_fiscal.security.human_identity import (
    HumanAccount,
    HumanIdentityService,
    InMemoryHumanAccountRepository,
    InMemoryWebSessionRepository,
    PortalRole,
    ScryptPasswordHasher,
)
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.contracts import EphemeralProviderCredentialsMaterial
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault
from kordena_fiscal.web import create_app
from kordena_fiscal.web.human_auth import CSRF_COOKIE, CSRF_HEADER
from kordena_fiscal.web.portal_runtime import DurableHumanPortalExecutor
from kordena_fiscal.xml.nfse_nacional_schema import national_dps_validator

TENANT = "tenant-native"
UNIT = "unit-cajamar"
IBGE = "3509205"
ROUTE = "/v1/portal/operations/prepareNativeNfse"


def _database(
    path: Path, *, with_binding: bool = True,
    provider_id: str = NACIONAL_HOMOLOGATION_PROVIDER_ID,
    issuer_ibge: str = IBGE,
    tax_regime: TaxRegimeCode = TaxRegimeCode.SIMPLES_NACIONAL,
) -> SqliteFiscalDatabase:
    db = SqliteFiscalDatabase(path)
    db.initialize()
    jurisdiction = BrazilianJurisdiction("SP", issuer_ibge)
    scope = ExecutionScope(
        TENANT, UNIT, FiscalEnvironment.HOMOLOGATION, "setup", "fm-nfcore"
    )
    with db() as uow:
        uow.control_plane.add_organization(
            FiscalOrganization(tenant_id=TENANT, legal_name="Emissor Sintetico")
        )
        uow.control_plane.add_unit(FiscalUnitRegistration(
            tenant_id=TENANT, unit_id=UNIT, display_name="Cajamar",
            enabled_environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        ))
        # The real Portal discovers registered units from canonical audit
        # evidence. A raw unit insert alone is not a completed onboarding.
        uow.control_plane.append_audit(ControlPlaneAuditEvent(
            event_id="synthetic-native-unit-onboarded",
            occurred_at=datetime.now(UTC),
            actor_id="synthetic-test-setup",
            action=ControlPlaneAuditAction.UNIT_ONBOARDED,
            target_type="unit", target_id=UNIT, correlation_id="synthetic-onboarding",
            tenant_id=TENANT, unit_id=UNIT,
        ))
        uow.control_plane.add_profile(FiscalProfile(
            profile_id="issuer-native", scope=scope,
            cnpj=Cnpj("11222333000181"), legal_name="Emissor Sintetico Ltda",
            tax_regime=tax_regime,
            state_registration=StateRegistration("SP", "123456789"),
            municipal_registration=(
                MunicipalRegistration("123456") if issuer_ibge == "3534401"
                else MunicipalRegistration("1234567") if issuer_ibge in ("3505708", "3525904")
                else None
            ),
            primary_cnae=CnaeCode("6201501"),
            address=FiscalAddress(
                street="Rua de Homologacao", number="10", district="Centro",
                municipality_name=(
                    "Osasco" if issuer_ibge == "3534401"
                    else "Barueri" if issuer_ibge == "3505708"
                    else "Jundiai" if issuer_ibge == "3525904" else "Cajamar"
                ), jurisdiction=jurisdiction,
                postal_code="07750000",
            ),
            effective_from=datetime.now(UTC) - timedelta(days=1),
        ))
        if with_binding:
            uow.commercial.put_provider_binding(ProviderBinding(
                binding_id="native-nfse-binding", tenant_id=TENANT,
                unit_id=UNIT, environment=FiscalEnvironment.HOMOLOGATION,
                document_kind=FiscalDocumentKind.NFSE,
                jurisdiction=jurisdiction,
                operation=ConfiguredFiscalOperation.AUTHORIZE,
                provider_id=provider_id,
            ))
            if provider_id in {
                "cajamar-geisweb-homologation", "osasco-rtc-homologation",
                "barueri-pmb004-homologation",
                "jundiai-giss-v2-homologation",
            }:
                uow.commercial.put_provider_binding(ProviderBinding(
                    binding_id="cajamar-query-binding",
                    tenant_id=TENANT, unit_id=UNIT,
                    environment=FiscalEnvironment.HOMOLOGATION,
                    document_kind=FiscalDocumentKind.NFSE,
                    jurisdiction=jurisdiction,
                    operation=ConfiguredFiscalOperation.QUERY,
                    provider_id=provider_id,
                ))
                uow.commercial.put_provider_binding(ProviderBinding(
                    binding_id="cajamar-cancel-binding",
                    tenant_id=TENANT, unit_id=UNIT,
                    environment=FiscalEnvironment.HOMOLOGATION,
                    document_kind=FiscalDocumentKind.NFSE,
                    jurisdiction=jurisdiction,
                    operation=ConfiguredFiscalOperation.CANCEL,
                    provider_id=provider_id,
                ))
        uow.commit()
    return db


def _client(
    db: SqliteFiscalDatabase,
    role: PortalRole = PortalRole.OWNER,
    *,
    operation_executor: CanonicalPortalOperationExecutor | None = None,
) -> TestClient:
    password = "only-for-synthetic-fixtures-2026"
    hasher = ScryptPasswordHasher()
    accounts = InMemoryHumanAccountRepository((HumanAccount(
        account_id="native-" + role.value, email=role.value + "@example.com",
        password_hash=hasher.hash(password), tenant_id=TENANT, role=role,
        unit_ids=frozenset({UNIT}),
    ),))
    identity = HumanIdentityService(
        accounts=accounts, sessions=InMemoryWebSessionRepository(),
        password_hasher=hasher,
    )
    web = TestClient(
        create_app(
            human_identity=identity,
            portal_executor=DurableHumanPortalExecutor(
                db, operation_executor=operation_executor,
            ),
        ),
        base_url="https://nfcore.test",
    )
    response = web.post("/v1/auth/login", json={
        "email": role.value + "@example.com", "password": password,
    })
    assert response.status_code == 200
    return web


def _payload() -> dict[str, object]:
    return {
        "unit_id": UNIT, "environment": "homologation",
        "source_id": "service-order-native-1",
        "competence_date": datetime.now(UTC).date().isoformat(),
        "service_state_code": "SP", "service_municipality_ibge": IBGE,
        "national_taxation_code": "010701",
        "municipal_service_code": "0107",
        "description": "Servico sintetico revisado pelo escritorio",
        "gross_amount": "100.00", "deduction_amount": "0.00",
        "iss_amount": "3.00", "iss_withheld": False,
        "taker_document": "12345678000195",
        "taker_name": "Tomador Sintetico Ltda",
        "source_normative": "urn:nfcore:synthetic:rule:2026",
        "rule_version": 1, "fiscal_review_approved": True,
    }


def _post(web: TestClient, payload: dict[str, object], key: str = "first-review"):
    csrf = web.cookies.get(CSRF_COOKIE)
    assert csrf
    return web.post(
        ROUTE, json=payload,
        headers={CSRF_HEADER: csrf, "Idempotency-Key": key},
    )


def test_osasco_portal_prepares_durable_original_and_replay_without_dps(
    tmp_path: Path,
) -> None:
    db = _database(
        tmp_path / "osasco-original.sqlite", issuer_ibge="3534401",
        provider_id="osasco-rtc-homologation", tax_regime=TaxRegimeCode.NORMAL,
    )
    web = _client(db)
    app = FiscalApplicationService(db)
    payload = _payload() | _TAKER_ADDRESS | {
        "competence_date": "2026-11-12",
        "source_id": "osasco-rtc-original",
        "service_municipality_ibge": "3534401",
    }
    first = _post(web, payload, key="osasco-original-prepare")
    assert first.status_code == 200, first.text
    assert first.json()["numbering_authority"] == "municipal_rps_durable"
    identifier = first.json()["document_id"]
    scope = ExecutionScope(
        TENANT, UNIT, FiscalEnvironment.HOMOLOGATION, "readback", "fm-nfcore",
    )
    original = app.load_sp4_original_rps(scope, identifier)
    assert (original.issuer_ibge, original.rps_number, original.rps_series) == (
        "3534401", "1", "R1",
    )
    assert original.municipal_batch_id is None
    again = _post(web, payload, key="osasco-original-prepare")
    assert again.status_code == 200, again.text
    assert again.json()["replay"] is True
    assert again.json()["document_id"] == identifier
    assert app.load_sp4_original_rps(scope, identifier) == original


def test_osasco_original_receipt_issue_and_read_only_full_note_http(
    tmp_path: Path,
) -> None:
    """Existing Portal/UoW; synthetic reviewed WCF notes, no municipal HTTP."""
    db = _database(
        tmp_path / "osasco-full-native.sqlite", issuer_ibge="3534401",
        provider_id="osasco-rtc-homologation", tax_regime=TaxRegimeCode.NORMAL,
    )
    application = FiscalApplicationService(db)
    submitted = Mock(return_value=Sp4ProviderOutcome(
        status=AuthorizationStatus.PENDING, provider_request_id="8001",
    ))
    verified = Mock()

    def read_full_invoice(
        request: NfseAuthorizationRequest, original: Sp4OriginalRps,
    ) -> Sp4ProviderOutcome:
        assert original.issuer_ibge == "3534401"
        assert original.rps_series == "R1"
        assert original.municipal_batch_id is None
        assert request.request_fingerprint == original.request_fingerprint
        invoice = Sp4VerifiedInvoice(
            issuer_cnpj=original.issuer_cnpj,
            issuer_ibge=original.issuer_ibge,
            competence_date=original.competence_date,
            rps_number=original.rps_number,
            rps_series=original.rps_series,
            gross_amount=original.gross_amount,
            invoice_number="8001",
            verification_code="OSASCO001",
            invoice_reference="8001",
            authorized_xml=b"<OsascoOfficialInvoiceSynthetic>8001</OsascoOfficialInvoiceSynthetic>",
        )
        return Sp4ProviderOutcome(
            status=AuthorizationStatus.AUTHORIZED, official_invoice=invoice,
        )

    queried = Mock(side_effect=read_full_invoice)
    ports = Sp4ReviewedMunicipalPorts(
        load_original_rps=Mock(side_effect=AssertionError("noncanonical loader")),
        fiscal_issuer_policy=Mock(), validate_prepared_rps=Mock(),
        submit_official_rps=submitted, query_official_rps=queried,
        verify_official_invoice_xml=verified,
    )
    handlers = build_runtime_fiscal_handler_factory(
        operations_gateway=FakeFiscalOperationsGateway(),
        sp4_reviewed_municipalities={"osasco-rtc-homologation": ports},
    )(application)
    web = _client(
        db, operation_executor=CanonicalPortalOperationExecutor(
            unit_of_work_factory=db,
            path=CanonicalFiscalOperationPath(application, handlers=handlers),
        ),
    )
    payload = _payload() | _TAKER_ADDRESS | {
        "competence_date": "2026-11-12",
        "source_id": "osasco-http-one-post",
        "service_municipality_ibge": "3534401",
    }
    prepared = _post(web, payload, key="osasco-one-preparation")
    assert prepared.status_code == 200, prepared.text
    document_id = prepared.json()["document_id"]
    csrf = web.cookies.get(CSRF_COOKIE)
    assert csrf
    body = {"unit_id": UNIT, "environment": "homologation", "document_id": document_id}
    issue = web.post(
        "/v1/portal/operations/issueFiscalDocument", json=body,
        headers={CSRF_HEADER: csrf, "Idempotency-Key": "osasco-one-post"},
    )
    assert issue.status_code == 200, issue.text
    assert submitted.call_count == 1
    assert queried.call_count == 0
    reconcile = web.post(
        "/v1/portal/operations/reconcileFiscalOperation", json=body,
        headers={CSRF_HEADER: csrf, "Idempotency-Key": "osasco-original-read"},
    )
    assert reconcile.status_code == 200, reconcile.text
    assert reconcile.json()["status"] == FiscalDocumentState.AUTHORIZED.value
    assert submitted.call_count == 1
    queried.assert_called_once()
    verified.assert_called_once()
    xml = web.get(
        f"/v1/portal/documents/{document_id}/artifacts/authorized_xml",
        params={"unit_id": UNIT, "environment": "homologation"},
    )
    assert xml.status_code == 200, xml.text
    assert xml.content == b"<OsascoOfficialInvoiceSynthetic>8001</OsascoOfficialInvoiceSynthetic>"
    repeat = web.post(
        "/v1/portal/operations/issueFiscalDocument", json=body,
        headers={CSRF_HEADER: csrf, "Idempotency-Key": "osasco-one-post"},
    )
    assert repeat.status_code == 200, repeat.text
    assert submitted.call_count == 1



def _osasco_synthetic_soap(method: str, receipt_number: str = "1") -> bytes:
    pre = '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
    pre += 'xmlns:t="http://tempuri.org/" '
    pre += (
        'xmlns:a="http://schemas.datacontract.org/2004/07/'
        'Eissnfe.Negocio.WebServices.Mensagem" '
    )
    pre += (
        'xmlns:b="http://schemas.datacontract.org/2004/07/'
        'Eissnfe.Dominio.DataTransferObject.Prestador" '
    )
    pre += (
        'xmlns:c="http://schemas.datacontract.org/2004/07/'
        'Eissnfe.Dominio.DataTransferObject.Contribuinte">'
    )
    body = f"<s:Body><t:{method}Response><t:{method}Result>"
    if method == "ConsultarNotaCompleta":
        body += (
            '<a:Erro>false</a:Erro><a:NotasGeradas>'
            f'<b:NotaFiscalRelatorioDTO><b:Numero>{8000 + int(receipt_number)}</b:Numero>'
            f'<b:NumeroRecibo>{receipt_number}</b:NumeroRecibo>'
            '<b:CodigoAutenticidade>OSASCO1234</b:CodigoAutenticidade>'
            '<b:Prestador><c:CNPJ>11222333000181</c:CNPJ></b:Prestador>'
            '<b:Valor>100.00</b:Valor></b:NotaFiscalRelatorioDTO>'
            '</a:NotasGeradas><a:QtdeNotas>1</a:QtdeNotas>'
        )
    else:
        body += "<a:Erro>false</a:Erro>"
    body += f"</t:{method}Result></t:{method}Response></s:Body></s:Envelope>"
    return (pre + body).encode("utf-8")


def _osasco_synthetic_policy() -> OsascoReviewedRtcPolicy:
    return OsascoReviewedRtcPolicy(
        source_normative="urn:nfcore:synthetic:rule:2026",
        rule_version=1, effective_from=date(2026, 1, 1),
        effective_through=date(2026, 12, 31),
        municipal_service_code="0107", national_taxation_code="010701",
        activity="14.01", class_trib="000001", nbs_code="1.2001.10.00",
        incidence_location="3", operation_indicator="050101",
        service_city="Osasco", service_city_ibge="3534401", service_state="SP",
        recipient_street_type="RUA", iss_rate=Decimal("3"),
        pis=Decimal("0.00"), cofins=Decimal("0.00"), csll=Decimal("0.00"),
        income_tax=Decimal("0.00"), inss=Decimal("0.00"),
        other_taxes=Decimal("0.00"), test_only=False,
    )


@pytest.mark.parametrize("cancel_proof", [True, False, None])
def test_osasco_http_full_issued_lifecycle_cancel_replay_and_unknown_outcome(
    tmp_path: Path, cancel_proof: bool | None,
) -> None:
    """Synthetic SOAP verifies the actual Portal→UoW→WCF→read-back path."""
    db = _database(
        tmp_path / f"osasco-cycle-{cancel_proof}.sqlite",
        issuer_ibge="3534401", provider_id="osasco-rtc-homologation",
        tax_regime=TaxRegimeCode.NORMAL,
    )
    posts: list[str] = []
    def exchange(_body: bytes, soap_action: str, _timeout: float) -> bytes:
        method = soap_action.rsplit("/", 1)[-1]
        posts.append(method)
        return _osasco_synthetic_soap(method)

    transport = OsascoRtcHomologationTransport(
        resolver=Mock(resolve_provider_id=lambda **kw: (
            "osasco-rtc-homologation"
        )),
        resolve_key=lambda _scope, _cnpj: "12345678-1234-1234-1234-123456789012",
        validated_request=lambda _raw, _hash: None,
        contract_for_method=lambda method: OsascoWcfContract(
            action="http://tempuri.org/INotaFiscalEletronica/" + method,
            method=method, wsdl_sha256="a" * 64,
        ),
        exchange=exchange,
    )
    reviewed = OsascoTrustedRuntimePorts(
        transport=transport,
        build_wcf_operation=build_osasco_rtc_issue_request_factory(
            resolve_rtc_fields=build_osasco_reviewed_tax_resolver(
                lambda _request, _original: _osasco_synthetic_policy(),
            ),
            validate_official_request=lambda _raw: None,
        ),
        verify_wcf_rps_identity=Mock(),
        fiscal_issuer_policy=Mock(),
        validate_prepared_rps=Mock(),
        verify_official_invoice_xml=Mock(),
        verify_official_cancel=Mock(return_value=cancel_proof),
    )
    app = FiscalApplicationService(db)
    handlers = build_runtime_fiscal_handler_factory(
        osasco_runtime_ports=reviewed,
    )(app)
    assert "cancelOsascoNfse" in handlers
    web = _client(
        db, operation_executor=CanonicalPortalOperationExecutor(
            unit_of_work_factory=db,
            path=CanonicalFiscalOperationPath(app, handlers=handlers),
        ),
    )
    payload = _payload() | _TAKER_ADDRESS | {
        "competence_date": "2026-11-12",
        "source_id": "osasco-complete-cycle",
        "service_municipality_ibge": "3534401",
    }
    prepared = _post(web, payload, "osasco-complete")
    assert prepared.status_code == 200, prepared.text
    document_id = prepared.json()["document_id"]
    csrf = web.cookies.get(CSRF_COOKIE)
    assert csrf
    body = {"unit_id": UNIT, "environment": "homologation", "document_id": document_id}
    issued = web.post(
        "/v1/portal/operations/issueFiscalDocument", json=body,
        headers={CSRF_HEADER: csrf, "Idempotency-Key": "osasco-issue-key"},
    )
    assert issued.status_code == 200, issued.text
    assert posts == ["RTC_EmitirNFE"]
    query = web.post(
        "/v1/portal/operations/reconcileFiscalOperation", json=body,
        headers={CSRF_HEADER: csrf, "Idempotency-Key": "osasco-reconcile-key"},
    )
    assert query.status_code == 200, query.text
    assert query.json()["status"] == FiscalDocumentState.AUTHORIZED.value
    assert posts == ["RTC_EmitirNFE", "ConsultarNotaCompleta"]
    xml = web.get(
        f"/v1/portal/documents/{document_id}/artifacts/authorized_xml",
        params={"unit_id": UNIT, "environment": "homologation"},
    )
    assert xml.status_code == 200
    assert xml.content == _osasco_synthetic_soap("ConsultarNotaCompleta")
    cancellation = body | {
        "human_approval": True,
        "cancellation_reason": "Cancelamento humano revisado",
    }
    cancelled = web.post(
        "/v1/portal/operations/cancelOsascoNfse", json=cancellation,
        headers={CSRF_HEADER: csrf, "Idempotency-Key": "osasco-cancel-key"},
    )
    assert cancelled.status_code == 200, cancelled.text
    expected = (
        FiscalDocumentState.CANCEL_REQUESTED if cancel_proof is None
        else (
            FiscalDocumentState.CANCELLED if cancel_proof
            else FiscalDocumentState.AUTHORIZED
        )
    )
    assert cancelled.json()["status"] == expected.value
    assert posts == ["RTC_EmitirNFE", "ConsultarNotaCompleta", "Cancelar"]
    retry = web.post(
        "/v1/portal/operations/cancelOsascoNfse", json=cancellation,
        headers={CSRF_HEADER: csrf, "Idempotency-Key": "osasco-cancel-key"},
    )
    assert retry.status_code == 200
    assert posts.count("Cancelar") == 1
    if cancel_proof is not False:
        duplicate = web.post(
            "/v1/portal/operations/cancelOsascoNfse", json=cancellation,
            headers={CSRF_HEADER: csrf, "Idempotency-Key": "different-osasco-key"},
        )
        assert duplicate.status_code == 409
        assert posts.count("Cancelar") == 1



def test_osasco_type_s_substitution_keeps_one_invoice_per_original_rps(
    tmp_path: Path,
) -> None:
    """Type S cancels old note once before authorizing the prepared substitute."""
    db = _database(
        tmp_path / "osasco-substitution.sqlite", issuer_ibge="3534401",
        provider_id="osasco-rtc-homologation", tax_regime=TaxRegimeCode.NORMAL,
    )
    posts: list[tuple[str, str | None]] = []

    def exchange(soap: bytes, action: str, _timeout: float) -> bytes:
        method = action.rsplit("/", 1)[-1]
        root = etree.fromstring(soap)
        fields = {
            etree.QName(node).localname: node.text
            for node in root.iter() if isinstance(node.tag, str)
        }
        assert fields.get("ChaveAutenticacao") == (
            "12345678-1234-1234-1234-123456789012"
        )
        posts.append((method, fields.get("TipoCancelamento")))
        number = fields.get("NumeroReciboUnico") or fields.get("NumeroRecibo") or "1"
        return _osasco_synthetic_soap(method, number)

    transport = OsascoRtcHomologationTransport(
        resolver=Mock(resolve_provider_id=lambda **_kw: "osasco-rtc-homologation"),
        resolve_key=lambda _s, _c: "12345678-1234-1234-1234-123456789012",
        validated_request=lambda _xml, _hash: None,
        contract_for_method=lambda method: OsascoWcfContract(
            action="http://tempuri.org/INotaFiscalEletronica/" + method,
            method=method, wsdl_sha256="a" * 64,
        ),
        exchange=exchange,
    )
    ports = OsascoTrustedRuntimePorts(
        transport=transport,
        build_wcf_operation=build_osasco_rtc_issue_request_factory(
            resolve_rtc_fields=build_osasco_reviewed_tax_resolver(
                lambda _req, _src: _osasco_synthetic_policy(),
            ),
            validate_official_request=lambda _xml: None,
        ),
        verify_wcf_rps_identity=Mock(),
        fiscal_issuer_policy=Mock(),
        validate_prepared_rps=Mock(),
        verify_official_invoice_xml=Mock(),
        verify_official_cancel=Mock(return_value=True),
    )
    app = FiscalApplicationService(db)
    handlers = build_runtime_fiscal_handler_factory(osasco_runtime_ports=ports)(app)
    assert "substituteOsascoNfse" in handlers
    web = _client(
        db, operation_executor=CanonicalPortalOperationExecutor(
            unit_of_work_factory=db,
            path=CanonicalFiscalOperationPath(app, handlers=handlers),
        ),
    )
    data = _payload() | _TAKER_ADDRESS | {
        "competence_date": "2026-11-12",
        "service_municipality_ibge": "3534401",
    }
    old = _post(web, data | {"source_id": "osasco-old"}, "osasco-old-key")
    next_doc = _post(
        web, data | {"source_id": "osasco-substitute"}, "osasco-new-key",
    )
    assert old.status_code == 200 and next_doc.status_code == 200
    old_id, new_id = old.json()["document_id"], next_doc.json()["document_id"]
    scope = ExecutionScope(
        TENANT, UNIT, FiscalEnvironment.HOMOLOGATION, "check", "fm-nfcore",
    )
    assert app.load_sp4_original_rps(scope, old_id).rps_number == "1"
    assert app.load_sp4_original_rps(scope, new_id).rps_number == "2"
    csrf = web.cookies.get(CSRF_COOKIE)
    assert csrf
    headers = {CSRF_HEADER: csrf}
    base = {"unit_id": UNIT, "environment": "homologation"}
    def operation(name: str, document_id: str, key: str):
        return web.post(
            f"/v1/portal/operations/{name}", json=base | {"document_id": document_id},
            headers=headers | {"Idempotency-Key": key},
        )
    assert operation("issueFiscalDocument", old_id, "issue-old").status_code == 200
    authorized = operation("reconcileFiscalOperation", old_id, "query-old")
    assert authorized.status_code == 200, authorized.text
    assert authorized.json()["status"] == FiscalDocumentState.AUTHORIZED.value
    substitution = base | {
        "original_id": old_id, "replacement_id": new_id,
        "human_approval": True, "cancellation_reason": "Correcao revisada do servico",
    }
    sent = web.post(
        "/v1/portal/operations/substituteOsascoNfse", json=substitution,
        headers=headers | {"Idempotency-Key": "approve-substitution"},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["original_status"] == FiscalDocumentState.CANCELLED.value
    assert sent.json()["replacement_status"] == "ready_to_transmit"
    assert sent.json()["next_action"] == "issueFiscalDocument"
    assert posts[-1] == ("Cancelar", "S")
    same = web.post(
        "/v1/portal/operations/substituteOsascoNfse", json=substitution,
        headers=headers | {"Idempotency-Key": "approve-substitution"},
    )
    assert same.status_code == 200, same.text
    assert [method for method, _ in posts].count("Cancelar") == 1
    with db() as uow:
        entries = uow.archive.list_for_document(scope, old_id)
    links = [
        e for e in entries
        if e.media_type == "application/vnd.nfcore.osasco-substitution.v1+json"
    ]
    assert len(links) == 1
    assert json.loads(links[0].content)["replacement_id"] == new_id
    replacement = operation("issueFiscalDocument", new_id, "issue-substitute")
    assert replacement.status_code == 200, replacement.text
    again = operation("reconcileFiscalOperation", new_id, "query-substitute")
    assert again.status_code == 200, again.text
    assert again.json()["status"] == FiscalDocumentState.AUTHORIZED.value
    assert posts[-2:] == [
        ("RTC_EmitirNFE", None), ("ConsultarNotaCompleta", None),
    ]


def test_osasco_simples_after_november_cutoff_uses_national_not_municipal(
    tmp_path: Path,
) -> None:
    db = _database(
        tmp_path / "osasco-cutoff.sqlite", issuer_ibge="3534401",
        provider_id="osasco-rtc-homologation",
    )
    web = _client(db)
    payload = _payload() | _TAKER_ADDRESS | {
        "competence_date": "2026-11-12",
        "source_id": "osasco-national-mandatory",
        "service_municipality_ibge": "3534401",
    }
    response = _post(web, payload, key="osasco-cutoff")
    assert response.status_code == 400


def test_owner_prepares_native_nfse_and_replay_keeps_immutable_document(tmp_path: Path) -> None:
    db = _database(tmp_path / "native.sqlite")
    web = _client(db)
    first = _post(web, _payload())
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["status"] == FiscalDocumentState.READY_TO_TRANSMIT.value
    assert result["fiscal_authorization"] == "not_inferred_from_preparation"
    assert result["transmitted"] is False
    assert result["dps_numbering"] == "pending_durable_authority"
    replay = _post(web, _payload(), key="second-review")
    assert replay.status_code == 200, replay.text
    assert replay.json()["replay"] is True
    assert replay.json()["document_id"] == result["document_id"]
    scope = ExecutionScope(TENANT, UNIT, FiscalEnvironment.HOMOLOGATION, "check", "fm-nfcore")
    prepared = FiscalApplicationService(db).load_prepared_nfse_authorization(
        scope, result["document_id"]
    )
    assert prepared.document.issuer.cnpj.value == "11222333000181"
    assert prepared.document.service_taker is not None
    assert prepared.document.service_taker.tax_id.value == "12345678000195"
    assert prepared.document.services[0].iss_amount.amount == 3
    with db() as uow:
        assert len(uow.archive.list_for_document(scope, result["document_id"])) == 1


def test_native_mutation_replay_cannot_change_reviewed_fiscal_facts(tmp_path: Path) -> None:
    db = _database(tmp_path / "conflict.sqlite")
    web = _client(db)
    assert _post(web, _payload()).status_code == 200
    changed = _post(web, _payload() | {"iss_amount": "4.00"}, "different-http-key")
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "NATIVE_NFSE_CONTENT_CONFLICT"
    assert _post(web, _payload(), "third-http-key").json()["replay"] is True


def test_native_nfse_enforces_owner_csrf_unit_and_explicit_review(tmp_path: Path) -> None:
    db = _database(tmp_path / "security.sqlite")
    operator = _client(db, PortalRole.OPERATOR)
    assert _post(operator, _payload()).status_code == 403
    owner = _client(db)
    assert owner.post(ROUTE, json=_payload()).status_code == 403
    csrf = owner.cookies.get(CSRF_COOKIE)
    assert csrf
    assert owner.post(ROUTE, json=_payload(), headers={CSRF_HEADER: csrf}).status_code == 400
    assert _post(owner, _payload() | {"tenant_id": "other"}).status_code == 400
    assert _post(owner, _payload() | {"unit_id": "other"}).status_code == 403
    assert _post(owner, _payload() | {"environment": "production"}).status_code == 400
    assert _post(owner, _payload() | {"fiscal_review_approved": False}).status_code == 403


def test_native_nfse_requires_real_binding_and_effective_profile(tmp_path: Path) -> None:
    db = _database(tmp_path / "unbound.sqlite", with_binding=False)
    web = _client(db)
    result = _post(web, _payload())
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "NATIVE_NFSE_PROVIDER_NOT_CONFIGURED"


def test_unmodeled_untaxed_iss_and_malformed_money_fail_before_preparation(tmp_path: Path) -> None:
    db = _database(tmp_path / "tax.sqlite")
    web = _client(db)
    assert _post(web, _payload() | {"iss_amount": "0.00"}).status_code == 400
    assert _post(web, _payload() | {"gross_amount": "100.001"}).status_code == 400
    assert _post(web, _payload() | {"national_taxation_code": "bad"}).status_code == 400
    assert _post(web, _payload()).status_code == 200


_CAJAMAR_PROVIDER = "cajamar-geisweb-homologation"
_TAKER_ADDRESS = {
    "taker_street": "Rua Teste Fiscal",
    "taker_number": "100",
    "taker_neighborhood": "Centro",
    "taker_city": "Sao Paulo",
    "taker_state": "SP",
    "taker_municipality_ibge": "3550308",
    "taker_postal_code": "01001000",
}


def test_cajamar_official_substitution_rules_do_not_infer_soap_completion(
    tmp_path: Path,
) -> None:
    db = _database(
        tmp_path / "cajamar-substitution-policy.sqlite", provider_id=_CAJAMAR_PROVIDER,
    )
    web = _client(db)
    data = _payload() | _TAKER_ADDRESS | {
        "competence_date": "2026-10-31",
        "source_id": "cajamar-original-for-substitution",
    }
    old = _post(web, data, "cajamar-review-old")
    candidate = _post(
        web, data | {"source_id": "cajamar-candidate-substitution"},
        "cajamar-review-candidate",
    )
    assert old.status_code == 200, old.text
    assert candidate.status_code == 200, candidate.text
    app = FiscalApplicationService(db)
    scope = ExecutionScope(
        TENANT, UNIT, FiscalEnvironment.HOMOLOGATION,
        "review", "fm-nfcore",
    )
    original = app.load_prepared_nfse_authorization(
        scope, old.json()["document_id"],
    )
    replacement = app.load_prepared_nfse_authorization(
        scope, candidate.json()["document_id"],
    )
    reviewed = review_cajamar_substitution(
        original=original, replacement=replacement,
        reviewed_at=datetime(2026, 11, 5, tzinfo=UTC),
    )
    assert reviewed.municipal_action == "MUNICIPAL_PORTAL_SUBSTITUTION_REQUIRED"
    assert reviewed.deadline == date(2026, 11, 10)
    assert reviewed.official_fiscal_confirmation is False
    assert reviewed.original_id != reviewed.replacement_id

    with pytest.raises(FiscalValidationError, match="period expired"):
        review_cajamar_substitution(
            original=original, replacement=replacement,
            reviewed_at=datetime(2026, 11, 11, 3, tzinfo=UTC),
        )
    with pytest.raises(FiscalValidationError, match="distinct"):
        review_cajamar_substitution(
            original=original, replacement=original,
            reviewed_at=datetime(2026, 11, 5, tzinfo=UTC),
        )
    for updated in (
        replace(replacement.document, competence_date=date(2026, 10, 30)),
        replace(
            replacement.document,
            service_taker=replace(
                replacement.document.service_taker,
                legal_name="Outro tomador",
            ),
        ),
        replace(
            replacement.document,
            services=(
                replace(
                    replacement.document.services[0],
                    gross_amount=Money(Decimal("120.00")),
                ),
            ),
        ),
    ):
        changed = NfseAuthorizationRequest.build(updated)
        with pytest.raises(FiscalValidationError, match="cannot change"):
            review_cajamar_substitution(
                original=original, replacement=changed,
                reviewed_at=datetime(2026, 11, 5, tzinfo=UTC),
            )

    # Prepared alone cannot be mistaken for substitution completed by city.
    with pytest.raises(PersistenceStateError):
        app.review_prepared_cajamar_substitution(
            scope=scope, original_id=old.json()["document_id"],
            replacement_id=candidate.json()["document_id"],
            reviewed_at=datetime(2026, 11, 5, tzinfo=UTC),
        )


def test_barueri_portal_prepares_original_with_durable_remittance_and_replay(
    tmp_path: Path,
) -> None:
    db = _database(
        tmp_path / "barueri-portal.sqlite",
        issuer_ibge="3505708",
        provider_id="barueri-pmb004-homologation",
        tax_regime=TaxRegimeCode.NORMAL,
    )
    web = _client(db)
    reviewed = _payload() | _TAKER_ADDRESS | {
        "competence_date": "2026-10-31",
        "service_municipality_ibge": "3505708",
        "source_id": "barueri-original-rps-2026",
    }
    first = _post(web, reviewed, key="barueri-reviewed-prepare")
    assert first.status_code == 200, first.text
    record = first.json()
    assert record["numbering_authority"] == "municipal_rps_durable"
    assert record["status"] == FiscalDocumentState.READY_TO_TRANSMIT.value
    assert record["transmitted"] is False
    assert record["dps_numbering"] == "not_applicable_municipal_original_rps"
    scope = ExecutionScope(
        TENANT, UNIT, FiscalEnvironment.HOMOLOGATION, "barueri-replay", "fm-nfcore",
    )
    application = FiscalApplicationService(db)
    original = application.load_sp4_original_rps(scope, record["document_id"])
    assert original.issuer_ibge == "3505708"
    assert original.rps_number == "1"
    assert original.rps_series == ""
    assert original.municipal_batch_id == "00000000001"
    assert application.load_barueri_remittance_protocol(
        scope, record["document_id"],
    ) is None
    assert application.load_barueri_submission_date(
        scope, record["document_id"],
    ) is None
    again = _post(web, reviewed, key="barueri-reviewed-prepare")
    assert again.status_code == 200, again.text
    assert again.json()["replay"] is True
    assert application.load_sp4_original_rps(scope, record["document_id"]) == original


def test_cajamar_prepares_original_rps_through_same_portal_and_uow(
    tmp_path: Path,
) -> None:
    db = _database(
        tmp_path / "cajamar-portal.sqlite", provider_id=_CAJAMAR_PROVIDER,
    )
    web = _client(db)
    reviewed = _payload() | _TAKER_ADDRESS | {
        "competence_date": "2026-10-31",
        "source_id": "cajamar-original-portal-2026",
    }
    first = _post(web, reviewed)
    assert first.status_code == 200, first.text
    record = first.json()
    assert record["status"] == FiscalDocumentState.READY_TO_TRANSMIT.value
    assert record["numbering_authority"] == "municipal_rps_durable"
    assert record["dps_numbering"] == "not_applicable_municipal_original_rps"
    assert record["transmitted"] is False
    assert record["fiscal_authorization"] == "not_inferred_from_preparation"

    scope = ExecutionScope(
        TENANT, UNIT, FiscalEnvironment.HOMOLOGATION, "replay", "fm-nfcore",
    )
    app = FiscalApplicationService(db)
    saved = app.load_prepared_nfse_authorization(scope, record["document_id"])
    assert saved.document.dps_number is None
    assert saved.document.service_taker is not None
    assert saved.document.service_taker.address is not None
    assert saved.document.service_taker.address.postal_code == "01001000"
    original = app.load_sp4_original_rps(scope, record["document_id"])
    assert original.issuer_ibge == IBGE
    assert original.rps_number == "1"
    assert original.municipal_batch_id == "1"
    assert original.issuer_cnpj == saved.document.issuer.cnpj

    again = _post(web, reviewed, key="same-cajamar-source")
    assert again.status_code == 200, again.text
    assert again.json()["replay"] is True
    assert app.load_sp4_original_rps(scope, record["document_id"]) == original
    with db() as uow:
        records = uow.archive.list_for_document(scope, record["document_id"])
    assert len(records) == 2


def test_cajamar_requires_full_taker_and_blocks_national_mandatory_competence(
    tmp_path: Path,
) -> None:
    db = _database(
        tmp_path / "cajamar-no-false-channel.sqlite", provider_id=_CAJAMAR_PROVIDER,
    )
    web = _client(db)
    prior = _payload() | {"competence_date": "2026-10-31"}
    missing_address = _post(web, prior)
    assert missing_address.status_code == 400
    assert missing_address.json()["detail"]["code"] == "NATIVE_NFSE_INVALID_FISCAL_FACTS"
    wrong_channel = _post(web, _payload() | _TAKER_ADDRESS | {
        "competence_date": "2026-11-01",
    })
    assert wrong_channel.status_code == 400
    assert wrong_channel.json()["detail"]["code"] == "NATIVE_NFSE_INVALID_FISCAL_FACTS"
    scope = ExecutionScope(
        TENANT, UNIT, FiscalEnvironment.HOMOLOGATION, "check", "fm-nfcore",
    )
    reference = "native-nfse-" + hashlib.sha256(
        (repr(scope.identity_partition_key) + ":service-order-native-1").encode(),
    ).hexdigest()[:40]
    with db() as uow:
        assert uow.lifecycle.get(reference) is None


def test_native_national_preserves_complete_reviewed_brazilian_taker(
    tmp_path: Path,
) -> None:
    db = _database(tmp_path / "native-full-taker.sqlite")
    web = _client(db)
    sent = _post(web, _payload() | _TAKER_ADDRESS)
    assert sent.status_code == 200, sent.text
    scope = ExecutionScope(
        TENANT, UNIT, FiscalEnvironment.HOMOLOGATION, "check", "fm-nfcore",
    )
    doc = FiscalApplicationService(db).load_prepared_nfse_authorization(
        scope, sent.json()["document_id"],
    ).document
    assert doc.service_taker is not None
    assert doc.service_taker.address is not None
    assert doc.service_taker.address.jurisdiction.municipality_ibge_code == "3550308"


def test_cajamar_portal_prepares_sends_recovers_and_downloads_authorized_xml(
    tmp_path: Path,
) -> None:
    """Same Portal and one UoW; only synthetic GeisWeb ports, no official I/O."""
    db = _database(
        tmp_path / "cajamar-end-to-end.sqlite", provider_id=_CAJAMAR_PROVIDER,
    )
    app = FiscalApplicationService(db)
    submitted = Mock(return_value=Sp4ProviderOutcome(status=AuthorizationStatus.PENDING))
    verified = Mock()
    cancelled = Mock()

    def verified_cancel(
        request: NfseAuthorizationRequest, original: Sp4OriginalRps,
        invoice: Sp4VerifiedInvoice,
    ) -> CajamarCancellationDecision:
        cancelled(request, original, invoice)
        if request.document.source.source_id == "cajamar-second-for-ambiguous-cancel":
            raise RuntimeError("synthetic transport timeout after cancellation claim")
        official_cancel = (
            "<CancelaNfseResposta><Nfse><IdentificacaoNfse>"
            f"<NumeroRps>{original.rps_number}</NumeroRps>"
            f"<NumeroNfse>{invoice.invoice_number}</NumeroNfse>"
            f"<CodigoVerificacao>{invoice.verification_code}</CodigoVerificacao>"
            "</IdentificacaoNfse></Nfse></CancelaNfseResposta>"
        )
        soap = (
            '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:g="http://www.geisweb.com.br/"><soap:Body>'
            '<g:CancelaNfseResponse><g:CancelaNfseResult>'
            f"{escape(official_cancel)}"
            "</g:CancelaNfseResult></g:CancelaNfseResponse>"
            "</soap:Body></soap:Envelope>"
        ).encode()
        return interpret_cajamar_cancel_response(
            receipt=CajamarGeiswebResult(
                method="CancelaNfse", response_xml=soap,
            ),
            source=original, issued=invoice, verify_official_response=Mock(),
        )

    def recover(
        request: NfseAuthorizationRequest, original: Sp4OriginalRps,
    ) -> Sp4ProviderOutcome:
        invoice_number = str(8764 + int(original.rps_number))
        invoice = Sp4VerifiedInvoice(
            issuer_cnpj=original.issuer_cnpj,
            issuer_ibge=original.issuer_ibge,
            competence_date=original.competence_date,
            rps_number=original.rps_number,
            rps_series=original.rps_series,
            gross_amount=original.gross_amount,
            invoice_number=invoice_number,
            verification_code="ABCDEF1234",
            invoice_reference=invoice_number,
            authorized_xml=(
                "<ConsultaLoteRpsResposta><Rps><IdentificacaoNfse>"
                f"<NumeroRps>{original.rps_number}</NumeroRps>"
                f"<NumeroNfse>{invoice_number}</NumeroNfse>"
                "<CodigoVerificacao>ABCDEF1234</CodigoVerificacao>"
                "</IdentificacaoNfse><Competencia>2026-10</Competencia>"
                "<Servico><Valores><ValorServicos>100,00</ValorServicos></Valores>"
                "<PrestadorServico><IdentificacaoPrestador>"
                f"<CnpjCpf>{original.issuer_cnpj.value}</CnpjCpf>"
                "</IdentificacaoPrestador></PrestadorServico></Servico>"
                "</Rps></ConsultaLoteRpsResposta>"
            ).encode(),
        )
        return Sp4ProviderOutcome(
            status=AuthorizationStatus.AUTHORIZED, official_invoice=invoice,
        )

    queried = Mock(side_effect=recover)
    ports = Sp4ReviewedMunicipalPorts(
        load_original_rps=Mock(side_effect=AssertionError("alternative loader used")),
        fiscal_issuer_policy=Mock(),
        validate_prepared_rps=Mock(),
        submit_official_rps=submitted,
        query_official_rps=queried,
        verify_official_invoice_xml=verified,
    )
    handler_factory = build_runtime_fiscal_handler_factory(
        operations_gateway=FakeFiscalOperationsGateway(),
        sp4_reviewed_municipalities={_CAJAMAR_PROVIDER: ports},
        cajamar_verified_cancel=verified_cancel,
    )
    handlers = handler_factory(app)
    executable = CanonicalPortalOperationExecutor(
        unit_of_work_factory=db,
        path=CanonicalFiscalOperationPath(app, handlers=handlers),
    )
    web = _client(db, operation_executor=executable)
    payload = _payload() | _TAKER_ADDRESS | {
        "competence_date": "2026-10-31",
        "source_id": "cajamar-fully-exercised-portal",
    }
    prepared = _post(web, payload)
    assert prepared.status_code == 200, prepared.text
    document_id = prepared.json()["document_id"]
    original = app.load_sp4_original_rps(
        ExecutionScope(
            TENANT, UNIT, FiscalEnvironment.HOMOLOGATION, "lookup", "fm-nfcore",
        ), document_id,
    )
    assert original.rps_number == "1"

    csrf = web.cookies.get(CSRF_COOKIE)
    assert csrf
    body = {
        "unit_id": UNIT, "environment": "homologation", "document_id": document_id,
    }
    issued = web.post(
        "/v1/portal/operations/issueFiscalDocument",
        json=body, headers={CSRF_HEADER: csrf, "Idempotency-Key": "cajamar-first-post"},
    )
    assert issued.status_code == 200, issued.text
    assert submitted.call_count == 1
    queried.assert_not_called()

    completed = web.post(
        "/v1/portal/operations/reconcileFiscalOperation",
        json=body, headers={CSRF_HEADER: csrf, "Idempotency-Key": "cajamar-original-lot-query"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == FiscalDocumentState.AUTHORIZED.value
    assert submitted.call_count == 1, "read-only recovery must not submit again"
    queried.assert_called_once()
    verified.assert_called_once()
    # Reconciliation may retain attempt history, but must archive exactly one
    # authentic authorized XML. Duplicate archival entries break cancellation.
    prepared_request = app.load_prepared_nfse_authorization(
        original.scope, document_id,
    )
    with db() as uow:
        history = uow.idempotency.attempts(prepared_request.idempotency_key)
        one_xml = [
            e for e in uow.archive.list_for_document(original.scope, document_id)
            if e.kind is FiscalArchiveKind.AUTHORIZED_XML
        ]
        assert len(one_xml) == 1, "recovery must archive one official XML"
        assert history[-1].document_id == document_id
        assert history[-1].status.value == "authorized"

    download = web.get(
        f"/v1/portal/documents/{document_id}/artifacts/authorized_xml",
        params={"unit_id": UNIT, "environment": "homologation"},
    )
    assert download.status_code == 200, download.text
    assert download.content.startswith(b"<ConsultaLoteRpsResposta><Rps>")
    assert download.headers["Cache-Control"] == "no-store"
    listed = web.get(
        "/v1/portal/surfaces/documents",
        params={"unit_id": UNIT, "environment": "homologation"},
    )
    assert listed.status_code == 200, listed.text
    printed = [
        row for row in listed.json()["rows"]
        if row.get("record_type") == "archive"
        and row.get("document_reference") == document_id
        and row.get("kind") == "authorized_xml"
    ]
    assert len(printed) == 1
    assert printed[0]["auxiliary_pdf_available"] is False
    municipal_pdf = web.get(
        f"/v1/portal/documents/{document_id}/artifacts/auxiliary_pdf",
        params={"unit_id": UNIT, "environment": "homologation"},
    )
    assert municipal_pdf.status_code == 409
    denied = web.get(
        f"/v1/portal/documents/{document_id}/artifacts/authorized_xml",
        params={"unit_id": "another-unit", "environment": "homologation"},
    )
    assert denied.status_code == 403

    replay = web.post(
        "/v1/portal/operations/issueFiscalDocument",
        json=body, headers={CSRF_HEADER: csrf, "Idempotency-Key": "cajamar-first-post"},
    )
    assert replay.status_code == 200, replay.text
    assert submitted.call_count == 1

    # Municipal substitution is a human review of two durable fiscal records,
    # not a fictitious SOAP operation or a second automatic issuance.
    candidate = _post(
        web, payload | {"source_id": "cajamar-reviewed-replacement"},
        key="cajamar-substitution-candidate",
    )
    assert candidate.status_code == 200, candidate.text
    candidate_id = candidate.json()["document_id"]
    reviewed_payload = {
        "unit_id": UNIT, "environment": "homologation",
        "original_id": document_id, "replacement_id": candidate_id,
        "human_approval": True,
    }
    with patch("kordena_fiscal.runtime.canonical_fiscal_composition.datetime") as clock:
        clock.now.return_value = datetime(2026, 11, 5, tzinfo=UTC)
        reviewed = web.post(
            "/v1/portal/operations/reviewCajamarSubstitution",
            json=reviewed_payload, headers={CSRF_HEADER: csrf},
        )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "MUNICIPAL_PORTAL_SUBSTITUTION_REQUIRED"
    assert reviewed.json()["official_fiscal_confirmation"] is False
    assert reviewed.json()["deadline"] == "2026-11-10"
    assert submitted.call_count == 1
    with db() as uow:
        assert uow.lifecycle.get(document_id).state is FiscalDocumentState.AUTHORIZED
        assert uow.lifecycle.get(candidate_id).state is FiscalDocumentState.READY_TO_TRANSMIT
    expired_review = web.post(
        "/v1/portal/operations/reviewCajamarSubstitution",
        json=reviewed_payload, headers={CSRF_HEADER: csrf},
    )
    assert expired_review.status_code == 400

    with patch(
        "kordena_fiscal.application.service._cajamar_policy_now",
        return_value=datetime(2026, 11, 5, tzinfo=UTC),
    ):
        # Cancellation uses the same authenticated Portal, canonical RPS/archive,
        cancel_body = body | {"cancellation_reason": "duplicate_invoice"}
        # signed municipal contract port and durable fiscal lifecycle.
        unauthorized = web.post(
            "/v1/portal/operations/cancelCajamarNfse",
            json=cancel_body | {"human_approval": False},
            headers={CSRF_HEADER: csrf, "Idempotency-Key": "cajamar-not-approved"},
        )
        assert unauthorized.status_code in {400, 403, 409}
        cancelled.assert_not_called()
        request_cancel = web.post(
            "/v1/portal/operations/cancelCajamarNfse",
            json=cancel_body | {"human_approval": True},
            headers={CSRF_HEADER: csrf, "Idempotency-Key": "cajamar-cancel-one"},
        )
        assert request_cancel.status_code == 200, request_cancel.text
        assert request_cancel.json()["status"] == FiscalDocumentState.CANCELLED.value
        assert request_cancel.json()["official_fiscal_confirmation"] is True
        cancelled.assert_called_once()
        assert submitted.call_count == 1
        with db() as uow:
            events = [
                item for item in uow.archive.list_for_document(
                    original.scope, document_id,
                )
                if item.kind is FiscalArchiveKind.FISCAL_EVENT
            ]
            assert len(events) == 1
            assert events[0].content.startswith(b"<CancelaNfseResposta>")
            assert uow.lifecycle.get(document_id).state is FiscalDocumentState.CANCELLED
        duplicate = web.post(
            "/v1/portal/operations/cancelCajamarNfse",
            json=cancel_body | {"human_approval": True},
            headers={CSRF_HEADER: csrf, "Idempotency-Key": "cajamar-cancel-replayed"},
        )
        assert duplicate.status_code != 200
        cancelled.assert_called_once(), "Duplicate cancellation must never reach provider"

        # A network timeout after CANCEL_REQUESTED must not send CancelaNfse
        # again on another HTTP key. The original note stays under investigation.
        another = _post(
            web, payload | {"source_id": "cajamar-second-for-ambiguous-cancel"},
            key="cajamar-second-service-order",
        )
        assert another.status_code == 200, another.text
        second_id = another.json()["document_id"]
        second_body = body | {"document_id": second_id}
        second_issue = web.post(
            "/v1/portal/operations/issueFiscalDocument",
            json=second_body,
            headers={CSRF_HEADER: csrf, "Idempotency-Key": "cajamar-second-issue"},
        )
        assert second_issue.status_code == 200, second_issue.text
        second_reconcile = web.post(
            "/v1/portal/operations/reconcileFiscalOperation",
            json=second_body,
            headers={CSRF_HEADER: csrf, "Idempotency-Key": "cajamar-second-recovery"},
        )
        assert second_reconcile.status_code == 200, second_reconcile.text
        assert second_reconcile.json()["status"] == FiscalDocumentState.AUTHORIZED.value
        try:
            uncertain = web.post(
                "/v1/portal/operations/cancelCajamarNfse",
                json=second_body | {
                    "cancellation_reason": "duplicate_invoice",
                    "human_approval": True,
                },
                headers={CSRF_HEADER: csrf, "Idempotency-Key": "cajamar-second-cancel"},
            )
            assert uncertain.status_code >= 400
        except RuntimeError as exc:
            assert "synthetic transport timeout" in str(exc)
        with db() as uow:
            second_state = uow.lifecycle.get(second_id)
            assert second_state is not None
            assert second_state.state is FiscalDocumentState.CANCEL_REQUESTED
        replay_cancel = web.post(
            "/v1/portal/operations/cancelCajamarNfse",
            json=second_body | {"cancellation_reason": "duplicate_invoice", "human_approval": True},
            headers={CSRF_HEADER: csrf, "Idempotency-Key": "cajamar-second-cancel-new-key"},
        )
        assert replay_cancel.status_code != 200
        assert cancelled.call_count == 2, "Ambiguous cancel must not be re-posted"


def _synthetic_a1_for_native_issuer() -> EphemeralCertificateMaterial:
    """Ephemeral PKCS#12 fixture; never a real customer A1 or trusted authority."""
    password = b"synthetic-native-e2e-only"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    issuer = Cnpj("11222333000181")
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic A1 fixture")])
    encoded = issuer.value.encode("ascii")
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=False,
            crl_sign=False, encipher_only=False, decipher_only=False,
        ), critical=True)
        .add_extension(x509.SubjectAlternativeName([
            x509.OtherName(ObjectIdentifier("2.16.76.1.3.3"),
                           bytes([0x04, len(encoded)]) + encoded),
        ]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return EphemeralCertificateMaterial(
        reference_id="synthetic-only-native-e2e",
        pkcs12_bytes=pkcs12.serialize_key_and_certificates(
            name=b"synthetic-native", key=key, cert=certificate, cas=None,
            encryption_algorithm=serialization.BestAvailableEncryption(password),
        ),
        password=password,
    )


def test_web_native_nfse_preparation_to_signed_gateway_and_authorized_xml(
    tmp_path: Path,
) -> None:
    """HTTP Portal -> durable preparation -> DPS 1.01 -> fake SEFIN -> archive HTTP.

    This uses one canonical runtime path and an ephemeral synthetic A1; no
    external gateway, municipality authorization or customer cert is contacted.
    """
    db = _database(tmp_path / "native-e2e.sqlite")
    application = FiscalApplicationService(db)
    captured: list[bytes] = []
    key = "35" + "0" * 48
    official_xml = (
        '<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">'
        f'<infNFSe Id="NFS{key}"/></NFSe>'
    ).encode()

    def fake_sefin(payload: bytes, *_args: object) -> bytes:
        request = json.loads(payload)
        signed = gzip.decompress(base64.b64decode(request["dpsXmlGZipB64"]))
        national_dps_validator("1.01").validate_document(signed)
        root = etree.fromstring(signed)
        signature = root.find("{http://www.w3.org/2000/09/xmldsig#}Signature")
        assert signature is not None
        assert root.findtext(
            "{http://www.sped.fazenda.gov.br/nfse}infDPS/"
            "{http://www.sped.fazenda.gov.br/nfse}prest/"
            "{http://www.sped.fazenda.gov.br/nfse}CNPJ"
        ) == "11222333000181"
        captured.append(signed)
        return json.dumps({
            "tipoAmbiente": 2, "chaveAcesso": key, "idDps": "synthetic-native-e2e",
            "nfseXmlGZipB64": base64.b64encode(
                gzip.compress(official_xml, mtime=0)
            ).decode("ascii"),
        }).encode()

    a1 = _synthetic_a1_for_native_issuer()
    national = NfseNacionalHomologationGateway(
        resolve_certificate=lambda _scope, _cnpj: a1,
        build_signed_dps=build_signed_dps,
        exchange=fake_sefin,
    )
    governed = _GovernedNationalNfseGateway(
        application=application, preaudit=nfse_preaudit, gateway=national,
    )
    handlers = build_provider_operation_handlers(
        FiscalOperationsClient(FakeFiscalOperationsGateway()),
        application=application, prepared_nfse_gateway=NfseGatewayClient(governed),
        archive_retention=RetentionPolicyMetadata("nfcore-fiscal-archive", 1),
    )
    operation_executor = CanonicalPortalOperationExecutor(
        unit_of_work_factory=db,
        path=CanonicalFiscalOperationPath(application, handlers=handlers),
    )
    browser = _client(db, operation_executor=operation_executor)
    prepared = _post(browser, _payload())
    assert prepared.status_code == 200, prepared.text
    document_id = prepared.json()["document_id"]

    # No printable document may exist before the authorized XML is archived.
    not_yet = browser.get(
        f"/v1/portal/documents/{document_id}/artifacts/auxiliary_pdf",
        params={"unit_id": UNIT, "environment": "homologation"},
    )
    assert not_yet.status_code == 404

    csrf = browser.cookies.get(CSRF_COOKIE)
    assert csrf
    issue_body = {
        "unit_id": UNIT, "environment": "homologation", "document_id": document_id,
    }
    issued = browser.post(
        "/v1/portal/operations/issueFiscalDocument",
        json=issue_body,
        headers={CSRF_HEADER: csrf, "Idempotency-Key": "native-issue-1"},
    )
    assert issued.status_code == 200, issued.text
    assert issued.json()["status"] == FiscalDocumentState.AUTHORIZED.value
    assert len(captured) == 1

    downloaded = browser.get(
        f"/v1/portal/documents/{document_id}/artifacts/authorized_xml",
        params={"unit_id": UNIT, "environment": "homologation"},
    )
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == official_xml
    assert downloaded.headers["Cache-Control"] == "no-store"
    assert downloaded.headers["X-Content-Type-Options"] == "nosniff"
    projection = browser.get(
        "/v1/portal/surfaces/documents",
        params={"unit_id": UNIT, "environment": "homologation"},
    )
    assert projection.status_code == 200, projection.text
    national_artifacts = [
        row for row in projection.json()["rows"]
        if row.get("document_reference") == document_id
        and row.get("kind") == "authorized_xml"
    ]
    assert len(national_artifacts) == 1
    assert national_artifacts[0]["auxiliary_pdf_available"] is True
    assert downloaded.headers["Content-Disposition"].startswith("attachment;")
    assert downloaded.headers["Content-Type"].startswith("application/xml")

    # The default Portal runtime must serve PDF/DANFSe from the SAME archived
    # authorized XML, with an actual renderer wired, not a missing dependency.
    # A fake PDF factory isolates output layout; HTTP/identity/archive are real.
    with patch("brazilfiscalreport.danfse.Danfse") as pdf_renderer:
        pdf_renderer.return_value.output.return_value = b"%PDF-1.4\\nSYNTHETIC"
        pdf = browser.get(
            f"/v1/portal/documents/{document_id}/artifacts/auxiliary_pdf",
            params={"unit_id": UNIT, "environment": "homologation"},
        )
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b"%PDF-")
    assert pdf.headers["Content-Type"].startswith("application/pdf")
    assert pdf.headers["Content-Disposition"].startswith("inline;")
    assert pdf.headers["Cache-Control"] == "no-store"
    assert pdf_renderer.call_count == 1
    assert official_xml.decode("utf-8") == pdf_renderer.call_args.kwargs["xml"]

    # Artifact query is still bound to the authenticated user's unit.
    wrong_unit = browser.get(
        f"/v1/portal/documents/{document_id}/artifacts/auxiliary_pdf",
        params={"unit_id": "unrelated-unit", "environment": "homologation"},
    )
    assert wrong_unit.status_code == 403

    again = browser.post(
        "/v1/portal/operations/issueFiscalDocument",
        json=issue_body,
        headers={CSRF_HEADER: csrf, "Idempotency-Key": "native-issue-1"},
    )
    assert again.status_code == 200, again.text
    assert len(captured) == 1, "Replay must not retransmit the signed DPS"
    assert _post(browser, _payload(), "native-after-authorization").status_code == 200



def _official_osasco_manifest(tmp_path: Path) -> Path:
    """Operator manifest using exact public 2026 WSDL/XSD bytes, synthetic issuer."""
    origin = (
        Path(__file__).resolve().parents[2]
        / "contracts/official/osasco/homologation"
    )
    manifest = {
        "wsdl": {
            "file": "municipal.wsdl",
            "sha256": hashlib.sha256(
                (origin / "NotaFiscalEletronica.singleWsdl.xml").read_bytes(),
            ).hexdigest(),
        },
        "binding_name": "BasicHttpBinding_INotaFiscalEletronicaServico",
        "official_xsd_package": {},
        "issuers": [],
    }
    (tmp_path / "municipal.wsdl").write_bytes(
        (origin / "NotaFiscalEletronica.singleWsdl.xml").read_bytes(),
    )
    for number in range(6):
        filename = f"inline-xsd-{number:03}.xsd"
        raw = (origin / filename).read_bytes()
        (tmp_path / filename).write_bytes(raw)
        manifest["official_xsd_package"][filename] = {  # type: ignore[index]
            "file": filename, "sha256": hashlib.sha256(raw).hexdigest(),
        }
    policy = asdict(_osasco_synthetic_policy())
    for key, value in list(policy.items()):
        if isinstance(value, date):
            policy[key] = value.isoformat()
        elif isinstance(value, Decimal):
            policy[key] = str(value)
    manifest["issuers"] = [{
        "tenant_id": TENANT, "unit_id": UNIT,
        "issuer_cnpj": "11222333000181",
        "municipal_registration": "123456", "policy": policy,
    }]
    target = tmp_path / "osasco-official-synthetic-issuer.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return target


def _osasco_official_schema_soap(method: str, receipt: str) -> bytes:
    """Valid public WCF XSD element order, no real municipality interaction."""
    prefix = (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:t="http://tempuri.org/" '
        'xmlns:a="http://schemas.datacontract.org/2004/07/'
        'Eissnfe.Negocio.WebServices.Mensagem" '
        'xmlns:b="http://schemas.datacontract.org/2004/07/'
        'Eissnfe.Dominio.DataTransferObject.Prestador" '
        'xmlns:c="http://schemas.datacontract.org/2004/07/'
        'Eissnfe.Dominio.DataTransferObject.Contribuinte">'
    )
    response = (
        f"<s:Body><t:{method}Response><t:{method}Result>"
        "<a:Erro>false</a:Erro>"
    )
    if method == "ConsultarNotaCompleta":
        response += (
            "<a:NotasGeradas><b:NotaFiscalRelatorioDTO>"
            "<b:CodigoAutenticidade>OSASCO1234</b:CodigoAutenticidade>"
            f"<b:Numero>{8000 + int(receipt)}</b:Numero>"
            f"<b:NumeroRecibo>{receipt}</b:NumeroRecibo>"
            "<b:Prestador><c:CNPJ>11222333000181</c:CNPJ></b:Prestador>"
            "<b:Valor>100.00</b:Valor>"
            "</b:NotaFiscalRelatorioDTO></a:NotasGeradas>"
            "<a:QtdeNotas>1</a:QtdeNotas>"
        )
    return (
        prefix + response
        + f"</t:{method}Result></t:{method}Response></s:Body></s:Envelope>"
    ).encode()


def test_osasco_executable_api_real_xsd_end_to_end_one_uow(
    tmp_path: Path,
) -> None:
    """Portal→api:app factory→official WSDL/XSD→synthetic WCF→durable UoW.

    Every fiscal response is synthetic but checked against real official XSD.
    No taxpayer key, network issuance, external fiscal homologation or DDL.
    """
    manifest = _official_osasco_manifest(tmp_path)
    db = _database(
        tmp_path / "osasco-actual-entrypoint.sqlite",
        issuer_ibge="3534401", provider_id="osasco-rtc-homologation",
        tax_regime=TaxRegimeCode.NORMAL,
    )
    with db() as uow:
        uow.control_plane.add_secret_reference(SecretReference(
            reference_id="ref:osasco-fixture-key",
            kind=SecretReferenceKind.CREDENTIALS,
            tenant_id=TENANT, unit_id=UNIT,
            environment=FiscalEnvironment.HOMOLOGATION,
            provider_id="osasco-rtc-homologation",
        ))
        uow.commit()
    vault = Mock()
    vault.resolve.side_effect = lambda ref, context: EphemeralProviderCredentialsMaterial(
        reference_id=ref.reference_id,
        credential_bytes=b"12345678-1234-1234-1234-123456789012",
    )
    observed: list[tuple[str, str | None, str]] = []

    def synthetic_exchange(soap: bytes, action: str, _timeout: float) -> bytes:
        method = action.rsplit("/", 1)[-1]
        assert action.startswith("http://tempuri.org/INotaFiscalEletronicaServico/")
        root = etree.fromstring(soap)
        fields = {
            etree.QName(node).localname: node.text
            for node in root.iter() if isinstance(node.tag, str)
        }
        assert fields["ChaveAutenticacao"] == "12345678-1234-1234-1234-123456789012"
        receipt = fields.get("NumeroReciboUnico") or fields.get("NumeroRecibo") or "1"
        observed.append((method, fields.get("TipoCancelamento"), receipt))
        return _osasco_official_schema_soap(method, receipt)

    settings = RuntimeSettings.from_mapping({
        "NFCORE_ENVIRONMENT": "staging",
        "NFCORE_PERSISTENCE_BACKEND": "postgres",
        "DATABASE_URL": "postgresql://fake:fake@db/nfcore",
        "NFCORE_SECRET_BACKEND": "external",
    })
    with patch(
        "kordena_fiscal.gateway.osasco_rtc_homologation._exchange",
        synthetic_exchange,
    ):
        factory = build_entrypoint_fiscal_handler_factory(
            settings,
            {"NFCORE_OSASCO_WCF_CONFIG_PATH": str(manifest)},
            None,
            osasco_secret_vault=vault,
        )
        assert factory is not None
        application = FiscalApplicationService(db)
        handlers = factory(application)
        assert {
            "issueFiscalDocument", "reconcileFiscalOperation",
            "cancelOsascoNfse", "substituteOsascoNfse",
        } <= handlers.keys()
        web = _client(
            db, operation_executor=CanonicalPortalOperationExecutor(
                unit_of_work_factory=db,
                path=CanonicalFiscalOperationPath(application, handlers=handlers),
            ),
        )
        values = _payload() | _TAKER_ADDRESS | {
            "competence_date": "2026-11-12",
            "service_municipality_ibge": "3534401",
        }
        first = _post(web, values | {"source_id": "osasco-original"}, "prepare-original")
        second = _post(web, values | {"source_id": "osasco-replacement"}, "prepare-replace")
        assert first.status_code == second.status_code == 200
        original_id, replacement_id = (
            first.json()["document_id"], second.json()["document_id"]
        )
        csrf = web.cookies.get(CSRF_COOKIE)
        assert csrf
        headers = {CSRF_HEADER: csrf}
        base = {"unit_id": UNIT, "environment": "homologation"}

        def execute(operation: str, payload: dict[str, object], key: str):
            return web.post(
                f"/v1/portal/operations/{operation}",
                json=base | payload,
                headers=headers | {"Idempotency-Key": key},
            )

        issued = execute("issueFiscalDocument", {"document_id": original_id}, "issue-original")
        assert issued.status_code == 200, issued.text
        queried = execute(
            "reconcileFiscalOperation", {"document_id": original_id}, "query-original",
        )
        assert queried.status_code == 200, queried.text
        assert queried.json()["status"] == FiscalDocumentState.AUTHORIZED.value
        download = web.get(
            f"/v1/portal/documents/{original_id}/artifacts/authorized_xml",
            params=base,
        )
        assert download.status_code == 200
        assert b"OSASCO1234" in download.content
        cancel = execute(
            "substituteOsascoNfse",
            {"original_id": original_id, "replacement_id": replacement_id,
             "human_approval": True, "cancellation_reason": "Substituicao revisada"},
            "cancel-type-s",
        )
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()["original_status"] == FiscalDocumentState.CANCELLED.value
        assert cancel.json()["next_action"] == "issueFiscalDocument"
        retry = execute(
            "substituteOsascoNfse",
            {"original_id": original_id, "replacement_id": replacement_id,
             "human_approval": True, "cancellation_reason": "Substituicao revisada"},
            "cancel-type-s",
        )
        assert retry.status_code == 200
        assert sum(method == "Cancelar" for method, _, _ in observed) == 1
        next_issue = execute(
            "issueFiscalDocument", {"document_id": replacement_id}, "issue-replace",
        )
        assert next_issue.status_code == 200, next_issue.text
        next_query = execute(
            "reconcileFiscalOperation", {"document_id": replacement_id}, "query-replace",
        )
        assert next_query.status_code == 200, next_query.text
        assert next_query.json()["status"] == FiscalDocumentState.AUTHORIZED.value
        assert [(method, cancel_type) for method, cancel_type, _ in observed] == [
            ("RTC_EmitirNFE", None),
            ("ConsultarNotaCompleta", None),
            ("Cancelar", "S"),
            ("RTC_EmitirNFE", None),
            ("ConsultarNotaCompleta", None),
        ]
        scope = ExecutionScope(
            TENANT, UNIT, FiscalEnvironment.HOMOLOGATION, "proof", "fm-nfcore",
        )
        assert (
            application.load_sp4_original_rps(scope, original_id).rps_number == "1"
        )
        assert (
            application.load_sp4_original_rps(scope, replacement_id).rps_number == "2"
        )
        assert vault.resolve.call_count == 5


def _synthetic_barueri_manifest(tmp_path: Path) -> Path:
    """Operator manifest with artificial files/issuer; never external homologation."""
    xsd = (
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:element name="NotaFiscal"><xs:complexType><xs:all>'
        + "".join(
            f'<xs:element name="{name}" type="xs:string"/>'
            for name in (
                "issuer_cnpj", "invoice_number", "verification_code",
                "invoice_reference", "rps_number", "gross_amount",
                "invoice_issued_on", "invoice_series",
            )
        )
        + '</xs:all></xs:complexType></xs:element></xs:schema>'
    ).encode()
    data: dict[str, object] = {
        "mode": "reviewed-homologation",
        "layout": "PMB004-v4.4",
        "invoice_tags": {
            field: field for field in (
                "issuer_cnpj", "invoice_number", "verification_code",
                "invoice_reference", "rps_number", "gross_amount",
                "invoice_issued_on", "invoice_series",
            )
        },
        "issuers": [{
            "tenant_id": TENANT, "unit_id": UNIT,
            "issuer_cnpj": "11222333000181",
            "profile_id": "issuer-native",
            "profile_version": 1, "tax_regime": TaxRegimeCode.NORMAL.value,
            "municipal_registration": "1234567",
            "effective_from": "2026-01-01", "effective_through": None,
            "canonical_service_code": "0107",
            "pmb004_service_code": "000000107",
            "service_location_code": "1", "public_way_code": "2",
            "nbs_code": "000000001", "operation_indicator": "000001",
            "tax_classification": "000001", "ibs_cbs_status": "000",
            "simples_assessment": "", "municipal_note_series": "",
            "personal_use": "0", "recipient_differs": "0",
            "recipient_emails": {
                "12345678000195": "synthetic-buyer@example.invalid",
            },
            "non_base_allowed": False,
        }],
    }
    for key, content in (
        ("rps_layout", b"%PDF-1.4 synthetic-only PMB004 v4.4"),
        ("return_layout", b"%PDF-1.4 synthetic-only ExportaNFe v3"),
        ("invoice_xsd", xsd),
    ):
        file = tmp_path / (key + (".xsd" if key == "invoice_xsd" else ".pdf"))
        file.write_bytes(content)
        data[key] = {"file": file.name, "sha256": hashlib.sha256(content).hexdigest()}
    target = tmp_path / "barueri-reviewed-fixture.json"
    target.write_text(json.dumps(data), encoding="utf-8")
    return target


def _synthetic_barueri_export(rps_file: bytes, *, cancelled: bool) -> bytes:
    """ExportaNFe v3 physical return using the actual on-wire original RPS."""
    lines = rps_file.split(b"\r\n")
    detail = lines[1]
    remittance = lines[0][14:25]
    assert detail[39:40] in (b"E", b"C")
    number = detail[15:25] if not cancelled else b"0000000001"
    amount = detail[463:478]
    head = b"1" + b"1234567" + b" " * 16 + b"PMB003" + remittance
    note = bytearray(b" " * 1678)
    note[:1] = b"2"
    note[1:5] = b"NF  "
    note[5:12] = b"0008765"
    note[12:20] = b"20261031"
    note[20:26] = b"120000"
    note[26:50] = b"AUTHCODE1234567890".ljust(24)
    note[50:54] = b"    "
    note[54:64] = number
    note[64:65] = b"1"
    note[65:66] = b"N"
    note[66:67] = b"C" if cancelled else b"A"
    if cancelled:
        note[67:75] = b"20261114"
    note[1628:1678] = b"35" + b"0" * 48
    item = bytearray(b" " * 95)
    item[0:1] = b"3"
    item[1:7] = b"000001"
    item[67:76] = b"000000107"
    item[76:91] = amount
    item[91:95] = b"0300"
    footer = b"90000004" + amount + b"0" * 15
    return b"\r\n".join((head, bytes(note), bytes(item), footer)) + b"\r\n"


def _synthetic_barueri_soap(
    method: str, *, protocol: str, return_file: bytes | None = None,
) -> bytes:
    namespace = "http://www.barueri.sp.gov.br/nfe"
    extra = (
        "<b:NomeArqRetorno>return.txt</b:NomeArqRetorno>"
        if method != "NFeLoteEnviarArquivo" else ""
    )
    if return_file is not None:
        extra += (
            "<b:ArquivoRPSBase64>"
            + base64.b64encode(return_file).decode("ascii")
            + "</b:ArquivoRPSBase64>"
        )
    return (
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:b="{namespace}"><soap:Body>'
        f"<b:{method}Response><b:{method}Result>"
        "<b:ListaMensagemRetorno><b:Codigo>OK200</b:Codigo>"
        "</b:ListaMensagemRetorno>"
        f"<b:ProtocoloRemessa>{protocol}</b:ProtocoloRemessa>"
        "<b:SituacaoArq>1</b:SituacaoArq>" + extra
        + f"</b:{method}Result></b:{method}Response>"
        "</soap:Body></soap:Envelope>"
    ).encode()


def _synthetic_barueri_substitution_export(
    original_file: bytes, event_file: bytes,
) -> bytes:
    """Official-v3-shaped two-note fixture: old C plus independent new A."""
    old = _synthetic_barueri_export(
        original_file, cancelled=True,
    ).split(b"\r\n")
    new = _synthetic_barueri_export(
        event_file, cancelled=False,
    ).split(b"\r\n")
    adjusted = bytearray(new[1])
    adjusted[5:12] = b"0008766"
    adjusted[26:50] = b"AUTHCODE1234567891".ljust(24)
    adjusted[1628:1678] = b"35" + b"0" * 47 + b"1"
    original_cents = int(old[2][76:91])
    substitute_cents = int(new[2][76:91])
    footer = (
        b"9" + b"0000006"
        + f"{original_cents + substitute_cents:015d}".encode("ascii")
        + b"0" * 15
    )
    return b"\r\n".join((
        new[0], old[1], old[2], bytes(adjusted), new[2], footer,
    )) + b"\r\n"


@pytest.mark.parametrize("substitute", [False, True])
def test_barueri_api_entrypoint_portal_issue_reconcile_cancel_replay_and_archive(
    tmp_path: Path, substitute: bool,
) -> None:
    """One portal/API/UoW and real fixed-width driver; mocked municipal I/O only."""
    manifest = _synthetic_barueri_manifest(tmp_path)
    db = _database(
        tmp_path / "barueri-end-to-end.sqlite", issuer_ibge="3505708",
        provider_id="barueri-pmb004-homologation", tax_regime=TaxRegimeCode.NORMAL,
    )
    vault = EncryptedA1Vault(
        directory=tmp_path / "synthetic-vault", master_key=b"\x00" * 32,
    )
    vault.resolve = Mock(return_value=_synthetic_a1_for_native_issuer())
    application = FiscalApplicationService(db)
    sent: list[bytes] = []
    calls: list[str] = []

    def exchange(soap: bytes, action: str, _tls: object, _timeout: float) -> bytes:
        method = action.strip('"').rsplit("/", 1)[-1]
        calls.append(method)
        xml = etree.fromstring(soap)
        inner_text = xml.xpath("//*[local-name()='MensagemXML']")[0].text
        assert isinstance(inner_text, str)
        fields = etree.fromstring(inner_text.encode())
        if method == "NFeLoteEnviarArquivo":
            encoded = fields.findtext("{http://www.barueri.sp.gov.br/nfe}ArquivoRPSBase64")
            assert encoded
            sent.append(base64.b64decode(encoded, validate=True))
        assert sent
        is_cancel = sent[-1].split(b"\r\n")[1][39:40] == b"C"
        protocol = "CANCEL1" if is_cancel else "ISSUE1"
        if method == "NFeLoteBaixarArquivo":
            return _synthetic_barueri_soap(
                method, protocol=protocol,
                return_file=(
                    _synthetic_barueri_substitution_export(sent[0], sent[-1])
                    if is_cancel and substitute
                    else _synthetic_barueri_export(sent[-1], cancelled=is_cancel)
                ),
            )
        return _synthetic_barueri_soap(method, protocol=protocol)

    def invoice_xml(url: str, _timeout: float) -> bytes:
        assert url.startswith("https://testeeiss.barueri.sp.gov.br/nfe/xmlNFe.ashx?")
        new = "numdoc=0008766" in url
        number = "0008766" if new else "0008765"
        code = "AUTHCODE1234567891" if new else "AUTHCODE1234567890"
        rps = "2" if new else "1"
        amount = "130.00" if new else "100.00"
        reference = "35" + "0" * (47 if new else 48) + ("1" if new else "")
        return (
            b"<NotaFiscal>"
            b"<issuer_cnpj>11222333000181</issuer_cnpj>"
            + f"<invoice_number>{number}</invoice_number>".encode()
            + f"<verification_code>{code}</verification_code>".encode()
            + f"<invoice_reference>{reference}".encode()
            + b"</invoice_reference>"
            + f"<rps_number>{rps}</rps_number>".encode()
            + f"<gross_amount>{amount}</gross_amount>".encode()
            + b"<invoice_issued_on>2026-10-31</invoice_issued_on>"
            b"<invoice_series>NF</invoice_series></NotaFiscal>"
        )

    settings = RuntimeSettings.from_mapping({
        "NFCORE_ENVIRONMENT": "staging",
        "NFCORE_PERSISTENCE_BACKEND": "postgres",
        "DATABASE_URL": "postgresql://fake:fake@db/nfcore",
        "NFCORE_SECRET_BACKEND": "external",
    })
    assert BarueriReviewedStartup.load(str(manifest)).policies
    with patch(
        "kordena_fiscal.gateway.barueri_pmb004_homologation._exchange",
        exchange,
    ), patch(
        "kordena_fiscal.gateway.barueri_official_invoice_xml._exchange",
        invoice_xml,
    ):
        factory = build_entrypoint_fiscal_handler_factory(
            settings, {"NFCORE_BARUERI_PMB004_CONFIG_PATH": str(manifest)}, vault,
        )
        assert factory is not None
        handlers = factory(application)
        assert {
            "issueFiscalDocument", "reconcileFiscalOperation",
            "cancelBarueriNfse", "substituteBarueriNfse",
            "reconcileBarueriNfseCancellation",
        } <= handlers.keys()
        web = _client(db, operation_executor=CanonicalPortalOperationExecutor(
            unit_of_work_factory=db,
            path=CanonicalFiscalOperationPath(application, handlers=handlers),
        ))
        payload = _payload() | _TAKER_ADDRESS | {
            "source_id": "barueri-http-complete",
            "competence_date": "2026-10-31",
            "service_municipality_ibge": "3505708",
        }
        prepared = _post(web, payload, "barueri-http-prepare")
        assert prepared.status_code == 200, prepared.text
        document_id = prepared.json()["document_id"]
        scope = ExecutionScope(
            TENANT, UNIT, FiscalEnvironment.HOMOLOGATION, "barueri-proof", "fm-nfcore",
        )
        original = application.load_sp4_original_rps(scope, document_id)
        assert original.municipal_batch_id == "00000000001"
        csrf = web.cookies.get(CSRF_COOKIE)
        assert csrf
        common = {"unit_id": UNIT, "environment": "homologation"}
        def operation(name: str, details: dict[str, object], key: str):
            return web.post(
                "/v1/portal/operations/" + name, json=common | details,
                headers={CSRF_HEADER: csrf, "Idempotency-Key": key},
            )
        issued = operation(
            "issueFiscalDocument", {"document_id": document_id}, "barueri-http-issue",
        )
        assert issued.status_code == 200, issued.text
        assert issued.json()["status"] == FiscalDocumentState.TRANSMITTING.value
        assert calls.count("NFeLoteEnviarArquivo") == 1
        assert application.load_barueri_remittance_protocol(scope, document_id) == "ISSUE1"
        done = operation(
            "reconcileFiscalOperation", {"document_id": document_id},
            "barueri-http-reconcile",
        )
        assert done.status_code == 200, done.text
        assert done.json()["status"] == FiscalDocumentState.AUTHORIZED.value
        assert calls.count("NFeLoteEnviarArquivo") == 1
        official = web.get(
            f"/v1/portal/documents/{document_id}/artifacts/authorized_xml",
            params=common,
        )
        assert official.status_code == 200, official.text
        assert official.content.startswith(b"<NotaFiscal>")
        with db() as uow:
            entries = uow.archive.list_for_document(scope, document_id)
            assert len([v for v in entries if v.kind is FiscalArchiveKind.AUTHORIZED_XML]) == 1
            assert uow.lifecycle.get(document_id).state is FiscalDocumentState.AUTHORIZED
        replay = operation(
            "issueFiscalDocument", {"document_id": document_id}, "barueri-http-issue",
        )
        assert replay.status_code == 200, replay.text
        assert calls.count("NFeLoteEnviarArquivo") == 1
        candidate_id: str | None = None
        if substitute:
            fresh = _post(web, payload | {
                "source_id": "barueri-reviewed-substitute",
                "gross_amount": "130.00", "iss_amount": "3.90",
            }, key="barueri-prepare-substitute")
            assert fresh.status_code == 200, fresh.text
            candidate_id = fresh.json()["document_id"]
        event_name = "substituteBarueriNfse" if substitute else "cancelBarueriNfse"
        event_data: dict[str, object] = (
            {"original_id": document_id, "replacement_id": candidate_id,
             "substitution_justification_code": "9",
             "cancellation_reason": "Substituicao sintetica",
             "human_approval": True}
            if substitute else
            {"document_id": document_id, "reason_code": "01",
             "cancellation_reason": "Servico cancelado sinteticamente",
             "human_approval": True}
        )
        denied = operation(
            event_name, {
                **event_data, "human_approval": False,
            }, "barueri-unapproved",
        )
        assert denied.status_code in (400, 403, 409)
        cancelled = operation(
            event_name, event_data, "barueri-cancel"
        )
        assert cancelled.status_code == 200, cancelled.text
        if substitute:
            assert cancelled.json()["original_status"] == (
                FiscalDocumentState.CANCEL_REQUESTED.value
            )
            assert cancelled.json()["replacement_status"] == (
                FiscalDocumentState.TRANSMITTING.value
            )
        else:
            assert cancelled.json()["status"] == (
                FiscalDocumentState.CANCEL_REQUESTED.value
            )
        assert calls.count("NFeLoteEnviarArquivo") == 2
        event_detail = sent[-1].split(b"\r\n")[1]
        assert event_detail[39:40] == b"C"
        if substitute:
            assert event_detail[40:42] == b"03"
            assert event_detail[513:514] == b"9"
        confirmed = operation(
            "reconcileBarueriNfseCancellation",
            {"document_id": document_id}, "barueri-reconcile-cancel",
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == FiscalDocumentState.CANCELLED.value
        assert confirmed.json()["official_fiscal_confirmation"] is True
        assert calls.count("NFeLoteEnviarArquivo") == 2
        with db() as uow:
            entries = uow.archive.list_for_document(scope, document_id)
            assert len([v for v in entries if v.kind is FiscalArchiveKind.FISCAL_EVENT]) == 1
            assert uow.lifecycle.get(document_id).state is FiscalDocumentState.CANCELLED
            if substitute:
                assert candidate_id is not None
                assert uow.lifecycle.get(candidate_id).state is FiscalDocumentState.AUTHORIZED
                substitute_xml = [
                    e for e in uow.archive.list_for_document(scope, candidate_id)
                    if e.kind is FiscalArchiveKind.AUTHORIZED_XML
                ]
                assert len(substitute_xml) == 1
                assert b"0008766" in substitute_xml[0].content
        duplicate = operation(
            event_name, event_data, "barueri-second-cancel",
        )
        assert duplicate.status_code != 200
        assert calls.count("NFeLoteEnviarArquivo") == 2
        replay_recovery = operation(
            "reconcileBarueriNfseCancellation",
            {"document_id": document_id}, "barueri-reconcile-cancel-again",
        )
        assert replay_recovery.status_code == 200, replay_recovery.text
        assert replay_recovery.json()["replay"] is True
        assert calls.count("NFeLoteEnviarArquivo") == 2


def test_jundiai_http_portal_durable_rps_pending_recovery_archive_and_isolation(
    tmp_path: Path,
) -> None:
    """Real HTTP/CSRF/session -> SQLite/UoW -> SP4 bridge with synthetic provider.

    Does not certify live Giss WSDL or the municipality's invoice XML signature;
    the Giss request serialization itself is audited against official XSD by
    scripts/audit/jundiai_test_xml_against_official.py.
    """
    db_path = tmp_path / "jundiai-http-durable.sqlite"
    db = _database(
        db_path, issuer_ibge="3525904",
        provider_id="jundiai-giss-v2-homologation",
        tax_regime=TaxRegimeCode.NORMAL,
    )
    application = FiscalApplicationService(db)
    submits: list[Sp4OriginalRps] = []
    queries: list[Sp4OriginalRps] = []
    verified = Mock()
    polling = [False, True]

    def submit(
        request: NfseAuthorizationRequest, original: Sp4OriginalRps,
    ) -> Sp4ProviderOutcome:
        assert request.request_fingerprint == original.request_fingerprint
        assert original.issuer_ibge == "3525904"
        assert original.municipal_batch_id is not None
        assert original.rps_series == "R1"
        submits.append(original)
        return Sp4ProviderOutcome(
            status=AuthorizationStatus.PENDING, provider_request_id="synthetic-batch-42",
        )

    def recover(
        request: NfseAuthorizationRequest, original: Sp4OriginalRps,
    ) -> Sp4ProviderOutcome:
        assert request.request_fingerprint == original.request_fingerprint
        queries.append(original)
        if not polling.pop(0):
            return Sp4ProviderOutcome(status=AuthorizationStatus.PENDING)
        verified_invoice = Sp4VerifiedInvoice(
            issuer_cnpj=original.issuer_cnpj, issuer_ibge=original.issuer_ibge,
            competence_date=original.competence_date,
            rps_number=original.rps_number, rps_series=original.rps_series,
            gross_amount=original.gross_amount, invoice_number="8765",
            verification_code="SYNTHETIC42", invoice_reference="8765",
            authorized_xml=b"<SyntheticJundiaiInvoice>8765</SyntheticJundiaiInvoice>",
        )
        return Sp4ProviderOutcome(
            status=AuthorizationStatus.AUTHORIZED, official_invoice=verified_invoice,
        )

    ports = Sp4ReviewedMunicipalPorts(
        load_original_rps=Mock(
            side_effect=AssertionError("non-canonical municipality RPS loader used")
        ),
        fiscal_issuer_policy=Mock(), validate_prepared_rps=Mock(),
        submit_official_rps=submit, query_official_rps=recover,
        verify_official_invoice_xml=verified,
    )
    factory = build_runtime_fiscal_handler_factory(
        operations_gateway=FakeFiscalOperationsGateway(),
        sp4_reviewed_municipalities={"jundiai-giss-v2-homologation": ports},
    )
    handlers = factory(application)
    runtime = CanonicalPortalOperationExecutor(
        unit_of_work_factory=db,
        path=CanonicalFiscalOperationPath(application, handlers=handlers),
    )
    web = _client(db, operation_executor=runtime)
    original_payload = _payload() | _TAKER_ADDRESS | {
        "service_municipality_ibge": "3525904",
        "competence_date": "2026-11-12",
        "source_id": "jundiai-http-verified-2026",
    }

    prepared = _post(web, original_payload, "jundiai-prepare")
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["numbering_authority"] == "municipal_rps_durable"
    identifier = prepared.json()["document_id"]
    assert _post(web, original_payload, "jundiai-second-preparation-key").json()["replay"]
    scope = ExecutionScope(
        TENANT, UNIT, FiscalEnvironment.HOMOLOGATION, "jundiai-db-audit", "fm-nfcore",
    )
    persisted = FiscalApplicationService(
        SqliteFiscalDatabase(db_path)
    ).load_sp4_original_rps(scope, identifier)
    assert persisted.issuer_ibge == "3525904"
    assert persisted.rps_number == "1"
    assert persisted.rps_series == "R1"
    assert persisted.municipal_batch_id is not None
    with pytest.raises((PersistenceConflictError, PersistenceStateError)):
        application.load_sp4_original_rps(ExecutionScope(
            "foreign-tenant", UNIT, FiscalEnvironment.HOMOLOGATION,
            "foreign-audit", "fm-nfcore",
        ), identifier)

    body = {
        "unit_id": UNIT, "environment": "homologation",
        "document_id": identifier,
    }
    csrf = web.cookies.get(CSRF_COOKIE)
    assert csrf is not None
    issue_url = "/v1/portal/operations/issueFiscalDocument"
    assert web.post(issue_url, json=body).status_code == 403
    assert web.post(
        issue_url, json=body | {"tenant_id": "foreign-tenant"},
        headers={CSRF_HEADER: csrf, "Idempotency-Key": "bad-tenant"},
    ).status_code in (400, 403)

    issued = web.post(issue_url, json=body, headers={
        CSRF_HEADER: csrf, "Idempotency-Key": "jundiai-one-soap-post",
    })
    assert issued.status_code == 200, issued.text
    assert len(submits) == 1
    assert queries == []

    reconcile_url = "/v1/portal/operations/reconcileFiscalOperation"
    first = web.post(reconcile_url, json=body, headers={
        CSRF_HEADER: csrf, "Idempotency-Key": "jundiai-lookup-pending",
    })
    assert first.status_code == 200, first.text
    assert first.json()["status"] != FiscalDocumentState.AUTHORIZED.value
    assert len(submits) == 1
    second = web.post(reconcile_url, json=body, headers={
        CSRF_HEADER: csrf, "Idempotency-Key": "jundiai-lookup-authorized",
    })
    assert second.status_code == 200, second.text
    assert second.json().get("status") == FiscalDocumentState.AUTHORIZED.value, second.text
    assert len(submits) == 1
    assert len(queries) == 2
    same_poll = web.post(reconcile_url, json=body, headers={
        CSRF_HEADER: csrf, "Idempotency-Key": "jundiai-lookup-authorized",
    })
    assert same_poll.status_code == 200, same_poll.text
    assert same_poll.json()["replay"] is True
    assert same_poll.json()["operation_result"]["status"] == "authorized"
    assert len(queries) == 2
    verified.assert_called_once()
    archive = web.get(
        f"/v1/portal/documents/{identifier}/artifacts/authorized_xml",
        params={"unit_id": UNIT, "environment": "homologation"},
    )
    assert archive.status_code == 200, archive.text
    assert archive.content == b"<SyntheticJundiaiInvoice>8765</SyntheticJundiaiInvoice>"
    replay = web.post(issue_url, json=body, headers={
        CSRF_HEADER: csrf, "Idempotency-Key": "jundiai-one-soap-post",
    })
    assert replay.status_code == 200, replay.text
    assert len(submits) == 1, "replay cannot trigger a duplicate municipal POST"
    second_key_same_invoice = web.post(issue_url, json=body, headers={
        CSRF_HEADER: csrf, "Idempotency-Key": "different-key-same-issued-rps",
    })
    assert second_key_same_invoice.status_code == 200, second_key_same_invoice.text
    assert second_key_same_invoice.json()["replay"] is True
    assert len(submits) == 1, "a second issue key must not retransmit the same RPS"

def test_barueri_http_portal_issue_recover_and_authorized_xml(
    tmp_path: Path,
) -> None:
    """Use the real authenticated Portal, durable original and archive; synthetic provider."""
    db = _database(
        tmp_path / "barueri-e2e.sqlite", issuer_ibge="3505708",
        provider_id="barueri-pmb004-homologation",
        tax_regime=TaxRegimeCode.NORMAL,
    )
    application = FiscalApplicationService(db)
    submit = Mock(return_value=Sp4ProviderOutcome(
        status=AuthorizationStatus.PENDING,
        provider_request_id="BARUERI01",
    ))
    validate_invoice = Mock()

    def read_authorized(
        request: NfseAuthorizationRequest, original: Sp4OriginalRps,
    ) -> Sp4ProviderOutcome:
        assert original.issuer_ibge == "3505708"
        assert original.rps_number == "1"
        assert original.municipal_batch_id == "00000000001"
        assert request.request_fingerprint == original.request_fingerprint
        return Sp4ProviderOutcome(
            status=AuthorizationStatus.AUTHORIZED,
            official_invoice=Sp4VerifiedInvoice(
                issuer_cnpj=original.issuer_cnpj,
                issuer_ibge=original.issuer_ibge,
                competence_date=original.competence_date,
                rps_number=original.rps_number,
                rps_series=original.rps_series,
                gross_amount=original.gross_amount,
                invoice_number="1001001",
                verification_code="BARUERI-TEST-01",
                invoice_reference="3505708-BARUERI-TEST-01",
                authorized_xml=b"<BarueriOfficialSynthetic>1001001</BarueriOfficialSynthetic>",
            ),
        )

    query = Mock(side_effect=read_authorized)
    ports = Sp4ReviewedMunicipalPorts(
        load_original_rps=Mock(side_effect=AssertionError("noncanonical loader")),
        fiscal_issuer_policy=Mock(), validate_prepared_rps=Mock(),
        submit_official_rps=submit, query_official_rps=query,
        verify_official_invoice_xml=validate_invoice,
    )
    handlers = build_runtime_fiscal_handler_factory(
        operations_gateway=FakeFiscalOperationsGateway(),
        sp4_reviewed_municipalities={"barueri-pmb004-homologation": ports},
    )(application)
    web = _client(db, operation_executor=CanonicalPortalOperationExecutor(
        unit_of_work_factory=db,
        path=CanonicalFiscalOperationPath(application, handlers=handlers),
    ))
    fields = _payload() | _TAKER_ADDRESS | {
        "competence_date": "2026-10-31",
        "source_id": "barueri-http-original",
        "service_municipality_ibge": "3505708",
    }
    first = _post(web, fields, key="barueri-prepared")
    assert first.status_code == 200, first.text
    identifier = first.json()["document_id"]
    csrf = web.cookies.get(CSRF_COOKIE)
    assert csrf
    command = {
        "unit_id": UNIT, "environment": "homologation", "document_id": identifier,
    }
    sent = web.post(
        "/v1/portal/operations/issueFiscalDocument",
        json=command, headers={CSRF_HEADER: csrf, "Idempotency-Key": "issue-barueri"},
    )
    assert sent.status_code == 200, sent.text
    assert submit.call_count == 1
    assert query.call_count == 0
    result = web.post(
        "/v1/portal/operations/reconcileFiscalOperation",
        json=command, headers={CSRF_HEADER: csrf, "Idempotency-Key": "poll-barueri"},
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == FiscalDocumentState.AUTHORIZED.value
    submit.assert_called_once()
    query.assert_called_once()
    validate_invoice.assert_called_once()
    archive = web.get(
        f"/v1/portal/documents/{identifier}/artifacts/authorized_xml",
        params={"unit_id": UNIT, "environment": "homologation"},
    )
    assert archive.status_code == 200, archive.text
    assert archive.content == b"<BarueriOfficialSynthetic>1001001</BarueriOfficialSynthetic>"
    repeated = web.post(
        "/v1/portal/operations/issueFiscalDocument",
        json=command, headers={CSRF_HEADER: csrf, "Idempotency-Key": "issue-barueri"},
    )
    assert repeated.status_code == 200, repeated.text
    submit.assert_called_once()
    # A separately authenticated tenant-scope cannot retrieve this fiscal archive.
    from kordena_fiscal.persistence.ports import PersistenceConflictError
    different_tenant = ExecutionScope(
        "unrelated-tenant", UNIT, FiscalEnvironment.HOMOLOGATION, "probe", "fm-nfcore",
    )
    with pytest.raises((PersistenceConflictError, PersistenceStateError, FiscalValidationError)):
        application.load_sp4_original_rps(different_tenant, identifier)


@pytest.mark.parametrize(("substitution", "cancel_confirmed"), [(False, False), (True, True)])
def test_jundiai_http_cancel_or_substitute_officially_scoped_and_idempotent(
    tmp_path: Path, substitution: bool, cancel_confirmed: bool,
) -> None:
    """Synthetic GISS response proves HTTP/UoW controls, not municipal atomic substitution."""
    from kordena_fiscal.gateway.jundiai_giss_cancellation_result import (
        JundiaiGissCancellationDecision,
    )
    from kordena_fiscal.gateway.jundiai_giss_homologation import (
        JundiaiGissHomologationTransport,
    )
    from kordena_fiscal.runtime.jundiai_cancel_handlers import (
        build_jundiai_event_handlers,
    )
    from kordena_fiscal.runtime.jundiai_operational_composition import (
        JundiaiTrustedRuntimePorts,
    )

    db = _database(
        tmp_path / ("jundiai-substitute.sqlite" if substitution else "jundiai-cancel.sqlite"),
        issuer_ibge="3525904", provider_id="jundiai-giss-v2-homologation",
        tax_regime=TaxRegimeCode.NORMAL,
    )
    application = FiscalApplicationService(db)
    posted = Mock(return_value=Sp4ProviderOutcome(
        status=AuthorizationStatus.PENDING, provider_request_id="GISS-LOT-01",
    ))

    def confirmed_invoice(
        request: NfseAuthorizationRequest, original: Sp4OriginalRps,
    ) -> Sp4ProviderOutcome:
        ns = "http://www.giss.com.br/consultar-nfse-rps-resposta-v2_04.xsd"
        types = "http://www.giss.com.br/tipos-v2_04.xsd"
        xml = (
            f'<ConsultarNfseRpsResposta xmlns="{ns}" xmlns:t="{types}">'
            '<t:CompNfse><t:Nfse><t:InfNfse>'
            '<t:Numero>8765</t:Numero><t:CodigoVerificacao>GISS-TEST-01</t:CodigoVerificacao>'
            f'<t:OrgaoGerador><t:CodigoMunicipio>{original.issuer_ibge}</t:CodigoMunicipio></t:OrgaoGerador>'
            '<t:PrestadorServico><t:IdentificacaoPrestador><t:CpfCnpj>'
            f'<t:Cnpj>{original.issuer_cnpj.value}</t:Cnpj>'
            '</t:CpfCnpj></t:IdentificacaoPrestador></t:PrestadorServico>'
            '<t:DeclaracaoPrestacaoServico><t:InfDeclaracaoPrestacaoServico>'
            '<t:Rps><t:IdentificacaoRps>'
            f'<t:Numero>{original.rps_number}</t:Numero><t:Serie>{original.rps_series}</t:Serie>'
            '</t:IdentificacaoRps></t:Rps>'
            f'<t:Competencia>{original.competence_date.isoformat()}</t:Competencia>'
            '<t:Prestador><t:CpfCnpj>'
            f'<t:Cnpj>{original.issuer_cnpj.value}</t:Cnpj>'
            '</t:CpfCnpj></t:Prestador><t:Servico><t:Valores>'
            f'<t:ValorServicos>{original.gross_amount:.2f}</t:ValorServicos>'
            '</t:Valores></t:Servico></t:InfDeclaracaoPrestacaoServico>'
            '</t:DeclaracaoPrestacaoServico></t:InfNfse></t:Nfse></t:CompNfse>'
            '</ConsultarNfseRpsResposta>'
        ).encode()
        return Sp4ProviderOutcome(
            status=AuthorizationStatus.AUTHORIZED,
            official_invoice=Sp4VerifiedInvoice(
                issuer_cnpj=original.issuer_cnpj,
                issuer_ibge=original.issuer_ibge,
                competence_date=original.competence_date,
                rps_number=original.rps_number,
                rps_series=original.rps_series,
                gross_amount=original.gross_amount,
                invoice_number="8765", verification_code="GISS-TEST-01",
                invoice_reference="8765", authorized_xml=xml,
            ),
        )

    queried = Mock(side_effect=confirmed_invoice)
    ports = Sp4ReviewedMunicipalPorts(
        load_original_rps=Mock(side_effect=AssertionError("noncanonical RPS loader")),
        fiscal_issuer_policy=Mock(), validate_prepared_rps=Mock(),
        submit_official_rps=posted, query_official_rps=queried,
        verify_official_invoice_xml=Mock(),
    )
    transport = JundiaiGissHomologationTransport(
        resolver=Mock(), resolve_certificate=Mock(),
        contract_for_method=Mock(), validate_signed_xml=Mock(),
        exchange=Mock(side_effect=AssertionError("No real GISS network access")),
    )
    pending = JundiaiGissCancellationDecision(
        confirmed=None, response_xml=b"<SyntheticCancelPending/>",
    )
    approved = JundiaiGissCancellationDecision(
        confirmed=True, response_xml=b"<SyntheticCancelConfirmed/>",
    )
    cancellation_post = Mock(return_value=approved if cancel_confirmed else pending)
    cancellation_query = Mock(return_value=approved)
    reviewed = JundiaiTrustedRuntimePorts(
        transport=transport, build_signed_operation=Mock(),
        verify_signed_rps_identity=Mock(), fiscal_issuer_policy=Mock(),
        validate_prepared_rps=Mock(), verify_official_invoice_xml=Mock(),
        submit_verified_cancel=cancellation_post,
        query_verified_cancel=cancellation_query,
    )
    handlers = dict(build_runtime_fiscal_handler_factory(
        operations_gateway=FakeFiscalOperationsGateway(),
        sp4_reviewed_municipalities={"jundiai-giss-v2-homologation": ports},
    )(application))
    handlers.update(build_jundiai_event_handlers(
        application=application, reviewed=reviewed,
        retention=RetentionPolicyMetadata("nfcore-fiscal-archive", 1),
    ))
    web = _client(db, operation_executor=CanonicalPortalOperationExecutor(
        unit_of_work_factory=db,
        path=CanonicalFiscalOperationPath(application, handlers=handlers),
    ))
    fields = _payload() | _TAKER_ADDRESS | {
        "competence_date": "2026-11-12",
        "source_id": "jundiai-original-verified-event",
        "service_municipality_ibge": "3525904",
    }
    first = _post(web, fields, "jundiai-cancel-preparation")
    assert first.status_code == 200, first.text
    original_id = first.json()["document_id"]
    replacement_id = None
    if substitution:
        candidate = _post(
            web, fields | {"source_id": "jundiai-separate-replacement"},
            "jundiai-substitution-candidate",
        )
        assert candidate.status_code == 200, candidate.text
        replacement_id = candidate.json()["document_id"]
        assert original_id != replacement_id
    csrf = web.cookies.get(CSRF_COOKIE)
    assert csrf
    root = "/v1/portal/operations/"
    original_body = {"unit_id": UNIT, "environment": "homologation", "document_id": original_id}
    issued = web.post(root + "issueFiscalDocument", json=original_body, headers={
        CSRF_HEADER: csrf, "Idempotency-Key": "jundiai-issued-once",
    })
    assert issued.status_code == 200, issued.text
    assert posted.call_count == 1
    authorized = web.post(root + "reconcileFiscalOperation", json=original_body, headers={
        CSRF_HEADER: csrf, "Idempotency-Key": "jundiai-issued-query",
    })
    assert authorized.status_code == 200, authorized.text
    assert authorized.json()["status"] == FiscalDocumentState.AUTHORIZED.value

    operation = "substituteJundiaiNfse" if substitution else "cancelJundiaiNfse"
    payload = {
        "unit_id": UNIT, "environment": "homologation",
        "human_approval": True, "reason_code": "1",
    }
    if substitution:
        payload.update({"original_id": original_id, "replacement_id": replacement_id})
    else:
        payload["document_id"] = original_id

    assert web.post(root + operation, json=payload).status_code == 403
    unapproved = web.post(root + operation, json=payload | {
        "human_approval": False,
    }, headers={CSRF_HEADER: csrf, "Idempotency-Key": "jundiai-unapproved"})
    assert unapproved.status_code in (400, 403), unapproved.text
    cancellation_post.assert_not_called()
    event = web.post(root + operation, json=payload, headers={
        CSRF_HEADER: csrf, "Idempotency-Key": "jundiai-one-event",
    })
    assert event.status_code == 200, event.text
    cancellation_post.assert_called_once()
    assert posted.call_count == 1
    if substitution:
        assert event.json()["original_status"] == FiscalDocumentState.CANCELLED.value
        assert event.json()["substitution_mode"] == (
            "separate_original_cancel_then_replacement_issue"
        )
        assert event.json()["replacement_status"] == "ready_to_transmit"
        assert event.json()["next_action"] == "issueFiscalDocument"
        assert replacement_id is not None
        with db() as uow:
            assert uow.lifecycle.get(replacement_id).state is (
                FiscalDocumentState.READY_TO_TRANSMIT
            )
        # Internal substitution must also complete the NEW fiscal document:
        # its own transmit, read-only provider reconciliation, and immutable
        # archived XML. The municipality's atomic SOAP substitute is separate
        # and not inferred from this synthetic sequential workflow.
        replacement_body = {
            "unit_id": UNIT, "environment": "homologation",
            "document_id": replacement_id,
        }
        replacement_issued = web.post(
            root + "issueFiscalDocument", json=replacement_body,
            headers={CSRF_HEADER: csrf, "Idempotency-Key": "jundiai-replacement-issue"},
        )
        assert replacement_issued.status_code == 200, replacement_issued.text
        assert posted.call_count == 2, "Original and replacement each require one POST"
        replacement_recovered = web.post(
            root + "reconcileFiscalOperation", json=replacement_body,
            headers={CSRF_HEADER: csrf, "Idempotency-Key": "jundiai-replacement-query"},
        )
        assert replacement_recovered.status_code == 200, replacement_recovered.text
        assert replacement_recovered.json()["status"] == FiscalDocumentState.AUTHORIZED.value
        assert queried.call_count == 2
        archived_replacement = web.get(
            f"/v1/portal/documents/{replacement_id}/artifacts/authorized_xml",
            params={"unit_id": UNIT, "environment": "homologation"},
        )
        assert archived_replacement.status_code == 200, archived_replacement.text
        assert b"ConsultarNfseRpsResposta" in archived_replacement.content
        replay_issue = web.post(
            root + "issueFiscalDocument", json=replacement_body,
            headers={CSRF_HEADER: csrf, "Idempotency-Key": "jundiai-replacement-issue"},
        )
        assert replay_issue.status_code == 200, replay_issue.text
        assert posted.call_count == 2, "An exact replay must not issue a third RPS"
        replay_cancel = web.post(
            root + operation, json=payload,
            headers={CSRF_HEADER: csrf, "Idempotency-Key": "jundiai-one-event"},
        )
        assert replay_cancel.status_code == 200, replay_cancel.text
        cancellation_post.assert_called_once()
        with db() as uow:
            assert uow.lifecycle.get(replacement_id).state is FiscalDocumentState.AUTHORIZED
    else:
        assert event.json()["status"] == FiscalDocumentState.CANCEL_REQUESTED.value
        recovered = web.post(root + "reconcileJundiaiNfseCancellation", json=original_body,
                             headers={CSRF_HEADER: csrf, "Idempotency-Key": "jundiai-cancel-read"})
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["status"] == FiscalDocumentState.CANCELLED.value
        cancellation_query.assert_called_once()
        cancellation_post.assert_called_once()
        repeated = web.post(root + "reconcileJundiaiNfseCancellation",
                            json=original_body, headers={
                                CSRF_HEADER: csrf, "Idempotency-Key": "jundiai-cancel-read",
                            })
        assert repeated.status_code == 200, repeated.text
        cancellation_query.assert_called_once()
        cancellation_post.assert_called_once()



def test_santana_simpliss_portal_uses_existing_durable_dps_and_replay(
    tmp_path: Path,
) -> None:
    """Real Portal/SQLite/UoW with municipal Simpliss, not a second RPS ledger."""
    db = _database(
        tmp_path / "santana-native.sqlite",
        issuer_ibge="3547304",
        provider_id="santana-simpliss-v1-homologation",
        tax_regime=TaxRegimeCode.NORMAL,
    )
    web = _client(db)
    payload = _payload() | _TAKER_ADDRESS | {
        "source_id": "santana-reviewed-dps-2026",
        "service_municipality_ibge": "3547304",
        "competence_date": "2026-11-12",
    }
    first = _post(web, payload, key="santana-durable-first")
    assert first.status_code == 200, first.text
    assert first.json()["numbering_authority"] == "national_dps_durable"
    assert first.json()["transmitted"] is False
    identifier = first.json()["document_id"]
    scope = ExecutionScope(
        TENANT, UNIT, FiscalEnvironment.HOMOLOGATION, "santana-readback", "fm-nfcore",
    )
    app = FiscalApplicationService(db)
    original = app.load_prepared_nfse_authorization(scope, identifier)
    assert original.document.dps_number == 1
    assert original.document.issuer.address.jurisdiction.municipality_ibge_code == "3547304"
    again = _post(web, payload, key="santana-durable-first")
    assert again.status_code == 200, again.text
    assert again.json()["replay"] is True
    assert again.json()["document_id"] == identifier
    assert app.load_prepared_nfse_authorization(scope, identifier) == original


def test_santana_provider_rejects_profile_of_another_municipality(
    tmp_path: Path,
) -> None:
    db = _database(
        tmp_path / "santana-wrong-city.sqlite",
        issuer_ibge="3509205",
        provider_id="santana-simpliss-v1-homologation",
        tax_regime=TaxRegimeCode.NORMAL,
    )
    web = _client(db)
    payload = _payload() | _TAKER_ADDRESS | {
        "source_id": "santana-city-spoof-attempt",
        "service_municipality_ibge": "3547304",
    }
    response = _post(web, payload, key="santana-city-spoof")
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "NATIVE_NFSE_INVALID_FISCAL_FACTS"
