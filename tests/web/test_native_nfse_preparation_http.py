"""Native National NFS-e preparation without ERP, A1, external transport or mock issuance."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
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
from kordena_fiscal.gateway.nfse_nacional_homologation import (
    NACIONAL_HOMOLOGATION_PROVIDER_ID,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import SP4_MUNICIPAL_PROVIDERS
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

TENANT = "tenant-native"
UNIT = "unit-cajamar"
IBGE = "3509205"
ROUTE = "/v1/portal/operations/prepareNativeNfse"


def _database(
    path: Path, *, with_binding: bool = True,
    ibge: str = IBGE, tax_regime: TaxRegimeCode = TaxRegimeCode.SIMPLES_NACIONAL,
    provider_id: str = NACIONAL_HOMOLOGATION_PROVIDER_ID,
) -> SqliteFiscalDatabase:
    db = SqliteFiscalDatabase(path)
    db.initialize()
    jurisdiction = BrazilianJurisdiction("SP", ibge)
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
        uow.control_plane.add_profile(FiscalProfile(
            profile_id="issuer-native", scope=scope,
            cnpj=Cnpj("11222333000181"), legal_name="Emissor Sintetico Ltda",
            tax_regime=tax_regime,
            state_registration=StateRegistration("SP", "123456789"),
            primary_cnae=CnaeCode("6201501"),
            address=FiscalAddress(
                street="Rua de Homologacao", number="10", district="Centro",
                municipality_name="Cajamar", jurisdiction=jurisdiction,
                postal_code="07750000",
            ),
            effective_from=datetime.now(UTC) - timedelta(days=1),
        ))
        if with_binding:
            uow.commercial.put_provider_binding(ProviderBinding(
                binding_id="native-national-nfse-binding", tenant_id=TENANT,
                unit_id=UNIT, environment=FiscalEnvironment.HOMOLOGATION,
                document_kind=FiscalDocumentKind.NFSE,
                jurisdiction=jurisdiction,
                operation=ConfiguredFiscalOperation.AUTHORIZE,
                provider_id=provider_id,
            ))
        uow.commit()
    return db


def _client(
    db: SqliteFiscalDatabase, role: PortalRole = PortalRole.OWNER,
    *,
    resolve_sp4_numbering: Callable[
        [ExecutionScope, str, str], tuple[int, str]
    ] | None = None,
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
                db, resolve_sp4_numbering=resolve_sp4_numbering,
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


@pytest.mark.parametrize("provider_id,ibge", sorted(SP4_MUNICIPAL_PROVIDERS.items()))
def test_native_portal_persists_exact_original_rps_for_four_sp_cities(
    tmp_path: Path, provider_id: str, ibge: str,
) -> None:
    db = _database(
        tmp_path / (ibge + ".sqlite"), ibge=ibge,
        tax_regime=TaxRegimeCode.NORMAL, provider_id=provider_id,
    )
    def approved(_scope: ExecutionScope, _issuer: str, _provider: str) -> tuple[int, str]:
        return 1, "NF"

    portal = _client(db, resolve_sp4_numbering=approved)
    payload = _payload() | {
        "service_municipality_ibge": ibge,
        "source_id": "reviewed-sp4-" + ibge,
    }
    first = _post(portal, payload)
    assert first.status_code == 200, first.text
    state = first.json()
    assert state["status"] == FiscalDocumentState.READY_TO_TRANSMIT.value
    assert state["dps_numbering"] == "not_applicable_municipal"
    assert state["rps_number"] == "1"
    assert state["rps_series"] == "NF"
    assert state["transmitted"] is False
    again = _post(portal, payload, key="replay-with-other-http-key")
    assert again.status_code == 200, again.text
    assert again.json()["replay"] is True
    assert again.json()["rps_number"] == "1"

    scope = ExecutionScope(
        TENANT, UNIT, FiscalEnvironment.HOMOLOGATION,
        "audit", "fm-nfcore",
    )
    original = FiscalApplicationService(db).load_sp4_original_rps(
        scope, state["document_id"],
    )
    assert original.issuer_ibge == ibge
    assert original.rps_number == "1"
    second = _post(portal, payload | {"source_id": "next-" + ibge}, "next")
    assert second.status_code == 200, second.text
    assert second.json()["rps_number"] == "2"


@pytest.mark.parametrize("provider_id,ibge", sorted(SP4_MUNICIPAL_PROVIDERS.items()))
def test_municipal_native_preparation_requires_reviewed_rps_policy_before_writing(
    tmp_path: Path, provider_id: str, ibge: str,
) -> None:
    db = _database(
        tmp_path / (ibge + ".sqlite"), ibge=ibge,
        tax_regime=TaxRegimeCode.NORMAL, provider_id=provider_id,
    )
    web = _client(db)
    response = _post(web, _payload() | {"service_municipality_ibge": ibge})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "NATIVE_NFSE_INVALID_FISCAL_FACTS"
    scoped = ExecutionScope(TENANT, UNIT, FiscalEnvironment.HOMOLOGATION, "check", "fm-nfcore")
    with db() as uow:
        assert not uow.lifecycle.list_for_scope(scoped)
