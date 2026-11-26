"""T20 actual document formats, canonical PostgreSQL and HTTP contracts."""

from __future__ import annotations

import base64
import io
import json
from datetime import UTC, datetime
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from test_bling_canonical import mapping  # noqa: F401
from test_t14_authorized_issuance import economy_database  # noqa: F401
from test_t15_historical_audit import MONTH, _setup
from test_t16_unused_credits import BUYER
from test_t18_credit_ledger import _seed
from test_t19_recovery_lifecycle import NOW, _fixture, _run, _session

from kordena_fiscal.application.accounting_dossier import (
    AccountingDossierService,
    DossierAuthorityError,
    DossierStepUpRequired,
)
from kordena_fiscal.archive.accounting_dossier import (
    digest,
    json_bytes,
    render_package,
    verify_package,
)
from kordena_fiscal.cognitive.api import create_cognitive_router
from kordena_fiscal.cognitive.historical_audit_api import historical_issuer_context
from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.security.human_identity import CsrfValidationError, PortalRole
from kordena_fiscal.web.human_auth import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE


def _payload():
    basis = {"finding_id": "a" * 64}
    return {
        "identification": {"basis_digest": digest(json_bytes(basis)), "issuer": "synthetic"},
        "basis": basis, "simulation_only": True, "credit_recognized": False,
        "t16": {"citation": {"reference": "=1+1"}},
        "t17": {
            "principal_cents": 334, "adjustment_cents": 37, "estimated_cents": 371,
            "large_cents": 9223372036854775807,
        },
        "legal": {"reference": "Artigo revisado"}, "ledger_summary": None,
        "cases": [], "opinion": {"status": "PENDENTE DE REVISÃO E ASSINATURA HUMANA"},
    }


def _inspect(raw):
    with ZipFile(io.BytesIO(raw)) as archive:
        memory = json.loads(archive.read("memoria.json"))
        manifest = json.loads(archive.read("manifesto.json"))
        assert memory["credit_recognized"] is False
        assert memory["simulation_only"] is True
        assert manifest["basis_digest"] == memory["identification"]["basis_digest"]
        verify_package(raw, manifest["basis_digest"])
        for entry in manifest["files"]:
            member = archive.read(entry["path"])
            assert digest(member) == entry["sha256"] and len(member) == entry["bytes"]
        assert archive.read("dossie.pdf").startswith(b"%PDF-")
        assert archive.read("dossie.pdf").rstrip().endswith(b"%%EOF")
        workbook = load_workbook(io.BytesIO(archive.read("memoria.xlsx")))
        assert workbook.sheetnames == [
            "Resumo", "Memória T16", "Memória T17", "Base legal",
            "Ledger T18", "Casos T19", "Evidências",
        ]
        return memory, workbook


def test_render_real_pdf_excel_xml_and_exact_integer_cells():
    payload = _payload()
    xml = b'<invoice source="synthetic"/>'
    raw = render_package(payload, {"xml/original.xml": xml})
    memory, workbook = _inspect(raw)
    assert memory == payload
    values = {r[0].value: r[1].value for r in list(workbook["Memória T17"].rows)[1:]}
    assert values["principal_cents"] == 334
    assert values["estimated_cents"] == 371
    assert values["large_cents"] == "9223372036854775807"
    cell = workbook["Memória T16"]["B2"]
    assert cell.data_type == "s" and cell.value == "=1+1"
    with ZipFile(io.BytesIO(raw)) as archive:
        assert archive.read("xml/original.xml") == xml


@pytest.mark.parametrize("name", ["../evil.xml", "/xml/evil.xml", "xml/../evil.xml"])
def test_reject_unsafe_paths(name):
    with pytest.raises(FiscalValidationError):
        render_package(_payload(), {name: b"<x/>", "xml/good.xml": b"<x/>"})


def test_archive_tampering_and_missing_xml_fail_closed():
    payload = _payload()
    with pytest.raises(FiscalValidationError):
        render_package(payload, {"provas/source.bin": b"source"})
    raw = render_package(payload, {"xml/original.xml": b"<original/>"})
    output = io.BytesIO()
    with ZipFile(io.BytesIO(raw)) as source, ZipFile(output, "w") as destination:
        for name in source.namelist():
            member = b"<changed/>" if name == "xml/original.xml" else source.read(name)
            destination.writestr(name, member)
    with pytest.raises(FiscalValidationError, match="integrity"):
        verify_package(output.getvalue(), payload["identification"]["basis_digest"])


def _dossier(db, recovery):
    return AccountingDossierService(db, recovery.identity, recovery.step_up, clock=lambda: NOW)


def _export(service, token, csrf, scope, finding_id, source):
    return service.export(
        token, csrf, scope.unit_id, MONTH, finding_id, source["version"], source["digest"],
    )


def test_postgres_federal_full_evidence_and_idempotent_versions(economy_database, mapping):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    recovery, token, csrf = _session(db, scope)
    service = _dossier(db, recovery)
    _run(recovery, token, csrf, scope, cmd, terms, 0, "request")
    before = recovery.read(token, csrf, scope.unit_id, MONTH)
    candidates = service.candidates(token, csrf, scope.unit_id, MONTH)
    source = candidates["source"]
    assert source["digest"] == cmd.recovery_digest
    assert any(item["finding_id"] == cmd.finding_id for item in candidates["candidates"])
    raw = _export(service, token, csrf, scope, cmd.finding_id, source)
    memory, _ = _inspect(raw)
    assert memory["t17"]["principal_cents"] == cmd.amount.principal_cents
    assert memory["t17"]["adjustment_cents"] == cmd.amount.selic_cents
    assert memory["cases"][0]["status"] == "requested"
    with ZipFile(io.BytesIO(raw)) as archive:
        t16 = json.loads(archive.read("fontes/t16.json"))
        t15 = json.loads(archive.read("fontes/t15.json"))
        for purchase in t16["purchases"]:
            xml = purchase["xml"]
            assert archive.read(f"xml/t16-{xml['sha256']}.xml") == base64.b64decode(
                xml["data_b64"], validate=True,
            )
        for doc in t15["documents"]:
            assert archive.read(f"xml/t15-{doc['xml_sha256']}.xml") == base64.b64decode(
                doc["xml_b64"], validate=True,
            )
        assert json.loads(archive.read("fontes/ledger-t18.json"))["events"]
        assert json.loads(archive.read("fontes/casos-t19.json"))[0]["events"]
    key = memory["identification"]["dossier_id"]
    with db.economy(scope) as store:
        row = store.record("fm_economy_dossiers", key)
        assert row["digest"] == digest(raw) and row["version"] == 1
    assert _export(service, token, csrf, scope, cmd.finding_id, source) == raw
    assert recovery.read(token, csrf, scope.unit_id, MONTH) == before
    _run(recovery, token, csrf, scope, cmd, terms, 1, "transmit")
    changed = _export(service, token, csrf, scope, cmd.finding_id, source)
    revised, _ = _inspect(changed)
    assert revised["identification"]["dossier_id"] == key
    assert revised["identification"]["dossier_version"] == 2
    assert revised["cases"][0]["status"] == "transmitted"
    with db.economy(scope) as store:
        assert store.record("fm_economy_dossiers", key, 1)["digest"] == digest(raw)
        assert store.record("fm_economy_dossiers", key, 2)["digest"] == digest(changed)


def test_postgres_icms_without_ledger_and_stale_selection(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    finding, expected = _seed(db, scope, context)
    recovery, token, csrf = _session(db, scope)
    service = _dossier(db, recovery)
    source = service.candidates(token, csrf, scope.unit_id, MONTH)["source"]
    assert source["digest"] == expected
    with pytest.raises(FiscalValidationError, match="selection changed"):
        _export(service, token, csrf, scope, finding, source | {"digest": "f" * 64})
    memory, _ = _inspect(_export(service, token, csrf, scope, finding, source))
    assert memory["ledger_summary"] is None
    assert memory["cases"] == []
    assert memory["t17"]["tax"] == "icms"


def test_postgres_authority_and_atomic_rollback(economy_database, mapping, monkeypatch):
    db = economy_database
    scope, cmd, _ = _fixture(db, mapping)
    recovery, token, csrf = _session(db, scope)
    service = _dossier(db, recovery)
    with pytest.raises(CsrfValidationError):
        service.candidates(token, "wrong", scope.unit_id, MONTH)
    auditor, read_token, read_csrf = _session(db, scope, role=PortalRole.AUDITOR)
    with pytest.raises(DossierAuthorityError):
        _dossier(db, auditor).candidates(read_token, read_csrf, scope.unit_id, MONTH)
    weak, weak_token, weak_csrf = _session(db, scope, step_up=False)
    with pytest.raises(DossierStepUpRequired):
        _dossier(db, weak).candidates(weak_token, weak_csrf, scope.unit_id, MONTH)
    source = service.candidates(token, csrf, scope.unit_id, MONTH)["source"]

    def fail(*args, **kwargs):
        raise FiscalValidationError("synthetic final-write failure")

    with monkeypatch.context() as patch:
        patch.setattr(EconomyStore, "append_dossier", fail)
        with pytest.raises(FiscalValidationError, match="final-write"):
            _export(service, token, csrf, scope, cmd.finding_id, source)
    raw = _export(service, token, csrf, scope, cmd.finding_id, source)
    memory, _ = _inspect(raw)
    assert memory["identification"]["dossier_version"] == 1


def test_postgres_http_binary_route_and_denials(economy_database, mapping):
    db = economy_database
    scope, cmd, _ = _fixture(db, mapping)
    recovery, token, _ = _session(db, scope)
    account = recovery.identity.authenticate_session(session_token=token, now=NOW).account
    issued = recovery.identity.issue_session(account, now=datetime.now(UTC))
    service = AccountingDossierService(db, recovery.identity, recovery.step_up)
    app = FastAPI()
    app.include_router(create_cognitive_router(
        recovery.identity, None, None, dossier_service=service,
    ))
    prefix = "/v1/portal/cognitive/economy/accounting-dossier"
    body = {
        "unit_id": scope.unit_id, "environment": "homologation", "competence": MONTH.isoformat(),
    }
    with TestClient(app) as client:
        assert client.post(prefix + "/candidates", json=body).status_code == 401
        client.cookies.set(SESSION_COOKIE, issued.session_token)
        client.cookies.set(CSRF_COOKIE, issued.csrf_token)
        headers = {CSRF_HEADER: issued.csrf_token}
        assert client.post(prefix + "/candidates", json=body).status_code == 403
        assert client.post(
            prefix + "/candidates", json=body | {"environment": "production"}, headers=headers,
        ).status_code == 403
        response = client.post(prefix + "/candidates", json=body, headers=headers)
        assert response.status_code == 200, response.text
        source = response.json()["source"]
        selection = body | {
            "finding_id": cmd.finding_id, "source_version": source["version"],
            "source_digest": source["digest"],
        }
        assert client.post(
            prefix + "/export", json=selection | {"source_digest": "a" * 64}, headers=headers,
        ).status_code == 409
        response = client.post(prefix + "/export", json=selection, headers=headers)
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert response.headers["cache-control"] == "no-store"
        _inspect(response.content)
