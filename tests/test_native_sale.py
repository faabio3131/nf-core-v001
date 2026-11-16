"""Manual sales use authenticated HTTP, real signatures, XSD and durable preparation."""
# ruff: noqa: F811 -- imported pytest fixtures are requested by name.
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from lxml import etree
from test_bling_canonical import mapping, preparation_database, signing_material  # noqa: F401

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive.danfe_pdf import render_authorized_nfe_danfe
from kordena_fiscal.control_plane import FiscalOrganization, FiscalUnitRegistration
from kordena_fiscal.control_plane.commercial import ConfiguredFiscalOperation, ProviderBinding
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    FiscalDocumentKind,
    FiscalEnvironment,
    Gtin,
    StateRegistration,
)
from kordena_fiscal.runtime.native_sale_policy import sale_policy_key
from kordena_fiscal.security.human_identity import (
    HumanAccount,
    HumanIdentityService,
    InMemoryHumanAccountRepository,
    InMemoryWebSessionRepository,
    PortalRole,
    ScryptPasswordHasher,
)
from kordena_fiscal.signing.nfe_xmldsig import verify_official_nfe4_signature
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault
from kordena_fiscal.web import create_app
from kordena_fiscal.web.human_auth import CSRF_COOKIE, CSRF_HEADER
from kordena_fiscal.web.portal_runtime import DurableHumanPortalExecutor
from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator


def client(db, *, tenant="tenant", role=PortalRole.OWNER, operation_executor=None):
    hasher = ScryptPasswordHasher()
    identity = HumanIdentityService(
        accounts=InMemoryHumanAccountRepository((HumanAccount(
            account_id="manual-" + tenant, email="manual@example.com",
            password_hash=hasher.hash("synthetic-password-only"), tenant_id=tenant,
            role=role, unit_ids=frozenset({"unit"}),
        ),)), sessions=InMemoryWebSessionRepository(), password_hasher=hasher,
    )
    web = TestClient(create_app(
        human_identity=identity, portal_executor=DurableHumanPortalExecutor(
            db, operation_executor=operation_executor,
            danfe_renderer=render_authorized_nfe_danfe),
    ), base_url="https://nfcore.test")
    assert web.post("/v1/auth/login", json={
        "email": "manual@example.com", "password": "synthetic-password-only",
    }).status_code == 200
    return web


def post(web, payload, key="manual-attempt", *, operation="prepareNativeSale"):
    return web.post("/v1/portal/operations/" + operation, json=payload, headers={
        CSRF_HEADER: web.cookies.get(CSRF_COOKIE), "Idempotency-Key": key,
    })


@pytest.fixture
def sale_setup(preparation_database, mapping, signing_material, tmp_path, monkeypatch):
    db = preparation_database
    now = datetime.now(UTC) - timedelta(minutes=1)
    scope = replace(mapping["issuer"].scope, host_namespace="fm-nfcore")
    issuer = replace(
        mapping["issuer"], scope=scope, effective_from=now - timedelta(days=1),
        address=replace(mapping["issuer"].address,
            jurisdiction=BrazilianJurisdiction("MG", "3106200"),
            municipality_name="Belo Horizonte"),
        state_registration=StateRegistration("MG", "123456789"),
    )
    product = replace(mapping["products_by_code"]["SKU"], scope=scope,
        gtin=Gtin("SEM GTIN"), effective_from=now - timedelta(days=1))
    with db() as uow:
        uow.control_plane.add_organization(FiscalOrganization("tenant", "Synthetic"))
        uow.control_plane.add_unit(FiscalUnitRegistration(
            "tenant", "unit", "Synthetic", frozenset({FiscalEnvironment.HOMOLOGATION})))
        uow.control_plane.add_profile(issuer)
        uow.commercial.add_product_profile(product)
        for kind in (FiscalDocumentKind.NFE, FiscalDocumentKind.NFCE):
            uow.commercial.put_provider_binding(ProviderBinding(
                binding_id="manual-" + kind.value, tenant_id="tenant", unit_id="unit",
                environment=FiscalEnvironment.HOMOLOGATION, document_kind=kind,
                jurisdiction=issuer.address.jurisdiction,
                operation=ConfiguredFiscalOperation.AUTHORIZE,
                provider_id="sefaz-mg-homologacao-" + kind.value + "4"))
        uow.commit()
    root = tmp_path / "policies"
    root.mkdir()
    monkeypatch.setenv("NFCORE_SALE_FISCAL_POLICY_ROOT", str(root))
    policies = {}
    for kind in (FiscalDocumentKind.NFE, FiscalDocumentKind.NFCE):
        policy = {
            "schema_version": 1, "policy_id": "synthetic-manual", "version": 1,
            "host_namespace": "fm-nfcore", "tenant_id": "tenant", "unit_id": "unit",
            "environment": "homologation", "document_kind": kind.value,
            "issuer_profile_id": issuer.profile_id, "issuer_profile_version": issuer.version,
            "products": {"p1": {"version": product.version}}, "series": 1,
            "sale_options": {"nature": "VENDA", "presence": 1, "freight_mode": 9},
            "rules": [{
                "rule_id": "synthetic-sale", "version": 1, "priority": 1,
                "effective_from": (now - timedelta(days=1)).isoformat(),
                "source_normative": "urn:synthetic:manual-test-only",
                "selector": {"state_code": "MG", "tax_regime": 1,
                    "recipient_profile": "consumer_final", "ncm_prefix": "21"},
                "outcome": {"cfop": "5102", "icms_code": "102", "pis_cst": "07",
                    "cofins_cst": "07", "nfe_rates": {"icms_rate": "0",
                        "pis_rate": "0", "cofins_rate": "0",
                        "pis_base": "net", "cofins_base": "net"}},
            }],
        }
        raw = json.dumps(policy).encode()
        digest = hashlib.sha256(raw).hexdigest()
        name = sale_policy_key(scope, kind)
        (root / (name + ".json")).write_bytes(raw)
        (root / (name + ".sha256")).write_text(digest)
        policies[kind.value] = digest
    calls = []

    class Vault:
        def resolve(self, **kwargs):
            calls.append(kwargs)
            assert kwargs["issuer_cnpj"] == issuer.cnpj.value
            return signing_material

    monkeypatch.setattr(EncryptedA1Vault, "from_environ", staticmethod(lambda: Vault()))
    payload = {
        "unit_id": "unit", "environment": "homologation", "document_kind": "nfce",
        "source_id": "sale-1", "issued_at": now.isoformat(),
        "policy_sha256": policies["nfce"], "recipient": None,
        "items": [{"product_id": "p1", "quantity": "2", "unit_price": "5.00",
            "discount": "0.00", "freight": "0.00", "other": "0.00"}],
        "payments": [{"method": "cash", "amount": "20.00"}], "change_amount": "10.00",
    }
    return db, scope, payload, policies, calls, root


def test_nfce_http_preparation_signature_schema_replay_restart_and_numbering(
    sale_setup, signing_material,
):
    db, scope, payload, policies, calls, root = sale_setup
    web = client(db)
    review = post(web, {k: payload[k] for k in ("unit_id", "environment", "document_kind")},
        operation="reviewNativeSale")
    assert review.status_code == 200, review.text
    assert review.json()["policy_sha256"] == policies["nfce"]
    assert calls == []
    first = post(web, payload)
    assert first.status_code == 200, first.text
    identifier = first.json()["document_id"]
    assert first.json()["transmitted"] is False
    assert first.json()["status"] == "ready_to_transmit"
    app = FiscalApplicationService(db)
    prepared = app.load_prepared_document_authorization(scope, identifier)
    assert prepared.access_key.value[20:22] == "65"
    assert prepared.access_key.value[25:34] == "000000001"
    OfficialNfeEnvelopeValidator()(prepared.signed_xml)
    xml = etree.fromstring(prepared.signed_xml)
    verify_official_nfe4_signature(xml, signing_material)
    ns = {"n": "http://www.portalfiscal.inf.br/nfe"}
    assert xml.xpath("string(//n:vTroco)", namespaces=ns) == "10.00"
    assert xml.xpath("string(//n:qrCode)", namespaces=ns).endswith(
        prepared.access_key.value + "|3|2")
    assert not xml.xpath("//n:dest", namespaces=ns)
    # Recreate HTTP executor; persisted replay must not open or sign with A1 again.
    again = post(client(db), payload)
    assert again.status_code == 200, again.text
    assert again.json()["replay"] is True and len(calls) == 1
    assert post(web, payload | {"change_amount": "9.00"}, "another").status_code == 409
    # Policy is archived exactly once; both replay and conflict preserve fiscal number.
    with db() as uow:
        assert len(uow.archive.list_for_document(scope, identifier)) == 2
        assert len([a for a in uow.archive.list_for_scope(scope)
            if a.media_type == "application/vnd.nfcore.sale-fiscal-policy.v1+json"]) == 1
    next_sale = post(web, payload | {"source_id": "sale-2"}, "second")
    assert next_sale.status_code == 200, next_sale.text
    second = app.load_prepared_document_authorization(scope, next_sale.json()["document_id"])
    assert second.access_key.value[25:34] == "000000002"
    recipient = {"document": "12345678000195", "name": "Synthetic recipient",
        "street": "Rua Sintetica", "number": "1", "district": "Centro",
        "municipality_name": "Belo Horizonte", "municipality_ibge_code": "3106200",
        "state": "MG", "postal_code": "30110000", "ie_indicator": 9, "final_consumer": True}
    nfe = post(web, payload | {"document_kind": "nfe", "policy_sha256": policies["nfe"],
        "recipient": recipient, "payments": [{"method": "pix", "amount": "10.00"}],
        "change_amount": "0.00"}, "nfe-attempt")
    assert nfe.status_code == 200, nfe.text
    prepared55 = app.load_prepared_document_authorization(scope, nfe.json()["document_id"])
    assert prepared55.access_key.value[20:22] == "55"
    assert prepared55.access_key.value[25:34] == "000000001"


@pytest.mark.parametrize("mutation", [
    {"tenant_id": "foreign"}, {"unit_id": "foreign"}, {"environment": "production"},
    {"provider_id": "arbitrary"}, {"policy_sha256": "0" * 64},
    {"items": []}, {"payments": []}, {"document_kind": "nfse"},
])
def test_sale_rejects_spoofing_and_invalid_facts_without_preparation(sale_setup, mutation):
    db, scope, payload, policies, calls, root = sale_setup
    response = post(client(db), payload | mutation)
    assert response.status_code in {400, 403, 409}, response.text
    with db() as uow:
        assert not uow.lifecycle.list_for_scope(scope)
    assert calls == []


def test_manual_sale_csrf_permission_and_foreign_tenant(sale_setup):
    db, scope, payload, policies, calls, root = sale_setup
    web = client(db)
    assert web.post("/v1/portal/operations/prepareNativeSale", json=payload).status_code == 403
    assert post(client(db, role=PortalRole.AUDITOR), payload).status_code == 403
    assert post(client(db, tenant="foreign"), payload).status_code in {400, 403}
    assert calls == []


def test_invalid_payment_rolls_back_allocation_and_can_be_corrected(sale_setup):
    db, scope, payload, policies, calls, root = sale_setup
    web = client(db)
    invalid = copy.deepcopy(payload)
    invalid["payments"][0]["amount"] = "15.00"
    assert post(web, invalid).status_code == 400
    with db() as uow:
        assert not uow.lifecycle.list_for_scope(scope)
    valid = post(web, payload)
    assert valid.status_code == 200, valid.text
    prepared = FiscalApplicationService(db).load_prepared_document_authorization(scope,
        valid.json()["document_id"])
    assert prepared.access_key.value[25:34] == "000000001"


def test_policy_digest_tampering_is_rejected_before_a1(sale_setup):
    db, scope, payload, policies, calls, root = sale_setup
    path = root / (sale_policy_key(scope, FiscalDocumentKind.NFCE) + ".json")
    path.write_bytes(path.read_bytes() + b" ")
    assert post(client(db), payload).status_code == 400
    assert calls == []


def test_replay_survives_policy_removal_and_claims_new_command_key(sale_setup):
    db, scope, payload, policies, calls, root = sale_setup
    web = client(db)
    first = post(web, payload)
    assert first.status_code == 200, first.text
    for path in root.iterdir():
        path.unlink()
    again = post(web, payload, "retry-after-rotation")
    assert again.status_code == 200 and again.json()["document_id"] == first.json()["document_id"]
    assert len(calls) == 1
    conflict = post(web, payload | {"source_id": "different"}, "retry-after-rotation")
    assert conflict.status_code == 409


def test_no_matching_tax_rule_is_controlled_without_preparation(sale_setup):
    db, scope, payload, policies, calls, root = sale_setup
    name = sale_policy_key(scope, FiscalDocumentKind.NFCE)
    path = root / (name + ".json")
    policy = json.loads(path.read_bytes())
    policy["rules"][0]["selector"]["ncm_prefix"] = "99"
    raw = json.dumps(policy).encode()
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    (root / (name + ".sha256")).write_text(digest)
    result = post(client(db), payload | {"policy_sha256": digest})
    assert result.status_code == 400, result.text
    assert calls == []


def test_legal_counter_converges_hosts_units_and_rejects_other_tenant(sale_setup):
    from concurrent.futures import ThreadPoolExecutor

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.numbering import FiscalSequenceKey, SequenceStateError

    db, scope, *_ = sale_setup
    app = FiscalApplicationService(db)
    key = FiscalSequenceKey.from_scope(scope, model=ElectronicInvoiceModel.NFE,
        series=7, issuer_cnpj="12345678000195")
    other_channel = replace(key, host_namespace="bling", unit_id="unit-other")
    # Concurrent transactions must share one legal stream, not merely count
    # sequential calls in one host partition. Runs on SQLite and PostgreSQL.
    with ThreadPoolExecutor(max_workers=4) as pool:
        numbers = list(pool.map(lambda i: app.reserve_number(
            key if i % 2 else other_channel).number, range(8)))
    assert sorted(numbers) == list(range(1, 9))
    with db() as uow:
        assert uow.sequences.last_reserved(key) == uow.sequences.last_reserved(other_channel) == 8
    with pytest.raises(SequenceStateError, match="tenant"):
        app.reserve_number(replace(other_channel, tenant_id="foreign"))
    # Model 65 is an independent legal sequence.
    assert app.reserve_number(replace(key, model=ElectronicInvoiceModel.NFCE)).number == 1


def test_legal_numbering_adopts_legacy_high_water_and_rollback(sale_setup):
    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.numbering import FiscalSequenceKey, FiscalSequencePolicy

    db, scope, *_ = sale_setup
    key = FiscalSequenceKey.from_scope(scope, model=ElectronicInvoiceModel.NFE,
        series=9, issuer_cnpj="12345678000195")
    with db() as uow:
        # Pre-upgrade row; the new code must never start this issuer at one.
        uow.sequences._connection.execute("""INSERT INTO fm_fiscal_sequences
            (host_namespace,tenant_id,unit_id,environment,model,series,
             first_number,max_number,last_reserved) VALUES (?,?,?,?,?,?,?,?,?)""",
            (scope.host_namespace, scope.tenant_id, scope.unit_id, "homologation",55,9,1,None,42))
        uow.commit()
    with db() as uow:
        assert uow.sequences.reserve_next(key, FiscalSequencePolicy()).number == 43
        # rollback the first adoption and reservation together
    app = FiscalApplicationService(db)
    assert app.reserve_number(key).number == 43
    # Legacy callers resolve the unique persisted issuer; no parallel writer.
    assert app.reserve_number(replace(key, issuer_cnpj=None)).number == 44


def test_legal_numbering_rejects_unbound_durable_writer(sale_setup):
    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.numbering import FiscalSequenceKey, SequenceStateError

    db, scope, *_ = sale_setup
    key = FiscalSequenceKey.from_scope(replace(scope, unit_id="unconfigured"),
        model=ElectronicInvoiceModel.NFE, series=1)
    with pytest.raises(SequenceStateError, match="issuer"):
        FiscalApplicationService(db).reserve_number(key)


def test_policy_installer_uses_same_validator_and_scope(sale_setup, tmp_path):
    from kordena_fiscal.runtime.native_sale_policy import install_reviewed_policy, load_sale_policy

    db, scope, payload, policies, calls, root = sale_setup
    name = sale_policy_key(scope, FiscalDocumentKind.NFCE)
    destination = tmp_path / "installed-policies"
    assert install_reviewed_policy(root / (name + ".json"), destination) == name
    _, digest, _ = load_sale_policy({"NFCORE_SALE_FISCAL_POLICY_ROOT": str(destination)},
        scope, FiscalDocumentKind.NFCE)
    assert digest == policies["nfce"]


@pytest.mark.parametrize("kind", ["nfe", "nfce"])
def test_http_sale_prepare_emit_query_xml_and_pdf(sale_setup, signing_material, kind):
    from kordena_fiscal.gateway.nfe_sp_homologation import (
        build_mg_nfce_homologation_gateway,
        build_mg_nfe_homologation_gateway,
    )
    from kordena_fiscal.operations import FakeFiscalOperationsGateway
    from kordena_fiscal.runtime.canonical_fiscal_composition import (
        build_runtime_fiscal_handler_factory,
    )
    from kordena_fiscal.runtime.fiscal_runtime import (
        CanonicalFiscalOperationPath,
        CanonicalPortalOperationExecutor,
    )

    db, scope, payload, policies, calls, root = sale_setup
    if kind == "nfe":
        payload = payload | {
            "document_kind": kind, "policy_sha256": policies[kind], "change_amount": "0.00",
            "payments": [{"method": "pix", "amount": "10.00"}],
            "recipient": {"document": "12345678000195", "name": "Synthetic recipient",
                "street": "Rua Sintetica", "number": "1", "district": "Centro",
                "municipality_name": "Belo Horizonte", "municipality_ibge_code": "3106200",
                "state": "MG", "postal_code": "30110000", "ie_indicator": 9,
                "final_consumer": True},
        }
    exchange_calls = []
    ns = "http://www.portalfiscal.inf.br/nfe"

    def exchange(soap, *_args):
        exchange_calls.append(soap)
        xml = etree.fromstring(soap)
        verify_official_nfe4_signature(xml.find(f".//{{{ns}}}enviNFe"), signing_material)
        key = xml.find(f".//{{{ns}}}infNFe").get("Id")[3:]
        digest = xml.findtext(".//{http://www.w3.org/2000/09/xmldsig#}DigestValue")
        return (
            '<Envelope xmlns="http://www.w3.org/2003/05/soap-envelope"><Body>'
            f'<retEnviNFe xmlns="{ns}" versao="4.00"><tpAmb>2</tpAmb>'
            '<verAplic>synthetic</verAplic><cStat>104</cStat><xMotivo>Lote processado</xMotivo>'
            '<cUF>31</cUF><dhRecbto>2026-11-16T12:00:00-03:00</dhRecbto>'
            '<protNFe versao="4.00"><infProt><tpAmb>2</tpAmb><verAplic>synthetic</verAplic>'
            f'<chNFe>{key}</chNFe><dhRecbto>2026-11-16T12:00:00-03:00</dhRecbto>'
            f'<nProt>131000000000001</nProt><digVal>{digest}</digVal>'
            '<cStat>100</cStat><xMotivo>Autorizado teste sintetico</xMotivo>'
            '</infProt></protNFe></retEnviNFe></Body></Envelope>'
        ).encode()

    builder = (
        build_mg_nfce_homologation_gateway if kind == "nfce"
        else build_mg_nfe_homologation_gateway
    )
    gateway = builder(
        resolve_certificate=lambda *_args: signing_material, exchange=exchange)
    app = FiscalApplicationService(db)
    query_gateway = FakeFiscalOperationsGateway()
    handlers = build_runtime_fiscal_handler_factory(
        operations_gateway=query_gateway, authorization_gateway=gateway)(app)
    web = client(db, operation_executor=CanonicalPortalOperationExecutor(
        unit_of_work_factory=db, path=CanonicalFiscalOperationPath(app, handlers=handlers)))
    prepared = post(web, payload)
    assert prepared.status_code == 200, prepared.text
    identifier = prepared.json()["document_id"]
    params = {"unit_id": "unit", "environment": "homologation"}
    url = f"/v1/portal/documents/{identifier}/artifacts/"
    assert web.get(url + "authorized_xml", params=params).status_code == 404
    body = params | {"document_id": identifier}
    issued = post(web, body, "emit-manual", operation="issueFiscalDocument")
    assert issued.status_code == 200, issued.text
    assert issued.json()["status"] == "authorized"
    replay = post(web, body, "emit-retry", operation="issueFiscalDocument")
    assert replay.status_code == 200 and len(exchange_calls) == 1
    archived = web.get(url + "authorized_xml", params=params)
    assert archived.status_code == 200 and b"nfeProc" in archived.content
    assert b"SignatureValue" in archived.content
    verify_official_nfe4_signature(etree.fromstring(archived.content), signing_material)
    pdf = web.get(url + "auxiliary_pdf", params=params)
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b"%PDF")
    key = app.load_prepared_document_authorization(scope, identifier).access_key.value
    queried = post(web, params | {"access_key": key}, "query", operation="queryFiscalDocument")
    assert queried.status_code == 200, queried.text
    assert queried.json()["status"] == "authorized"
    assert len(query_gateway.query_calls) == 1 and len(exchange_calls) == 1
    forbidden = client(db, tenant="other")
    assert forbidden.get(url + "authorized_xml", params=params).status_code == 404
