"""Real authenticated Web -> canonical Extrema RPS preparation, no provider/network.

Fixtures use a synthetic issuer and fake human identity. No external certificate
or municipal homologation is implied by these tests.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.control_plane import FiscalOrganization, FiscalUnitRegistration
from kordena_fiscal.control_plane.commercial import (
    ConfiguredFiscalOperation,
    ProviderBinding,
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
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.mg_webiss_soap import EXTREMA_WEBISS_PROVIDER_ID
from kordena_fiscal.lifecycle import FiscalDocumentState
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.security.human_identity import (
    HumanAccount,
    HumanIdentityService,
    InMemoryHumanAccountRepository,
    InMemoryWebSessionRepository,
    PortalRole,
    ScryptPasswordHasher,
)
from kordena_fiscal.web import create_app
from kordena_fiscal.web.human_auth import CSRF_COOKIE, CSRF_HEADER
from kordena_fiscal.web.portal_runtime import DurableHumanPortalExecutor


def _database(path: Path) -> SqliteFiscalDatabase:
    db = SqliteFiscalDatabase(path)
    db.initialize()
    jurisdiction = BrazilianJurisdiction("MG", "3125101")
    scope = ExecutionScope(
        tenant_id="tenant-extrema", unit_id="unit-extrema",
        environment=FiscalEnvironment.HOMOLOGATION,
        host_namespace="fm-nfcore", correlation_id="setup",
    )
    with db() as uow:
        uow.control_plane.add_organization(FiscalOrganization(
            tenant_id="tenant-extrema", legal_name="Synthetic Extrema Taxpayer",
        ))
        uow.control_plane.add_unit(FiscalUnitRegistration(
            tenant_id="tenant-extrema", unit_id="unit-extrema",
            display_name="Extrema", enabled_environments=frozenset({
                FiscalEnvironment.HOMOLOGATION,
            }),
        ))
        uow.control_plane.add_profile(FiscalProfile(
            profile_id="issuer-extrema", scope=scope,
            cnpj=Cnpj("11222333000181"), legal_name="Synthetic Issuer Ltda",
            tax_regime=TaxRegimeCode.NORMAL,
            state_registration=StateRegistration("MG", "123456789"),
            primary_cnae=CnaeCode("6201501"),
            address=FiscalAddress(
                street="Rua Sintetica", number="10", district="Centro",
                municipality_name="Extrema", jurisdiction=jurisdiction,
                postal_code="37640000",
            ),
            effective_from=datetime.now(UTC) - timedelta(days=1),
        ))
        uow.commercial.put_provider_binding(ProviderBinding(
            binding_id="webiss-extrema-approved-binding",
            tenant_id="tenant-extrema", unit_id="unit-extrema",
            environment=FiscalEnvironment.HOMOLOGATION,
            document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=jurisdiction, operation=ConfiguredFiscalOperation.AUTHORIZE,
            provider_id=EXTREMA_WEBISS_PROVIDER_ID,
        ))
        uow.commit()
    return db


def _client(
    db: SqliteFiscalDatabase, *, role: PortalRole,
    operation_executor: Any | None = None,
) -> TestClient:
    password = "only-synthetic-test-password-2026"
    hasher = ScryptPasswordHasher()
    accounts = InMemoryHumanAccountRepository((HumanAccount(
        account_id="webiss-user-" + role.value,
        email=role.value + "@example.com",
        password_hash=hasher.hash(password),
        tenant_id="tenant-extrema", role=role,
        unit_ids=frozenset({"unit-extrema"}),
    ),))
    identity = HumanIdentityService(
        accounts=accounts, sessions=InMemoryWebSessionRepository(),
        password_hasher=hasher,
    )
    web = TestClient(create_app(
        human_identity=identity,
        portal_executor=DurableHumanPortalExecutor(
            db, operation_executor=operation_executor,
        ),
    ), base_url="https://nfcore.test")
    response = web.post("/v1/auth/login", json={
        "email": role.value + "@example.com", "password": password,
    })
    assert response.status_code == 200
    return web


def _payload() -> dict[str, object]:
    return {
        "unit_id": "unit-extrema",
        "environment": "homologation",
        "source_id": "service-order-approved-123",
        "competence_date": datetime.now(UTC).date().isoformat(),
        "taker_cnpj": "12345678000195",
        "taker_name": "Synthetic Buyer Ltda",
        "service_code": "0107",
        "description": "Servico sintetico revisado",
        "gross_amount": "100.00",
        "deduction_amount": "0.00",
        "iss_rate_fraction": "0.0300",
        "iss_withheld": False,
        "exigibilidade_iss": "1",
        "incidence_municipality": "3125101",
        "incentive_fiscal": False,
        "nbs_code": "123456789",
        "rtc_operation_indicator": "010101",
        "rtc_cst": "000",
        "rtc_tax_class": "000001",
        "rule_reference": "urn:nfcore:synthetic:reviewed-rtc-rule:2026",
        "rule_version": 1,
        "rps_series": 1,
        "fiscal_review_approved": True,
    }


def _post(web: TestClient, data: dict[str, object], key: str = "reviewed-order-one"):
    csrf = web.cookies.get(CSRF_COOKIE)
    assert csrf
    return web.post(
        "/v1/portal/operations/prepareExtremaNfse",
        json=data,
        headers={CSRF_HEADER: csrf, "Idempotency-Key": key},
    )


def test_owner_prepares_rps_once_and_retry_reuses_original_number(tmp_path: Path) -> None:
    db = _database(tmp_path / "review.sqlite")
    web = _client(db, role=PortalRole.OWNER)
    payload = _payload()
    first = _post(web, payload)
    assert first.status_code == 200, first.text
    status = first.json()
    assert status["status"] == FiscalDocumentState.READY_TO_TRANSMIT.value
    assert status["rps_number"] == 1
    assert status["transmitted"] is False
    assert status["fiscal_authorization"] == "not_inferred_from_preparation"
    second = _post(web, payload, key="same-order-new-http-key")
    assert second.status_code == 200, second.text
    assert second.json()["replay"] is True
    assert second.json()["rps_number"] == 1
    assert second.json()["document_id"] == status["document_id"]
    scope = ExecutionScope(
        "tenant-extrema", "unit-extrema",
        FiscalEnvironment.HOMOLOGATION, "audit", "fm-nfcore",
    )
    document = FiscalApplicationService(db).load_prepared_nfse_authorization(
        scope, status["document_id"],
    )
    assert document.document.issuer.cnpj.value == "11222333000181"


def test_mutated_review_is_blocked_and_original_stays_immutable(tmp_path: Path) -> None:
    db = _database(tmp_path / "tamper.sqlite")
    web = _client(db, role=PortalRole.OWNER)
    original = _post(web, _payload())
    assert original.status_code == 200
    edited = _payload() | {"rtc_tax_class": "000002"}
    response = _post(web, edited)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EXTREMA_PREPARATION_CONFLICT"
    assert _post(web, _payload()).json()["rps_number"] == 1


def test_extrema_web_boundary_requires_admin_review_csrf_and_scoped_unit(tmp_path: Path) -> None:
    db = _database(tmp_path / "secure.sqlite")
    operator = _client(db, role=PortalRole.OPERATOR)
    assert _post(operator, _payload()).status_code == 403
    owner = _client(db, role=PortalRole.OWNER)
    route = "/v1/portal/operations/prepareExtremaNfse"
    assert owner.post(route, json=_payload()).status_code == 403
    csrf = owner.cookies.get(CSRF_COOKIE)
    assert csrf
    assert owner.post(route, json=_payload(), headers={CSRF_HEADER: csrf}).status_code == 400
    assert _post(owner, _payload() | {"tenant_id": "other"}).status_code == 400
    assert _post(owner, _payload() | {"unit_id": "other"}).status_code == 403
    assert _post(owner, _payload() | {"fiscal_review_approved": False}).status_code == 403
    assert _post(owner, _payload() | {"environment": "production"}).status_code == 400


def test_invalid_rtc_blocks_preparation_before_durable_numbering(tmp_path: Path) -> None:
    db = _database(tmp_path / "bad-rtc.sqlite")
    web = _client(db, role=PortalRole.OWNER)
    bad = _post(web, _payload() | {"rtc_tax_class": "WRONG!"})
    assert bad.status_code == 400
    success = _post(web, _payload())
    assert success.status_code == 200, success.text
    assert success.json()["rps_number"] == 1
