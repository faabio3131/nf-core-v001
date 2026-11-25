# ruff: noqa: F811 -- imported pytest fixtures are requested by name.
"""T15 synthetic XMLs, reviewed apuracoes and actual isolated PostgreSQL/HTTP."""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import sys
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from test_bling_canonical import mapping  # noqa: F401
from test_t14_authorized_issuance import economy_database  # noqa: F401

from kordena_fiscal.application.federal_regime_store import declare_federal_regime
from kordena_fiscal.application.historical_audit import (
    TABLE,
    import_month,
    record_id,
    source_bundle,
)
from kordena_fiscal.cognitive.composition import build_cognitive_router
from kordena_fiscal.cognitive.historical_audit_api import (
    build_historical_audit_runner,
    historical_issuer_context,
)
from kordena_fiscal.control_plane import (
    ControlPlaneAuditAction,
    ControlPlaneAuditEvent,
    FiscalOrganization,
    FiscalUnitRegistration,
)
from kordena_fiscal.domain import (
    Cnpj,
    ElectronicInvoiceModel,
    FiscalEnvironment,
    FiscalValidationError,
    TaxRegimeCode,
)
from kordena_fiscal.security.human_identity import (
    HumanAccount,
    HumanIdentityService,
    InMemoryHumanAccountRepository,
    InMemoryWebSessionRepository,
    PortalRole,
    ScryptPasswordHasher,
)
from kordena_fiscal.tax.historical_audit import IssuerContext, Month, analyze_month, closed_months
from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime
from kordena_fiscal.web import create_app
from kordena_fiscal.web.human_auth import CSRF_COOKIE, CSRF_HEADER
from kordena_fiscal.web.portal_runtime import DurableHumanPortalExecutor
from kordena_fiscal.xml.access_key import AccessKeyInput, build_access_key

ISSUER = Cnpj("12345678000195")
MONTH = date(2026, 1, 1)
TODAY = date(2026, 11, 24)
NS = "http://www.portalfiscal.inf.br/nfe"


def _artifact(ref, kind, content=None):
    raw = content or ("SYNTHETIC TEST EVIDENCE " + ref).encode()
    return {
        "reference": ref,
        "kind": kind,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "data_b64": base64.b64encode(raw).decode(),
    }


def _xml(period, number, crt=3, issuer=ISSUER, model=55):
    issued = datetime(period.year, period.month, 15, 12, tzinfo=UTC)
    key = build_access_key(
        AccessKeyInput(
            "35",
            issued,
            issuer,
            ElectronicInvoiceModel(model),
            1,
            number,
            1,
            number,
        )
    ).value
    parts = []
    for i, (ncm, pis, cofins, icms, rate_p, rate_c) in enumerate(
        [
            ("30049099", "1.00", "2.00", "18.00", "1.00", "2.00"),
            ("22030000", "1.00", "2.00", None, "1.00", "2.00"),
            ("10063021", "1.65", "7.60", "18.00", "1.65", "7.60"),
        ],
        1,
    ):
        icms_xml = (
            "<ICMS60><orig>0</orig><CST>60</CST><vBCSTRet>100.00</vBCSTRet>"
            "<vICMSSTRet>12.00</vICMSSTRet></ICMS60>"
            if icms is None
            else f"<ICMS00><orig>0</orig><CST>00</CST><vBC>100.00</vBC>"
            f"<pICMS>18.00</pICMS><vICMS>{icms}</vICMS></ICMS00>"
        )
        parts.append(
            f'<det nItem="{i}"><prod><NCM>{ncm}</NCM><CFOP>5102</CFOP>'
            f"</prod><imposto><ICMS>{icms_xml}</ICMS>"
            f"<PIS><PISAliq><CST>01</CST><vBC>100.00</vBC><pPIS>{rate_p}</pPIS>"
            f"<vPIS>{pis}</vPIS></PISAliq></PIS>"
            f"<COFINS><COFINSAliq><CST>01</CST><vBC>100.00</vBC><pCOFINS>{rate_c}</pCOFINS>"
            f"<vCOFINS>{cofins}</vCOFINS></COFINSAliq></COFINS></imposto></det>"
        )
    raw = (
        f'<nfeProc xmlns="{NS}" versao="4.00"><NFe><infNFe Id="NFe{key}" versao="4.00">'
        f"<ide><cUF>35</cUF><cNF>{number:08}</cNF><mod>{model}</mod><serie>1</serie><nNF>{number}</nNF>"
        f"<dhEmi>{issued.isoformat()}</dhEmi><tpNF>1</tpNF><tpEmis>1</tpEmis>"
        f"<cDV>{key[-1]}</cDV><tpAmb>1</tpAmb><finNFe>1</finNFe></ide>"
        f"<emit><CNPJ>{issuer.value}</CNPJ><enderEmit><UF>SP</UF></enderEmit><CRT>{crt}</CRT></emit>"
        + "".join(parts)
        + f'</infNFe></NFe><protNFe versao="4.00"><infProt><tpAmb>1</tpAmb><chNFe>{key}</chNFe>'
        "<nProt>135000000000001</nProt><cStat>100</cStat></infProt></protNFe></nfeProc>"
    ).encode()
    return raw


def fixture(period=MONTH, count=1, receipt="receipt-1", crt=3):
    artifacts = [
        _artifact("coverage", "coverage"),
        _artifact("assessment", "assessment"),
        _artifact("status", "status"),
        _artifact(receipt, "payment"),
    ]
    catalog, citations = [], []
    for name, ncm, fed, local in (
        ("rule-mono", "30049099", "monophase_downstream", "ordinary"),
        ("rule-st", "22030000", "ordinary", "icms_substituted"),
        ("rule-base", "10063021", "ordinary", "ordinary"),
        ("base-review", None, "ordinary", "ordinary"),
    ):
        artifact = _artifact(name, "legal")
        artifacts.append(artifact)
        url = "https://www.gov.br/teste-sintetico/" + name
        citations.append(
            {
                "act": "Synthetic rule — not legislation",
                "provision": "synthetic",
                "source_url": url,
                "source_sha256": artifact["sha256"],
                "published_on": "2020-01-01",
                "valid_from": "2020-01-01",
                "valid_until": "2027-01-01",
                "review_reference": name,
            }
        )
        if ncm is not None:
            catalog.append(
                {
                    "ncm": ncm,
                    "cest": None,
                    "cfop": "5102",
                    "uf": "SP",
                    "activity": "commerce",
                    "market": "domestic",
                    "regime": "lucro_real" if crt == 3 else "simples_nacional",
                    "operation_context": "resale",
                    "valid_from": "2020-01-01",
                    "valid_until": "2027-01-01",
                    "source_url": url,
                    "rule_reference": name,
                    "federal": fed,
                    "local": local,
                }
            )
    docs = []
    for number in range(1, count + 1):
        raw = _xml(period, number, crt)
        items = []
        for i, (name, values) in enumerate(
            [
                ("rule-mono", (100, 200, 1800)),
                ("rule-st", (100, 200, 1200)),
                ("rule-base", (165, 760, 1800)),
            ],
            1,
        ):
            allocations = []
            for tax, amount in zip(("pis", "cofins", "icms"), values, strict=True):
                base = 8200 if crt == 3 and i == 3 and tax in {"pis", "cofins"} else None
                allocations.append(
                    {
                        "tax": tax,
                        "declared_cents": amount,
                        "reviewed_base_cents": base,
                        "base_review_reference": "base-review" if base is not None else None,
                        "base_mode": "xml_base_less_own_icms" if base is not None else None,
                        "reviewed_rate": ("1.65" if tax == "pis" else "7.60")
                        if base is not None
                        else None,
                        "assessment_reference": "assessment",
                        "treatment_reference": name,
                    }
                )
            items.append(
                {
                    "number": i,
                    "activity": "commerce",
                    "operation_context": "resale",
                    "allocations": allocations,
                }
            )
        docs.append(
            {
                "xml_b64": base64.b64encode(raw).decode(),
                "xml_sha256": hashlib.sha256(raw).hexdigest(),
                "status_reference": "status",
                "status": "active",
                "items": items,
            }
        )
    controls = {
        tax: value * count
        for tax, value in (
            ("pis", 365),
            ("cofins", 1160),
            ("icms", 4800),
        )
    }
    collection = "direct" if crt == 3 else "das_components"
    return {
        "competence": period.isoformat(),
        "review_status": "reviewed",
        "review_reference": "synthetic-review",
        "coverage_reference": "coverage",
        "coverage_complete": True,
        "collection": collection,
        "regime": "lucro_real" if crt == 3 else "simples_nacional",
        "citations": citations,
        "catalog": catalog,
        "artifacts": artifacts,
        "documents": docs,
        "controls": [
            {
                "tax": k,
                "declared_principal_cents": v,
                "assessment_reference": "assessment",
                "payment_history_complete": True,
                "payment_history_reference": "coverage",
                "no_unresolved_adjustments": True,
            }
            for k, v in controls.items()
        ],
        "payments": [
            {
                "receipt_id": receipt,
                "issuer_cnpj": ISSUER.value,
                "competence": period.isoformat(),
                "paid_on": period.replace(day=20).isoformat(),
                "collection": collection,
                "evidence_reference": receipt,
                "principal_cents": sum(controls.values()) + 100,
                "allocations": controls,
                "other_principal_cents": 100,
            }
        ],
    }


def _context(crt=3):
    return IssuerContext.model_validate(
        {
            "uf": "SP",
            "state_ibge_code": "35",
            "crt": crt,
            "regime": "lucro_real" if crt == 3 else "simples_nacional",
            "profile_id": "synthetic",
            "profile_version": 1,
            "cnae": "4711302",
        }
    )


def _run(data, period=MONTH, crt=3):
    return analyze_month(Month.model_validate(data), ISSUER, period, _context(crt), as_of=TODAY)


def _replace_xml(data, raw):
    doc = data["documents"][0]
    doc["xml_b64"] = base64.b64encode(raw).decode()
    doc["xml_sha256"] = hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("model,cfop,status", [(65, "5102", "100"), (55, "6102", "150")])
def test_authorized_document_variants(model, cfop, status):
    data = fixture()
    raw = _xml(MONTH, 1, model=model).replace(b"5102</CFOP>", cfop.encode() + b"</CFOP>")
    _replace_xml(data, raw.replace(b"100</cStat>", status.encode() + b"</cStat>"))
    for rule in data["catalog"]:
        rule["cfop"] = cfop
    assert _run(data)["groups"] == _run(fixture())["groups"]


@pytest.mark.parametrize("status", ["110", None])
def test_unauthorized_or_missing_protocol(status):
    data = fixture()
    raw = _xml(MONTH, 1)
    if status is None:
        raw = raw[: raw.index(b"<protNFe ")] + b"</nfeProc>"
    else:
        raw = raw.replace(b"100</cStat>", status.encode() + b"</cStat>")
    _replace_xml(data, raw)
    with pytest.raises(FiscalValidationError):
        _run(data)


@pytest.mark.parametrize("number", ["01", "+1", " 1", "1 ", "١", "1_0", "0", "991", ""])
def test_item_number_preserves_xsd_lexical_space(number):
    data = fixture()
    raw = _xml(MONTH, 1).replace(b'nItem="1"', f'nItem="{number}"'.encode())
    _replace_xml(data, raw)
    with pytest.raises(FiscalValidationError):
        _run(data)


def test_exact_window_and_leap_boundary():
    months = closed_months(date(2026, 10, 1), TODAY)
    assert len(months) == 60 and months[0] == date(2021, 11, 1)
    assert months[-1] == date(2026, 10, 1) and len(set(months)) == 60
    for invalid in (TODAY, date(2026, 11, 1), date(2027, 1, 1), date(5, 1, 1)):
        with pytest.raises(FiscalValidationError):
            closed_months(invalid, TODAY)


def test_normal_regime_item_reconciliation_exact_cents():
    report = _run(fixture())
    assert report["item_count"] == 3
    assert [g["paid_candidate_cents"] for g in report["groups"]] == [130, 337, 1200]
    assert [g["reviewed_due_cents"] for g in report["groups"]] == [235, 823, 3600]
    lines = report["documents"][0]["findings"]
    assert sum(x["paid_candidate_cents"] or 0 for x in lines) == 1667
    st = next(x for x in lines if x["item_number"] == 2 and x["tax"] == "icms")
    assert st["xml_tax"]["amount_cents"] is None  # vICMSSTRet is never treated as own ICMS.
    assert st["reason"] == "icms_substituted"
    assert st["difference_cents"] == 1200
    assert report["credit_recognized"] is False and report["realized_cents"] is None


def test_historical_simples_das_uses_reviewed_allocations_not_current_rates():
    period = date(2022, 2, 1)
    report = _run(fixture(period, crt=1), period, 1)
    assert [g["paid_candidate_cents"] for g in report["groups"]] == [100, 200, 1200]
    assert all(g["collection"] == "das_components" for g in report["groups"])


@pytest.mark.parametrize(
    "change",
    [
        "partial",
        "unpaid",
        "adjustments",
        "coverage",
        "ambiguous",
        "mixed",
        "unresolved_document",
        "mismatched_control",
    ],
)
def test_incomplete_or_mixed_data_never_assigns_paid_candidate(change):
    data = fixture()
    if change == "partial":
        data["controls"][0]["payment_history_complete"] = False
    elif change == "unpaid":
        data["payments"] = []
    elif change == "adjustments":
        data["controls"][0]["no_unresolved_adjustments"] = False
    elif change == "coverage":
        data["coverage_complete"] = False
    elif change == "ambiguous":
        data["catalog"].append(copy.deepcopy(data["catalog"][0]))
    elif change == "mixed":
        data["documents"][0]["items"][2]["allocations"][0]["reviewed_base_cents"] = 12000
        data["documents"][0]["items"][2]["allocations"][0]["base_mode"] = "reviewed_amount"
    elif change == "unresolved_document":
        data["documents"][0]["status"] = "unresolved"
        data["documents"][0]["items"] = []
    else:
        data["controls"][0]["declared_principal_cents"] += 1
    report = _run(data)
    assert report["groups"][0]["paid_candidate_cents"] is None
    assert report["credit_recognized"] is False


@pytest.mark.parametrize(
    "change",
    [
        "bad_xml_hash",
        "duplicate_xml",
        "missing_item",
        "foreign_issuer",
        "bad_key",
        "dtd",
        "wrong_period",
        "test_environment",
        "duplicate_receipt",
        "receipt_other_issuer",
        "receipt_future",
        "receipt_wrong_period",
        "receipt_unbalanced",
        "legal_hash",
        "legal_expired",
        "base_without_citation",
        "base_wrong_tax",
        "cancelled_with_items",
        "allocation_reference",
        "foreign_scope_rule",
        "float_amount",
        "duplicate_artifact",
    ],
)
def test_malformed_or_unsupported_evidence_fails_closed(change):
    data = fixture()
    doc = data["documents"][0]
    if change == "bad_xml_hash":
        doc["xml_sha256"] = "0" * 64
    elif change == "duplicate_xml":
        data["documents"].append(copy.deepcopy(doc))
    elif change == "missing_item":
        doc["items"].pop()
    elif change in {"foreign_issuer", "bad_key", "dtd", "wrong_period", "test_environment"}:
        raw = base64.b64decode(doc["xml_b64"])
        if change == "foreign_issuer":
            raw = _xml(MONTH, 1, issuer=Cnpj("11222333000181"))
        elif change == "bad_key":
            raw = raw.replace(b"<cNF>00000001</cNF>", b"<cNF>00000002</cNF>")
        elif change == "dtd":
            raw = b'<!DOCTYPE nfeProc [<!ENTITY x "boom">]>' + raw
        elif change == "wrong_period":
            raw = _xml(date(2026, 2, 1), 1)
        else:
            raw = raw.replace(b"<tpAmb>1</tpAmb>", b"<tpAmb>2</tpAmb>")
        doc["xml_b64"] = base64.b64encode(raw).decode()
        doc["xml_sha256"] = hashlib.sha256(raw).hexdigest()
    elif change == "duplicate_receipt":
        data["payments"].append(copy.deepcopy(data["payments"][0]))
    elif change == "receipt_other_issuer":
        data["payments"][0]["issuer_cnpj"] = "11222333000181"
    elif change == "receipt_future":
        data["payments"][0]["paid_on"] = "2026-12-01"
    elif change == "receipt_wrong_period":
        data["payments"][0]["competence"] = "2026-02-01"
    elif change == "receipt_unbalanced":
        data["payments"][0]["principal_cents"] += 1
    elif change == "legal_hash":
        data["citations"][0]["source_sha256"] = "0" * 64
    elif change == "legal_expired":
        data["citations"][0]["valid_until"] = "2026-01-15"
    elif change == "base_without_citation":
        doc["items"][2]["allocations"][0]["base_review_reference"] = None
    elif change == "base_wrong_tax":
        doc["items"][2]["allocations"][2]["reviewed_base_cents"] = 8200
    elif change == "cancelled_with_items":
        doc["status"] = "cancelled"
    elif change == "allocation_reference":
        doc["items"][0]["allocations"][0]["assessment_reference"] = "coverage"
    elif change == "foreign_scope_rule":
        data["catalog"][2]["rule_reference"] = "missing"
    elif change == "float_amount":
        doc["items"][0]["allocations"][0]["declared_cents"] = 1.0
    else:
        data["artifacts"].append(copy.deepcopy(data["artifacts"][0]))
    with pytest.raises((FiscalValidationError, ValueError)):
        _run(data)


def _setup(db, mapping):
    scope = replace(mapping["issuer"].scope, host_namespace="fm-nfcore")
    profile = replace(
        mapping["issuer"],
        scope=scope,
        cnpj=ISSUER,
        tax_regime=TaxRegimeCode.NORMAL,
        effective_from=datetime(2021, 1, 1, tzinfo=UTC),
    )
    with db() as uow:
        uow.control_plane.add_organization(FiscalOrganization(scope.tenant_id, "Synthetic T15"))
        uow.control_plane.add_unit(
            FiscalUnitRegistration(
                scope.tenant_id,
                scope.unit_id,
                "Synthetic",
                frozenset({FiscalEnvironment.HOMOLOGATION}),
            )
        )
        uow.control_plane.append_audit(
            ControlPlaneAuditEvent(
                event_id="synthetic-t15-unit-onboarded",
                occurred_at=datetime.now(UTC),
                actor_id="synthetic-t15",
                action=ControlPlaneAuditAction.UNIT_ONBOARDED,
                target_type="unit",
                target_id=scope.unit_id,
                correlation_id="synthetic-t15",
                tenant_id=scope.tenant_id,
                unit_id=scope.unit_id,
            )
        )
        uow.control_plane.add_profile(profile)
        uow.commit()
    declare_federal_regime(
        db,
        scope=scope,
        crt=TaxRegimeCode.NORMAL,
        issuer_cnpj=ISSUER,
        federal_income_tax_regime=FederalIncomeTaxRegime.LUCRO_REAL,
        effective_from=datetime(2021, 1, 1, tzinfo=UTC),
        source_reference="synthetic-regime-t15",
        actor="synthetic-t15",
        idempotency_key="synthetic-regime-t15",
        occurred_at=datetime.now(UTC),
    )
    return scope


def _client(db, scope, role="owner", configured=True):
    hasher = ScryptPasswordHasher()
    password = "Synthetic-only-T15-test-password"
    account = HumanAccount(
        "synthetic-t15-" + role,
        role + "@example.test",
        hasher.hash(password),
        scope.tenant_id,
        PortalRole(role),
        frozenset({scope.unit_id}),
    )
    identity = HumanIdentityService(
        accounts=InMemoryHumanAccountRepository((account,)),
        sessions=InMemoryWebSessionRepository(),
        password_hasher=hasher,
    )
    reader = DurableHumanPortalExecutor(db)
    runner = build_historical_audit_runner(
        reader,
        lambda current: db.economy(current, read_only=True),
        db,
    )
    router = build_cognitive_router(
        identity,
        reader,
        {"NFCORE_COGNITIVE_ENABLED": "true"},
        historical_audit_runner=runner if configured else None,
    )
    client = TestClient(
        create_app(human_identity=identity, portal_executor=reader, cognitive_router=router),
        base_url="https://nfcore.test",
    )
    assert (
        client.post(
            "/v1/auth/login", json={"email": account.email, "password": password}
        ).status_code
        == 200
    )
    return client


def _post(client, body, csrf=True):
    return client.post(
        "/v1/portal/cognitive/economy/historical-audit",
        json=body,
        headers={CSRF_HEADER: client.cookies.get(CSRF_COOKIE)} if csrf else {},
    )


def _cli(db, scope, data, tmp_path, monkeypatch):
    from pathlib import Path

    path = Path(__file__).parents[1] / "scripts/nfcore_historical_audit_import.py"
    spec = importlib.util.spec_from_file_location("t15_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bundle = tmp_path / "t15-bundle.json"
    bundle.write_text(
        json.dumps(
            {
                "tenant": scope.tenant_id,
                "unit": scope.unit_id,
                "issuer_cnpj": ISSUER.value,
                "version": 1,
                "facts": data,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NFCORE_ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_URL", db._dsn)
    monkeypatch.setattr(
        sys, "argv", [str(path), str(bundle), "--tenant", scope.tenant_id, "--unit", scope.unit_id]
    )
    module.main()
    monkeypatch.setenv("NFCORE_ENVIRONMENT", "production")
    with pytest.raises(SystemExit) as caught:
        module.main()
    assert caught.value.code == 2
    monkeypatch.setenv("NFCORE_ENVIRONMENT", "test")


# Imported pytest fixtures come from the certified T14 integration.
def test_real_postgres_http_60_months_pages_and_receipt_deduplication(
    economy_database,
    mapping,
    tmp_path,
    monkeypatch,
):
    db = economy_database
    scope = _setup(db, mapping)
    _, context = historical_issuer_context(db, scope, MONTH)
    data = fixture(count=12)
    _cli(db, scope, data, tmp_path, monkeypatch)
    with db.economy(scope) as store:
        assert import_month(
            store, ISSUER, MONTH, 1, Month.model_validate(data), context=context, as_of=TODAY
        )["replay"]
        row = store.record(TABLE, record_id(ISSUER, MONTH), 1)
        assert source_bundle(store, ISSUER, MONTH, row).model_dump() == (
            Month.model_validate(data).model_dump()
        )
        changed = copy.deepcopy(data)
        changed["coverage_complete"] = False
        with pytest.raises(FiscalValidationError, match="conflict"):
            import_month(
                store, ISSUER, MONTH, 1, Month.model_validate(changed), context=context, as_of=TODAY
            )
    client = _client(db, scope)
    body = {
        "unit_id": scope.unit_id,
        "environment": scope.environment.value,
        "competence": "2026-02-01",
    }
    anonymous = TestClient(client.app, base_url="https://nfcore.test")
    assert _post(anonymous, body, csrf=False).status_code == 401
    assert _post(client, body, csrf=False).status_code == 403
    assert _post(client, body | {"tenant_id": "forged"}).status_code == 400
    assert _post(client, body | {"unit_id": "foreign"}).status_code == 403
    assert _post(_client(db, scope, role="operator"), body).status_code == 403
    assert _post(_client(db, scope, configured=False), body).status_code == 503
    assert _post(client, body | {"competence": "2099-01-01"}).status_code == 422
    response = _post(client, body)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["competences"] == 60 and len(report["months"]) == 60
    assert report["window_start"] == "2021-03-01"
    assert report["reviewed_months"] == 1 and report["status"] == "partial_basis"
    assert report["partial_totals_by_tax"]["pis"] == {
        "classified_months": 1,
        "paid_candidate_cents": 1560,
    }
    january = next(m for m in report["months"] if m["competence"] == MONTH.isoformat())
    assert january["pages"] == 2 and january["finding_count"] == 108
    detail = {
        "month": MONTH.isoformat(),
        "page": 0,
        "snapshot_digest": january["snapshot"]["digest"],
        "window_digest": report["window_digest"],
    }
    page = _post(client, body | {"detail": detail}).json()
    assert len(page["rows"]) == 100 and page["next_page"] == 1
    assert "xml_b64" not in json.dumps(page) and "data_b64" not in json.dumps(page)
    tail = _post(client, body | {"detail": detail | {"page": 1}}).json()
    assert len(tail["rows"]) == 8 and tail["next_page"] is None
    assert _post(client, body | {"detail": detail | {"page": 2}}).status_code == 422
    assert _post(client, body | {"detail": detail | {"page": True}}).status_code == 400
    for other in (
        replace(scope, tenant_id="foreign"),
        replace(scope, unit_id="foreign"),
        replace(scope, host_namespace="foreign"),
        replace(scope, environment=FiscalEnvironment.PRODUCTION),
    ):
        with db.economy(other, read_only=True) as store:
            assert store.record(TABLE, record_id(ISSUER, MONTH)) is None
    february = date(2026, 2, 1)
    with db.economy(scope) as store:
        import_month(
            store,
            ISSUER,
            february,
            1,
            Month.model_validate(fixture(february)),
            context=context,
            as_of=TODAY,
        )
    duplicate = _post(client, body).json()
    assert duplicate["partial_totals_by_tax"]["pis"]["paid_candidate_cents"] is None
    assert _post(client, body | {"detail": detail}).status_code == 409
    january = next(m for m in duplicate["months"] if m["competence"] == MONTH.isoformat())
    assert january["duplicate_receipt_in_window"]
    page = _post(
        client,
        body
        | {
            "detail": detail
            | {
                "window_digest": duplicate["window_digest"],
            }
        },
    ).json()
    assert all(item.get("paid_candidate_cents") is None for item in page["rows"])
    with db.economy(scope) as store:
        import_month(
            store,
            ISSUER,
            february,
            2,
            Month.model_validate(fixture(february, receipt="receipt-2")),
            context=context,
            as_of=TODAY,
        )
        assert store.record(TABLE, record_id(ISSUER, february), 1) is not None
    final = _post(client, body).json()
    assert final["reviewed_months"] == 2
    assert final["partial_totals_by_tax"]["pis"]["paid_candidate_cents"] == 1690
    # A failed write leaves no orphan source chunk or index.
    march = date(2026, 3, 1)
    with pytest.raises(RuntimeError, match="rollback"):
        with db.economy(scope) as store:
            import_month(
                store,
                ISSUER,
                march,
                1,
                Month.model_validate(fixture(march, receipt="receipt-3")),
                context=context,
                as_of=TODAY,
            )
            raise RuntimeError("rollback")
    with db.economy(scope, read_only=True) as store:
        assert store.record(TABLE, record_id(ISSUER, march)) is None
        assert store.record(TABLE, record_id(ISSUER, march) + "-source-0") is None

    end = date(2026, 10, 1)
    with db.economy(scope) as store:
        for period in closed_months(end, TODAY):
            if period in {MONTH, february}:
                continue
            imported = fixture(period, receipt="receipt-" + period.isoformat())
            import_month(
                store,
                ISSUER,
                period,
                1,
                Month.model_validate(imported),
                context=context,
                as_of=TODAY,
            )
    full = _post(client, body | {"competence": end.isoformat()})
    assert full.status_code == 200, full.text
    complete = full.json()
    assert complete["reviewed_months"] == 60 and complete["available_months"] == 60
    assert complete["partial_totals_by_tax"]["pis"] == {
        "classified_months": 60,
        "paid_candidate_cents": (60 + 11) * 130,
    }
    assert complete["credit_recognized"] is False
    assert sum(m["document_count"] for m in complete["months"]) == 71
    assert sum(m["item_count"] for m in complete["months"]) == 213
    assert sum(m["finding_count"] for m in complete["months"]) == 639
    assert complete["partial_totals_by_tax"]["cofins"]["paid_candidate_cents"] == 71 * 337
    assert complete["partial_totals_by_tax"]["icms"]["paid_candidate_cents"] == 71 * 1200


@pytest.mark.parametrize(
    "change", ["regime", "rule_regime", "rate", "double_exclusion", "state_code"]
)
def test_historical_context_and_reviewed_base_are_not_overrideable(change):
    data = fixture()
    context = _context()
    if change == "regime":
        data["regime"] = "lucro_presumido"
    elif change == "rule_regime":
        data["catalog"][0]["regime"] = "lucro_presumido"
    elif change == "rate":
        data["documents"][0]["items"][2]["allocations"][0]["reviewed_rate"] = "2"
    elif change == "double_exclusion":
        data["documents"][0]["items"][2]["allocations"][0]["reviewed_base_cents"] = 6400
    else:
        context = context.model_copy(update={"state_ibge_code": "31"})
    with pytest.raises(FiscalValidationError):
        analyze_month(Month.model_validate(data), ISSUER, MONTH, context, as_of=TODAY)


def test_explicit_reviewed_zero_activity_is_distinct_from_missing_or_cancelled():
    data = fixture()
    data["documents"][0]["status"] = "cancelled"
    data["documents"][0]["items"] = []
    data["payments"] = []
    for control in data["controls"]:
        control["declared_principal_cents"] = 0
    result = _run(data)
    assert result["document_count"] == 1 and result["item_count"] == 0
    assert result["documents"][0]["status"] == "cancelled"
    assert all(g["paid_candidate_cents"] == 0 for g in result["groups"])
    data["coverage_complete"] = False
    assert all(g["paid_candidate_cents"] is None for g in _run(data)["groups"])


def test_postgres_http_regime_revision_invalidates_prior_month(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping)
    _, old_context = historical_issuer_context(db, scope, MONTH)
    data = fixture()
    with db.economy(scope) as store:
        import_month(
            store, ISSUER, MONTH, 1, Month.model_validate(data), context=old_context, as_of=TODAY
        )
    client = _client(db, scope)
    body = {
        "unit_id": scope.unit_id,
        "environment": scope.environment.value,
        "competence": MONTH.isoformat(),
    }

    def current_month():
        response = _post(client, body)
        assert response.status_code == 200, response.text
        return response.json()["months"][-1]

    assert current_month()["status"] == "reviewed_scope"
    declare_federal_regime(
        db,
        scope=scope,
        crt=TaxRegimeCode.NORMAL,
        issuer_cnpj=ISSUER,
        federal_income_tax_regime=FederalIncomeTaxRegime.LUCRO_PRESUMIDO,
        effective_from=datetime(2025, 12, 1, tzinfo=UTC),
        source_reference="review-revision",
        actor="synthetic-t15",
        idempotency_key="review-revision",
        occurred_at=datetime.now(UTC),
    )
    changed = current_month()
    assert changed["status"] == "issuer_history_changed"
    assert changed["snapshot"] is None and changed["groups"] == []
    _, new_context = historical_issuer_context(db, scope, MONTH)
    assert new_context.regime == "lucro_presumido"
    data["regime"] = new_context.regime
    for rule in data["catalog"]:
        rule["regime"] = new_context.regime
    with db.economy(scope) as store:
        import_month(
            store, ISSUER, MONTH, 2, Month.model_validate(data), context=new_context, as_of=TODAY
        )
    revised = current_month()
    assert revised["status"] == "reviewed_scope" and revised["snapshot"]["version"] == 2
