# ruff: noqa: F811 -- imported pytest fixtures are requested by name.
"""T14 synthetic, scoped NF-e authorization evidence; no live transmission."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
from fastapi.testclient import TestClient
from lxml import etree
from psycopg import sql
from test_bling_canonical import mapping, signing_material  # noqa: F401
from test_bling_workflow import workflow_database
from test_native_sale import client, post

from kordena_fiscal.application.accounting_review import (
    ReviewDecision,
    ReviewTarget,
    project_review,
    record_decision,
)
from kordena_fiscal.application.authorized_issuance import MEDIA_TYPE, IssuanceApprovalRequired
from kordena_fiscal.application.federal_regime_store import declare_federal_regime
from kordena_fiscal.application.issuance_terms import TERMS_SCHEMA
from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.application.state_benefits_service import import_reviewed_state_benefit
from kordena_fiscal.application.state_review_gate import REVIEW_KEY_ENV, review_claims
from kordena_fiscal.cognitive.accounting_review_api import build_accounting_review_runner
from kordena_fiscal.cognitive.composition import build_cognitive_router
from kordena_fiscal.cognitive.state_benefits_api import build_state_issuer_verifier
from kordena_fiscal.control_plane import (
    ControlPlaneAuditAction,
    ControlPlaneAuditEvent,
    FiscalOrganization,
    FiscalUnitRegistration,
)
from kordena_fiscal.control_plane.commercial import ConfiguredFiscalOperation, ProviderBinding
from kordena_fiscal.domain import (
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
    Gtin,
    TaxRegimeCode,
)
from kordena_fiscal.gateway import FiscalGatewayClient
from kordena_fiscal.gateway.nfe_sp_homologation import SefazSpHomologationGateway
from kordena_fiscal.lifecycle import FiscalDocumentState
from kordena_fiscal.runtime.native_sale_policy import sale_policy_key
from kordena_fiscal.security.human_identity import (
    HumanAccount,
    HumanIdentityService,
    InMemoryWebSessionRepository,
    PortalRole,
    ScryptPasswordHasher,
)
from kordena_fiscal.security.human_mfa import HumanMfaService, InMemoryHumanMfaStore
from kordena_fiscal.security.totp import totp_at
from kordena_fiscal.signing.nfe_xmldsig import verify_official_nfe4_signature
from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime
from kordena_fiscal.tax.state_benefits import FACTS_SCHEMA, RULE_SCHEMA
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault
from kordena_fiscal.web import create_app
from kordena_fiscal.web.human_auth import CSRF_COOKIE, CSRF_HEADER
from kordena_fiscal.web.portal_runtime import DurableHumanPortalExecutor
from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

LOCAL = ZoneInfo("America/Sao_Paulo")
BENEFIT = "synthetic-t14-icms"
REVIEW = "synthetic-t14-curatorial-review"
NORM = "Decreto Sintetico T14 — TESTE NAO LEI"
ACTOR = "synthetic-t14-accountant"


@pytest.fixture
def economy_database(tmp_path, monkeypatch):
    dsn = os.environ.get("NFCORE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("isolated PostgreSQL provided by CI")
    role = "t14_role_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as raw:
        raw.execute(
            sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(
                sql.Identifier(role),
            )
        )
    try:
        with workflow_database(tmp_path, "postgres") as database:
            database.initialize(enable_economy=True, economy_runtime_role=role)
            monkeypatch.setenv("NFCORE_ECONOMY_ENABLED", "true")
            monkeypatch.setenv("NFCORE_ECONOMY_RUNTIME_ROLE", role)
            yield database
    finally:
        with psycopg.connect(dsn, autocommit=True) as raw:
            raw.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def _fixture(database, mapping, signing_material, monkeypatch, tmp_path):
    now = datetime.now(UTC)
    period = now.astimezone(LOCAL).date().replace(day=1)
    start = datetime.combine(period, datetime.min.time(), tzinfo=LOCAL) - timedelta(days=2)
    end = datetime.combine(
        period.replace(day=28) + timedelta(days=4),
        datetime.min.time(),
        tzinfo=LOCAL,
    ) + timedelta(days=40)
    scope = replace(mapping["issuer"].scope, host_namespace="fm-nfcore")
    issuer = replace(
        mapping["issuer"], scope=scope, tax_regime=TaxRegimeCode.NORMAL, effective_from=start
    )
    product = replace(
        mapping["products_by_code"]["SKU"], scope=scope, gtin=Gtin("SEM GTIN"), effective_from=start
    )
    with database() as uow:
        uow.control_plane.add_organization(FiscalOrganization("tenant", "Synthetic T14"))
        uow.control_plane.add_unit(
            FiscalUnitRegistration(
                "tenant",
                "unit",
                "Synthetic",
                frozenset({FiscalEnvironment.HOMOLOGATION}),
            )
        )
        uow.control_plane.append_audit(
            ControlPlaneAuditEvent(
                event_id="synthetic-t14-unit-onboarded",
                occurred_at=now,
                actor_id="synthetic-t14-setup",
                action=ControlPlaneAuditAction.UNIT_ONBOARDED,
                target_type="unit",
                target_id="unit",
                correlation_id="synthetic-t14",
                tenant_id="tenant",
                unit_id="unit",
            )
        )
        uow.control_plane.add_profile(issuer)
        uow.commercial.add_product_profile(product)
        uow.commercial.put_provider_binding(
            ProviderBinding(
                binding_id="t14-nfe",
                tenant_id="tenant",
                unit_id="unit",
                environment=scope.environment,
                document_kind=FiscalDocumentKind.NFE,
                jurisdiction=issuer.address.jurisdiction,
                operation=ConfiguredFiscalOperation.AUTHORIZE,
                provider_id="sefaz-sp-homologacao-nfe4",
            )
        )
        uow.commit()
    declare_federal_regime(
        database,
        scope=scope,
        crt=TaxRegimeCode.NORMAL,
        issuer_cnpj=issuer.cnpj,
        federal_income_tax_regime=FederalIncomeTaxRegime.LUCRO_REAL,
        effective_from=start,
        source_reference="synthetic-regime",
        actor="test",
        idempotency_key="t14-regime",
        occurred_at=start,
    )
    sale_rule = {
        "rule_id": "synthetic-t14-sale-rule",
        "version": 1,
        "priority": 1,
        "effective_from": start.isoformat(),
        "effective_to": end.isoformat(),
        "source_normative": NORM,
        "selector": {
            "state_code": "SP",
            "destination_state_code": "SP",
            "tax_regime": 3,
            "recipient_profile": "consumer_final",
            "ncm_prefix": product.ncm.value,
        },
        "outcome": {
            "cfop": "5102",
            "icms_code": "20",
            "pis_cst": "07",
            "cofins_cst": "07",
            "nfe_rates": {
                "icms_rate": "18",
                "icms_reduction_rate": "20",
                "pis_rate": "0",
                "cofins_rate": "0",
                "pis_base": "net",
                "cofins_base": "net",
                "icms_benefit": {
                    "code": "SP123456",
                    "benefit_id": BENEFIT,
                    "reviewed_by": "synthetic-reviewer",
                    "approval_reference": REVIEW,
                    "deson_mode": "nominal_minus_due",
                    "deson_rate": "18",
                    "deson_reason": 9,
                    "deduct_deson": False,
                },
            },
        },
    }
    terms = {
        "schema_version": TERMS_SCHEMA,
        "sale_rule": sale_rule,
        "issuer_profile_id": issuer.profile_id,
        "issuer_profile_version": issuer.version,
        "product_id": product.product_id,
        "product_profile_id": product.profile_id,
        "product_profile_version": product.version,
        "product_origin": 0,
        "no_cumulative_cap": True,
        "application_reference": "synthetic-application-review",
    }
    url = "https://www.gov.br/testes/sintetico/t14"
    policy = {
        "schema_version": RULE_SCHEMA,
        "review_status": "reviewed",
        "review_reference": REVIEW,
        "uf": "SP",
        "benefit_kind": "base_reduction",
        "legal_path": "state_statute",
        "state_normative_reference": NORM,
        "state_official_source_url": url,
        "valid_from": start.date().isoformat(),
        "valid_until": end.date().isoformat(),
        "legal_valid_until_inclusive": (end.date() - timedelta(days=1)).isoformat(),
        "allowed_regimes": ["lucro_real"],
        "cnae_scope": "allowlist",
        "allowed_cnaes": [issuer.primary_cnae.value],
        "ncm_scope": "allowlist",
        "allowed_ncms": [product.ncm.value],
        "allowed_cfops": ["5102"],
        "allowed_operations": ["domestic_sale"],
        "required_evidence": [],
        "individual_concession_required": False,
        "issuance_application": terms,
        "legal_citations": [
            {
                "act": NORM,
                "provision": "Teste sintetico",
                "source_url": url,
                "source_sha256": "a" * 64,
                "published_on": start.date().isoformat(),
                "valid_from": start.date().isoformat(),
                "valid_until": end.date().isoformat(),
                "review_reference": REVIEW,
            }
        ],
    }
    facts = {
        "schema_version": FACTS_SCHEMA,
        "review_status": "reviewed",
        "review_reference": REVIEW,
        "uf": "SP",
        "activity_cnae": issuer.primary_cnae.value,
        "operation_ncm": product.ncm.value,
        "operation_cfop": "5102",
        "operation": "domestic_sale",
        "evidence": {
            key: "synthetic-" + key
            for key in (
                "state_normative_review",
                "operation_classification_review",
                "taxpayer_status_review",
                "competence_review",
                "state_act_review",
                "state_registration_regular_review",
                "icms_st_applicability_review",
                "difal_applicability_review",
                "individual_concession_review",
            )
        }
        | {"issuance_application_review": terms["application_reference"]},
        "individual_concession": {
            "status": "not_required",
            "competence": period.isoformat(),
            "review_reference": REVIEW,
            "document_reference": "synthetic-concession-review",
        },
    }
    key = "synthetic-t14-test-only-" + "x" * 40
    monkeypatch.setenv(REVIEW_KEY_ENV, key)
    receipt = {
        "claims": review_claims(
            policy=policy,
            facts=facts,
            scope_identity=scope.identity_material,
            issuer_cnpj=issuer.cnpj.value,
            competence=period,
            benefit_id=BENEFIT,
            benefit_version=1,
        ),
        "reviewer_id": "synthetic-reviewer",
        "approved_at": (now - timedelta(seconds=1)).isoformat(),
        "decision": "internal_curatorial_accepted",
    }
    receipt["signature_hmac_sha256"] = hmac.new(
        key.encode(),
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()
    policy["internal_review_approval"] = receipt
    with database.economy(scope) as store:
        evaluated = import_reviewed_state_benefit(
            store,
            snapshot_id="t14-facts",
            snapshot_version=1,
            competence=period,
            issuer=issuer.cnpj,
            content=facts,
            benefit_id=BENEFIT,
            benefit_version=1,
            benefit_content=policy,
            verify_issuer=build_state_issuer_verifier(database, scope),
            verified_source_bytes=lambda _: 1,
        )
        assert evaluated["status"] == "potential"
        assert evaluated["issuance_application"] == terms
        assert not evaluated["issuance_authorized"]
    root = tmp_path / "t14-policies"
    root.mkdir()
    monkeypatch.setenv("NFCORE_SALE_FISCAL_POLICY_ROOT", str(root))
    sale = {
        "schema_version": 1,
        "policy_id": "t14-synthetic",
        "version": 1,
        "host_namespace": scope.host_namespace,
        "tenant_id": scope.tenant_id,
        "unit_id": scope.unit_id,
        "environment": scope.environment.value,
        "document_kind": "nfe",
        "issuer_profile_id": issuer.profile_id,
        "issuer_profile_version": issuer.version,
        "products": {"p1": {"version": 1}},
        "series": 1,
        "sale_options": {"nature": "VENDA", "presence": 1, "freight_mode": 9},
        "rules": [sale_rule],
    }
    name = sale_policy_key(scope, FiscalDocumentKind.NFE)

    def install(data):
        raw = json.dumps(data).encode()
        digest = hashlib.sha256(raw).hexdigest()
        (root / (name + ".json")).write_bytes(raw)
        (root / (name + ".sha256")).write_text(digest, encoding="ascii")
        return digest

    digest = install(sale)

    class Vault:
        def resolve(self, **kwargs):
            assert kwargs["issuer_cnpj"] == issuer.cnpj.value
            return signing_material

    monkeypatch.setattr(EncryptedA1Vault, "from_environ", staticmethod(lambda: Vault()))
    payload = {
        "unit_id": scope.unit_id,
        "environment": scope.environment.value,
        "document_kind": "nfe",
        "source_id": "t14-sale",
        "issued_at": datetime.now(UTC).isoformat(),
        "policy_sha256": digest,
        "recipient": {
            "document": "52998224725",
            "name": "Synthetic buyer",
            "street": "Rua Sintetica",
            "number": "1",
            "district": "Centro",
            "municipality_name": "Sao Paulo",
            "municipality_ibge_code": "3550308",
            "state": "SP",
            "postal_code": "01001000",
            "ie_indicator": 9,
            "final_consumer": True,
        },
        "items": [
            {
                "product_id": "p1",
                "quantity": "1",
                "unit_price": "100.00",
                "discount": "0.00",
                "freight": "0.00",
                "other": "0.00",
            }
        ],
        "payments": [{"method": "pix", "amount": "100.00"}],
        "change_amount": "0.00",
    }
    return scope, issuer, period, sale, install, payload, policy, facts


def _accountant(database, scope):
    hasher = ScryptPasswordHasher()
    password = "Synthetic-only-password-14!"
    account = HumanAccount(
        ACTOR,
        "t14-accountant@example.test",
        hasher.hash(password),
        scope.tenant_id,
        PortalRole.ACCOUNTANT,
        frozenset({scope.unit_id}),
    )
    database.human_accounts().save(account)
    identity = HumanIdentityService(
        accounts=database.human_accounts(),
        sessions=InMemoryWebSessionRepository(),
        password_hasher=hasher,
    )
    mfa = HumanMfaService(store=InMemoryHumanMfaStore(), encryption_key=bytes(range(32)))
    reader = DurableHumanPortalExecutor(database)
    runner = build_accounting_review_runner(
        reader, database.economy, database, mfa.has_recent_step_up
    )
    router = build_cognitive_router(
        identity, reader, {"NFCORE_COGNITIVE_ENABLED": "true"}, accounting_review_runner=runner
    )
    web = TestClient(
        create_app(
            human_identity=identity, human_mfa=mfa, portal_executor=reader, cognitive_router=router
        ),
        base_url="https://nfcore.test",
    )
    first = web.post("/v1/auth/login", json={"email": account.email, "password": password})
    assert first.status_code == 200, first.text
    challenge = first.json()["mfa"]["challenge"]
    enroll = web.post("/v1/auth/mfa/enroll/start", json={"challenge": challenge})
    assert enroll.status_code == 200, enroll.text
    raw = enroll.json()["secret_base32"]
    secret = base64.b32decode(raw + "=" * (-len(raw) % 8))
    instant = datetime.now(UTC)
    enrolled = web.post(
        "/v1/auth/mfa/enroll/confirm",
        json={
            "challenge": challenge,
            "code": totp_at(secret, instant - timedelta(seconds=30)),
        },
    )
    assert enrolled.status_code == 200, enrolled.text
    csrf = {CSRF_HEADER: web.cookies.get(CSRF_COOKIE)}
    return web, account, secret, csrf


def _review(web, scope, period, csrf, command=None):
    body = {
        "unit_id": scope.unit_id,
        "environment": scope.environment.value,
        "competence": period.isoformat(),
        "target": {"kind": "benefit", "source": "state", "benefit_id": BENEFIT},
    }
    if command is not None:
        body["command"] = command
    return web.post("/v1/portal/cognitive/economy/accounting-review", json=body, headers=csrf)


def _command(report, decision, request_id):
    return {
        "decision": decision,
        "subject_digest": report["subject_digest"],
        "expected_version": report["current_version"],
        "request_id": request_id,
        "opinion_reference": "synthetic-opinion",
        "professional_reference": "CRC-TEST",
        "rationale": "Synthetic test of the accounting approval, not a real opinion.",
    }


def test_t14_real_postgres_http_totp_signed_preparation_and_dispatch(
    economy_database,
    mapping,
    signing_material,
    monkeypatch,
    tmp_path,
):
    db = economy_database
    scope, issuer, period, sale, install, payload, policy, facts = _fixture(
        db,
        mapping,
        signing_material,
        monkeypatch,
        tmp_path,
    )
    operator = client(db)
    preview = post(
        operator,
        {
            key: payload[key]
            for key in (
                "unit_id",
                "environment",
                "document_kind",
            )
        },
        operation="reviewNativeSale",
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["accounting_approval_required"][0]["benefit_id"] == BENEFIT
    blocked = post(operator, payload, "missing-review")
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["code"] == "ACCOUNTING_ISSUANCE_BLOCKED"

    accountant, account, secret, csrf = _accountant(db, scope)
    response = _review(accountant, scope, period, csrf)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["status"] == "pending"
    assert report["subject"]["candidate"]["issuance_application"] == policy["issuance_application"]
    command = _command(report, "approved", "approve-1")
    refused = _review(accountant, scope, period, csrf, command)
    assert refused.status_code == 403, refused.text
    code = totp_at(secret, datetime.now(UTC))
    step = accountant.post("/v1/auth/mfa/step-up", json={"code": code}, headers=csrf)
    assert step.status_code == 200, step.text
    assert (
        accountant.post("/v1/auth/mfa/step-up", json={"code": code}, headers=csrf).status_code
        == 401
    )
    approved = _review(accountant, scope, period, csrf, command)
    assert approved.status_code == 200, approved.text
    approval = approved.json()
    assert approval["status"] == "approved"
    assert approval["issuance_authorized"] is False

    # A different pinned rate cannot borrow the approval of the original rule.
    import copy

    altered = copy.deepcopy(sale)
    altered["rules"][0]["outcome"]["nfe_rates"]["icms_reduction_rate"] = "25"
    altered_digest = install(altered)
    bad = post(
        operator,
        payload | {"policy_sha256": altered_digest, "issued_at": datetime.now(UTC).isoformat()},
        "bad-rate",
    )
    assert bad.status_code == 409, bad.text
    restored = install(sale)
    payload = payload | {"policy_sha256": restored, "issued_at": datetime.now(UTC).isoformat()}
    prepared = post(operator, payload, "prepared-1")
    assert prepared.status_code == 200, prepared.text
    doc_id = prepared.json()["document_id"]
    app = FiscalApplicationService(db)
    request = app.load_prepared_authorization(scope, doc_id)
    assert request.access_key.value[25:34] == "000000001"
    OfficialNfeEnvelopeValidator()(request.signed_xml)
    root = etree.fromstring(request.signed_xml)
    verify_official_nfe4_signature(root, signing_material)
    assert root.xpath("string(//*[local-name()='cBenef'])") == "SP123456"
    assert root.xpath("string(//*[local-name()='ICMSTot']/*[local-name()='vICMS'])") == "14.40"
    assert root.xpath("string(//*[local-name()='ICMSTot']/*[local-name()='vICMSDeson'])") == "3.60"
    with db() as uow:
        proof = [
            e for e in uow.archive.list_for_document(scope, doc_id) if e.media_type == MEDIA_TYPE
        ]
    assert len(proof) == 1
    claims = json.loads(proof[0].content)["claims"]
    assert claims[0]["review_event_digest"] == approval["latest"]["event_digest"]
    assert claims[0]["subject_digest"] == approval["subject_digest"]
    assert claims[0]["benefit_digest"] == approval["subject"]["benefit_digest"]

    # No provider call can occur after revocation, even for already signed XML.
    exchange_calls = []

    def exchange(soap, *_args):
        exchange_calls.append(soap)
        raise AssertionError("blocked dispatch reached provider")

    gateway = FiscalGatewayClient(
        SefazSpHomologationGateway(
            resolve_certificate=lambda *_args: signing_material,
            exchange=exchange,
        )
    )
    revoked = _review(accountant, scope, period, csrf, _command(approval, "revoked", "revoke-1"))
    assert revoked.status_code == 200, revoked.text
    with pytest.raises(IssuanceApprovalRequired):
        app.authorize_prepared_document(
            document_id=doc_id, request=request, gateway=gateway, occurred_at=datetime.now(UTC)
        )
    assert exchange_calls == []
    with db() as uow:
        assert uow.lifecycle.get(doc_id).state is FiscalDocumentState.READY_TO_TRANSMIT
    # Exact preparation replay is a read of durable bytes, never a new approval or issuance.
    assert post(operator, payload, "prepared-replay").json()["replay"] is True
    renewed = _review(
        accountant, scope, period, csrf, _command(revoked.json(), "approved", "approve-2")
    )
    assert renewed.status_code == 200, renewed.text
    with pytest.raises(IssuanceApprovalRequired, match="earlier issuance|changed"):
        app.authorize_prepared_document(
            document_id=doc_id, request=request, gateway=gateway, occurred_at=datetime.now(UTC)
        )
    # A new document can consume the renewed approval.
    payload2 = payload | {"source_id": "t14-sale-2", "issued_at": datetime.now(UTC).isoformat()}
    second = post(operator, payload2, "prepared-2")
    assert second.status_code == 200, second.text
    doc2 = second.json()["document_id"]
    request2 = app.load_prepared_authorization(scope, doc2)
    db.human_accounts().save(replace(account, enabled=False))
    with pytest.raises(IssuanceApprovalRequired, match="no longer designated"):
        app.authorize_prepared_document(
            document_id=doc2, request=request2, gateway=gateway, occurred_at=datetime.now(UTC)
        )
    db.human_accounts().save(account)

    # Successful dispatch is a synthetic provider response only.
    ns = "http://www.portalfiscal.inf.br/nfe"

    def simulated_exchange(soap, *_args):
        exchange_calls.append(soap)
        root = etree.fromstring(soap)
        verify_official_nfe4_signature(root.find(f".//{{{ns}}}enviNFe"), signing_material)
        key = root.find(f".//{{{ns}}}infNFe").get("Id")[3:]
        digest = root.findtext(".//{http://www.w3.org/2000/09/xmldsig#}DigestValue")
        received = datetime.now(LOCAL).isoformat(timespec="seconds")
        return (
            '<Envelope xmlns="http://www.w3.org/2003/05/soap-envelope"><Body>'
            f'<retEnviNFe xmlns="{ns}" versao="4.00"><tpAmb>2</tpAmb>'
            "<verAplic>synthetic</verAplic><cStat>104</cStat><xMotivo>Lote processado</xMotivo>"
            f"<cUF>35</cUF><dhRecbto>{received}</dhRecbto>"
            '<protNFe versao="4.00"><infProt><tpAmb>2</tpAmb><verAplic>synthetic</verAplic>'
            f"<chNFe>{key}</chNFe><dhRecbto>{received}</dhRecbto>"
            f"<nProt>135000000000001</nProt><digVal>{digest}</digVal>"
            "<cStat>100</cStat><xMotivo>Autorizado teste sintetico</xMotivo>"
            "</infProt></protNFe></retEnviNFe></Body></Envelope>"
        ).encode()

    approved_gateway = FiscalGatewayClient(
        SefazSpHomologationGateway(
            resolve_certificate=lambda *_args: signing_material,
            exchange=simulated_exchange,
        )
    )
    result = app.authorize_prepared_document(
        document_id=doc2, request=request2, gateway=approved_gateway, occurred_at=datetime.now(UTC)
    )
    assert result.lifecycle.state is FiscalDocumentState.AUTHORIZED
    assert len(exchange_calls) == 1
    replay = app.authorize_prepared_document(
        document_id=doc2, request=request2, gateway=gateway, occurred_at=datetime.now(UTC)
    )
    assert replay.replay and len(exchange_calls) == 1

    # Normative supersession blocks a NEW preparation, not historical artifacts.
    with db.economy(scope) as store:
        store.append_benefit(
            record_id=BENEFIT,
            version=2,
            tax_code="ICMS",
            jurisdiction="SP",
            normative_reference=NORM,
            valid_from=period,
            valid_until=None,
            content={"schema_version": RULE_SCHEMA, "review_status": "revoked"},
        )
    denied = post(
        operator,
        payload | {"source_id": "t14-sale-3", "issued_at": datetime.now(UTC).isoformat()},
        "revoked-rule",
    )
    assert denied.status_code == 409, denied.text
    _history_regression(db, scope, issuer.cnpj, period)


def _history_regression(db, scope, issuer, period):
    target = ReviewTarget(kind="annual_comparison")
    subject = {"kind": "annual_comparison", "synthetic": True}
    with db.economy(scope) as store:
        for version in range(22):
            before = project_review(store, issuer, period, target, subject)
            command = ReviewDecision.model_validate(
                _command(
                    before,
                    "approved" if version % 2 == 0 else "revoked",
                    f"history-{version}",
                )
            )
            after = record_decision(
                store,
                issuer,
                period,
                target,
                subject,
                command,
                actor_id=ACTOR,
                now=datetime.now(UTC),
            )
        assert [e["event_version"] for e in after["history"]] == list(range(22, 2, -1))
        older = project_review(
            store, issuer, period, target, subject, before_version=after["next_before_version"]
        )
        assert [e["event_version"] for e in older["history"]] == [2, 1]
        assert older["next_before_version"] is None
        key = after["record_id"]
        row = store.record("fm_economy_snapshots", key, 22)
        assert row is not None
        corrupt = row["content"] | {
            "event_version": 23,
            "previous_digest": "0" * 64,
            "command": row["content"]["command"] | {"expected_version": 22},
        }
        store.append_snapshot(
            record_id=key, version=23, competence=period, issuer=issuer, content=corrupt
        )
        with pytest.raises(FiscalValidationError, match="chain mismatch"):
            project_review(store, issuer, period, target, subject)
