"""T20 actual document formats, canonical PostgreSQL and HTTP contracts."""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pypdf import PdfReader
from test_bling_canonical import mapping as _mapping_fixture
from test_t14_authorized_issuance import economy_database as _economy_database_fixture
from test_t15_historical_audit import MONTH, _setup
from test_t16_unused_credits import BUYER
from test_t18_credit_ledger import _federal_seed, _reviewed, _seed
from test_t19_recovery_lifecycle import NOW, _fixture, _run, _session

from kordena_fiscal.application import accounting_dossier as dossier
from kordena_fiscal.application import credit_ledger as ledger
from kordena_fiscal.application.accounting_dossier import (
    AccountingDossierService,
    DossierAuthorityError,
    DossierStepUpRequired,
)
from kordena_fiscal.application.unused_credits import verify_credit_unit
from kordena_fiscal.archive.accounting_dossier import (
    DISCLAIMER,
    digest,
    json_bytes,
    render_package,
    verify_package,
)
from kordena_fiscal.cognitive import api as cognitive_api
from kordena_fiscal.cognitive.api import create_cognitive_router
from kordena_fiscal.cognitive.historical_audit_api import historical_issuer_context
from kordena_fiscal.domain import FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.runtime import api as runtime_api
from kordena_fiscal.runtime.config import RuntimeSettings
from kordena_fiscal.security.human_identity import (
    CsrfValidationError,
    HumanAccount,
    HumanAuthenticationError,
    HumanAuthorizationError,
    HumanIdentityService,
    PortalRole,
    ScryptPasswordHasher,
)
from kordena_fiscal.security.human_mfa import HumanMfaService
from kordena_fiscal.security.totp import totp_at
from kordena_fiscal.tax.credit_ledger import Command, transition
from kordena_fiscal.tax.recovery_lifecycle import managed_request_id
from kordena_fiscal.web.human_auth import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE

# Register the imported pytest fixtures under their canonical names without
# shadowing an import binding when the test requests the fixture by name.
mapping = _mapping_fixture
economy_database = _economy_database_fixture


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
    assert cell.number_format == "@" and cell.quotePrefix
    assert all(
        row[1].number_format == "0" for row in list(workbook["Memória T17"].rows)[1:]
        if isinstance(row[1].value, int)
    )
    assert workbook["Ledger T18"]["A2"].value == "Estado"
    assert workbook["Casos T19"]["A2"].value == "Estado"
    assert [cell.value for cell in workbook["Evidências"][1]] == ["Caminho", "SHA-256", "Bytes"]
    with ZipFile(io.BytesIO(raw)) as archive:
        assert archive.read("xml/original.xml") == xml
        pdf = PdfReader(io.BytesIO(archive.read("dossie.pdf")))
        text = " ".join(" ".join(p.extract_text().split()) for p in pdf.pages)
        assert DISCLAIMER in text
        assert "Principal (centavos)" in text and "Referência legal" in text
        with ZipFile(io.BytesIO(archive.read("memoria.xlsx"))) as xlsx:
            styles = xlsx.read("xl/styles.xml")
            assert b'FF163B64' in styles and b'FFFFFFFF' in styles


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
    scope = _setup(db, mapping, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    now = datetime.now(UTC)
    finding, _ = _seed(db, scope, context, as_of=now.astimezone(dossier.LOCAL).date())
    recovery, token, _ = _session(db, scope)
    account = recovery.identity.authenticate_session(session_token=token, now=NOW).account
    issued = recovery.identity.issue_session(account, now=now)
    service = AccountingDossierService(db, recovery.identity, recovery.step_up, clock=lambda: now)
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
            "finding_id": finding, "source_version": source["version"],
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


@pytest.mark.parametrize(
    "value", ["=1+1", "+1+1", "-1+1", "@SUM(A1:A2)", "\t=1+1", "\r=1+1", "\x00"],
)
def test_workbook_untrusted_text_stays_text(value):
    payload = _payload()
    payload["t16"]["citation"]["reference"] = value
    payload["t17"]["wide_cents"] = 10**12
    raw = render_package(payload, {"xml/original.xml": b"<original/>"})
    memory, workbook = _inspect(raw)
    assert memory == payload
    cell = workbook["Memória T16"]["B2"]
    assert cell.data_type == "s" and cell.quotePrefix and cell.number_format == "@"
    expected = {"\t=1+1": r"\u0009=1+1", "\r=1+1": r"\u000d=1+1", "\x00": r"\u0000"}
    assert cell.value == expected.get(value, value)
    values = {r[0].value: r[1] for r in list(workbook["Memória T17"].rows)[1:]}
    assert values["wide_cents"].value == 10**12
    assert values["wide_cents"].number_format == "0"
    assert values["large_cents"].number_format == "@"
    assert workbook["Memória T16"].row_dimensions[2].height >= 22


@pytest.mark.parametrize(
    "future", [NOW + timedelta(days=1), NOW.replace(month=12, day=1),
               NOW.replace(year=2031, month=1, day=21)],
)
def test_postgres_source_cutoff_cannot_be_replayed(
    economy_database, mapping, future, monkeypatch,
):
    db = economy_database
    scope, cmd, _ = _fixture(db, mapping)
    recovery, token, csrf = _session(db, scope)
    service = _dossier(db, recovery)
    source = service.candidates(token, csrf, scope.unit_id, MONTH)["source"]
    account = recovery.identity.authenticate_session(session_token=token, now=NOW).account
    renewed = recovery.identity.issue_session(account, now=future)
    service.clock = lambda: future
    for operation in (
        lambda: service.candidates(renewed.session_token, renewed.csrf_token, scope.unit_id, MONTH),
        lambda: _export(service, renewed.session_token, renewed.csrf_token, scope,
                        cmd.finding_id, source),
    ):
        with pytest.raises(FiscalValidationError, match="cutoff"):
            operation()

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return future.astimezone(tz) if tz is not None else future.replace(tzinfo=None)

    monkeypatch.setattr(cognitive_api, "datetime", FrozenDateTime)
    app = FastAPI()
    app.include_router(create_cognitive_router(
        recovery.identity, None, None, dossier_service=service,
    ))
    body = {
        "unit_id": scope.unit_id, "environment": "homologation", "competence": MONTH.isoformat(),
    }
    selection = body | {
        "finding_id": cmd.finding_id, "source_version": source["version"],
        "source_digest": source["digest"],
    }
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, renewed.session_token)
        client.cookies.set(CSRF_COOKIE, renewed.csrf_token)
        headers = {CSRF_HEADER: renewed.csrf_token}
        for action, request in (("candidates", body), ("export", selection)):
            response = client.post(
                f"/v1/portal/cognitive/economy/accounting-dossier/{action}",
                json=request, headers=headers,
            )
            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "DOSSIER_EVIDENCE_INVALID"
    with db.economy(scope) as store:
        assert store.records("fm_economy_dossiers") == ()
        assert not any(
            row["record_id"].startswith("t20-dossier-")
            for row in store.records("fm_economy_opportunities")
        )


def test_postgres_cofins_concurrent_replay_and_four_axis_rls(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    command, = _federal_seed(db, scope, MONTH, [("cofins", 334)])
    recovery, token, csrf = _session(db, scope)
    service = _dossier(db, recovery)
    source = service.candidates(token, csrf, scope.unit_id, MONTH)["source"]
    barrier = Barrier(2)

    def run(_):
        barrier.wait(timeout=20)
        return _export(service, token, csrf, scope, command.finding_id, source)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(run, range(2)))
    assert first == second
    memory, _ = _inspect(first)
    assert memory["t17"]["tax"] == "cofins"
    key = memory["identification"]["dossier_id"]
    with db.economy(scope) as store:
        assert store.record("fm_economy_dossiers", key)["version"] == 1
        assert store.record("fm_economy_dossiers", key, 2) is None
    identities = {
        "fm_economy_dossiers": key,
        "fm_economy_opportunities": key + "-opportunity",
        "fm_economy_snapshots": key + "-archive",
    }
    for other in (
        replace(scope, tenant_id="other-tenant"), replace(scope, unit_id="other-unit"),
        replace(scope, host_namespace="other-host"),
        replace(scope, environment=FiscalEnvironment.PRODUCTION),
    ):
        with db.economy(other) as store:
            for table, record in identities.items():
                assert store.record(table, record) is None
                # Deliberately omit scope WHERE clauses to prove database RLS itself.
                assert store._conn.execute(
                    f"SELECT count(*) FROM {table} WHERE record_id=%s", (record,),
                ).fetchone()[0] == 0
    for other in (
        replace(scope, tenant_id="other-tenant"), replace(scope, unit_id="other-unit"),
    ):
        foreign, foreign_token, foreign_csrf = _session(db, other)
        with pytest.raises((FiscalValidationError, HumanAuthorizationError)):
            _dossier(db, foreign).candidates(foreign_token, foreign_csrf, scope.unit_id, MONTH)
        with pytest.raises((FiscalValidationError, HumanAuthorizationError)):
            _export(_dossier(db, foreign), foreign_token, foreign_csrf, scope,
                    command.finding_id, source)


@pytest.mark.parametrize("suffix", ["-archive", "-archive-0"])
def test_postgres_corrupt_archive_replay_fails_closed(
    economy_database, mapping, monkeypatch, suffix,
):
    db = economy_database
    scope, cmd, _ = _fixture(db, mapping)
    recovery, token, csrf = _session(db, scope)
    service = _dossier(db, recovery)
    source = service.candidates(token, csrf, scope.unit_id, MONTH)["source"]
    raw = _export(service, token, csrf, scope, cmd.finding_id, source)
    memory, _ = _inspect(raw)
    key = memory["identification"]["dossier_id"]
    original = EconomyStore.record

    def corrupt(store, table, record_id, version=None):
        row = original(store, table, record_id, version)
        if row is not None and record_id == key + suffix:
            field = "sha256" if suffix == "-archive" else "data_b64"
            return row | {"content": row["content"] | {field: "AAAA"}}
        return row

    # Fault injection on the read boundary; append-only tables are never weakened.
    with monkeypatch.context() as patch:
        patch.setattr(EconomyStore, "record", corrupt)
        with pytest.raises(FiscalValidationError, match="archive"):
            _export(service, token, csrf, scope, cmd.finding_id, source)
    assert _export(service, token, csrf, scope, cmd.finding_id, source) == raw


@pytest.mark.parametrize("malformed", [False, True], ids=["canonical-orphan", "legacy-malformed"])
def test_postgres_orphan_managed_ledger_blocks_dossier(economy_database, mapping, malformed):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    _, context = historical_issuer_context(db, scope, MONTH)
    proof = verify_credit_unit(db, scope, BUYER)
    request_id = managed_request_id(terms.case_id, 1, 1)
    if malformed:
        request_id = request_id.replace("t19-", "T19-", 1)
    forged = Command.model_validate(cmd.model_dump() | {
        "expected_version": 1, "request_id": request_id, "movement": "reserved",
    })
    reviewed = _reviewed(scope, forged)
    day = NOW.astimezone(dossier.LOCAL).date()
    with db.economy(scope) as store:
        if malformed:
            # The application writer must reject malformed identifiers.
            key = ledger.journal_id(BUYER, cmd.finding_id)
            state, rows = ledger._replay(store, BUYER, MONTH, key)
            with pytest.raises(FiscalValidationError, match="invalid T19 managed movement identity"):
                ledger._post_movement(
                    store, BUYER, reviewed, context=context,
                    as_of=day, unit=proof, managed=True,
                )
            assert ledger._replay(store, BUYER, MONTH, key)[1] == rows
            # Simulate pre-existing corruption directly in the test store.
            # Keep the source, evidence, postings, balances and digest valid.
            content = dict(rows[-1]["content"])
            content.update({
                "event_version": 2, "previous_digest": rows[-1]["digest"],
                "as_of": day.isoformat(), "reviewed": reviewed.model_dump(),
                "postings": transition(state, forged), "balances": state.projection(),
            })
            store.append_snapshot(record_id=key, version=2, competence=MONTH,
                                  issuer=BUYER, content=content)
        else:
            # Canonical identifier but no corresponding T19 case event.
            ledger._post_movement(
                store, BUYER, reviewed, context=context,
                as_of=day, unit=proof, managed=True,
            )
    recovery, token, csrf = _session(db, scope)
    service = _dossier(db, recovery)
    source = service.candidates(token, csrf, scope.unit_id, MONTH)["source"]
    expected_error = (
        "invalid T19 managed movement identity" if malformed else "orphan recovery case ledger"
    )
    with pytest.raises(FiscalValidationError, match=expected_error):
        _export(service, token, csrf, scope, cmd.finding_id, source)
    with db.economy(scope) as store:
        assert store.records("fm_economy_dossiers") == ()
        for table in ("fm_economy_opportunities", "fm_economy_snapshots"):
            assert not any(
                row["record_id"].startswith("t20-dossier-")
                for row in store.records(table, limit=500)
            )


def test_postgres_revocation_during_render_rolls_back(economy_database, mapping, monkeypatch):
    db = economy_database
    scope, cmd, _ = _fixture(db, mapping)
    recovery, token, csrf = _session(db, scope)
    service = _dossier(db, recovery)
    source = service.candidates(token, csrf, scope.unit_id, MONTH)["source"]
    human = recovery.identity.authenticate_session(session_token=token, now=NOW)
    original = dossier.render_package

    def revoke(*args, **kwargs):
        raw = original(*args, **kwargs)
        recovery.identity.logout(human)
        return raw

    monkeypatch.setattr(dossier, "render_package", revoke)
    with pytest.raises(HumanAuthenticationError):
        _export(service, token, csrf, scope, cmd.finding_id, source)
    with db.economy(scope) as store:
        assert store.records("fm_economy_dossiers") == ()
        assert not any(
            row["record_id"].startswith("t20-dossier-")
            for row in store.records("fm_economy_snapshots", limit=500)
        )


def _live_identity(db, scope, monkeypatch):
    db.initialize(enable_mfa=True)
    monkeypatch.setenv("NFCORE_HUMAN_MFA", "enabled")
    monkeypatch.setenv("NFCORE_HUMAN_MFA_KEY_BASE64", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("NFCORE_T20_DOSSIER_ENABLED", "true")
    monkeypatch.setenv("NFCORE_COGNITIVE_ENABLED", "true")
    now = datetime.now(UTC)
    hasher = ScryptPasswordHasher()
    account = HumanAccount(
        "t20-test-actor", "t20@example.test", hasher.hash("Synthetic-T20-Password-123"),
        scope.tenant_id, PortalRole.ACCOUNTANT, frozenset({scope.unit_id}),
    )
    db.human_accounts().save(account)
    identity = HumanIdentityService(
        accounts=db.human_accounts(), sessions=db.web_sessions(), password_hasher=hasher,
    )
    issued = identity.issue_session(account, now=now)
    human = identity.authenticate_session(session_token=issued.session_token, now=now)
    mfa = HumanMfaService.from_environ(db.human_mfa)
    assert mfa is not None
    encoded = mfa.start_enrollment(account, now).secret_base32
    secret = base64.b32decode(encoded + "=" * (-len(encoded) % 8))
    codes = mfa.confirm_enrollment(account, totp_at(secret, now), now)
    _, context = historical_issuer_context(db, scope, MONTH)
    finding, source_digest = _seed(db, scope, context, as_of=now.astimezone(dossier.LOCAL).date())
    return issued, human, mfa, codes, finding, source_digest


def test_postgres_cli_subprocess_real_mfa_and_destination(
    economy_database, mapping, monkeypatch, tmp_path,
):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    issued, human, mfa, codes, finding, source_digest = _live_identity(db, scope, monkeypatch)
    cli = Path(__file__).parents[1] / "scripts/nfcore_accounting_dossier.py"
    args = [sys.executable, str(cli), "--unit", scope.unit_id, "--competence", MONTH.isoformat()]
    env = os.environ | {
        "NFCORE_ENVIRONMENT": "test", "DATABASE_URL": db._dsn,
        "NFCORE_T20_SESSION_TOKEN": issued.session_token,
        "NFCORE_T20_CSRF_TOKEN": issued.csrf_token,
    }
    output = tmp_path / "dossier.zip"
    selection = ["--finding", finding, "--source-version", "1", "--source-digest", source_digest]

    def invoke(arguments, **overrides):
        result = subprocess.run(
            [*args, *arguments], env=env | overrides, capture_output=True,
            text=True, check=False, timeout=90,
        )
        assert issued.session_token not in result.stderr and issued.csrf_token not in result.stderr
        return result

    for overrides in (
        {"NFCORE_ENVIRONMENT": "production"}, {"NFCORE_T20_DOSSIER_ENABLED": "false"},
        {"NFCORE_ECONOMY_ENABLED": "false"}, {"NFCORE_HUMAN_MFA": "disabled"},
        {"NFCORE_T20_CSRF_TOKEN": "invalid"}, {},
    ):
        result = invoke(["--candidates"], **overrides)
        assert result.returncode == 2 and not result.stdout
    mfa.step_up(human.account, human.session_id, codes[0], datetime.now(UTC))
    result = invoke(["--candidates"])
    result.check_returncode()
    assert json.loads(result.stdout)["source"]["digest"] == source_digest
    dangling = tmp_path / "dangling.zip"
    dangling.symlink_to(tmp_path / "missing.zip")
    for target in (dangling, tmp_path / "missing" / "dossier.zip"):
        result = invoke(["--output", str(target), *selection])
        assert result.returncode == 2 and not result.stdout
    with db.economy(scope) as store:
        assert store.records("fm_economy_dossiers") == ()
    invoke(["--output", str(output), *selection]).check_returncode()
    original = output.read_bytes()
    _inspect(original)
    assert output.stat().st_mode & 0o777 == 0o600
    assert invoke(["--output", str(output), *selection]).returncode == 2
    assert output.read_bytes() == original and dangling.is_symlink()


@pytest.mark.parametrize(
    ("environment", "disabled", "expected"),
    [
        ("test", None, 200),
        ("test", "NFCORE_T20_DOSSIER_ENABLED", 503),
        ("test", "NFCORE_COGNITIVE_ENABLED", 404),
        ("test", "NFCORE_ECONOMY_ENABLED", 503),
        ("test", "NFCORE_HUMAN_MFA", 503),
        ("staging", None, 200),
        ("production", None, 503),
    ],
)
def test_postgres_runtime_availability_and_real_http_mfa(
    economy_database, mapping, monkeypatch, environment, disabled, expected,
):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    issued, human, _, codes, finding, source_digest = _live_identity(db, scope, monkeypatch)
    if disabled:
        monkeypatch.setenv(disabled, "disabled" if disabled == "NFCORE_HUMAN_MFA" else "false")
    if environment in {"staging", "production"}:
        # The existing release schema gate hard-codes public.*; this fixture
        # deliberately uses a disposable non-public schema. Adapt ONLY that
        # unrelated startup probe in this test, not the T20 composition gate.
        expected_migrations = db.applied_migrations()

        def isolated_schema(database, **_):
            assert database._dsn == db._dsn
            assert database.applied_migrations() == expected_migrations
            with database.connection() as connection:
                assert connection.execute(
                    "SELECT to_regclass('fm_economy_dossiers'), to_regclass('fm_human_accounts')"
                ).fetchone() == ("fm_economy_dossiers", "fm_human_accounts")
            return expected_migrations

        monkeypatch.setattr(PostgresFiscalDatabase, "require_current_schema", isolated_schema)
    profile = {
        "NFCORE_ENVIRONMENT": environment, "NFCORE_PERSISTENCE_BACKEND": "postgres",
        "DATABASE_URL": db._dsn,
    }
    if environment == "production":
        # Satisfy the unchanged production edge policy with a reserved test DNS
        # name. TestClient is in-process; no DNS lookup or deployment occurs.
        profile.update({
            "NFCORE_PUBLIC_HOSTNAME": "nfcore-t20.example.test",
            "NFCORE_REQUIRE_HTTPS": "true",
            "NFCORE_SECRET_BACKEND": "external",
        })
    settings = RuntimeSettings.from_mapping(profile)
    app = runtime_api.create_runtime_app(settings)
    assert app.state.nfcore_runtime_composition is not None
    prefix = "/v1/portal/cognitive/economy/accounting-dossier"
    body = {
        "unit_id": scope.unit_id, "environment": "homologation", "competence": MONTH.isoformat(),
    }
    selection = body | {"finding_id": finding, "source_version": 1, "source_digest": source_digest}
    base_url = f"https://{settings.public_hostname or 'testserver'}"
    with TestClient(app, base_url=base_url) as client:
        client.cookies.set(SESSION_COOKIE, issued.session_token)
        client.cookies.set(CSRF_COOKIE, issued.csrf_token)
        headers = {CSRF_HEADER: issued.csrf_token}
        bootstrap = client.get("/v1/portal/bootstrap")
        assert bootstrap.status_code == 200, bootstrap.text
        assert bootstrap.json()["projection"]["accounting_dossier_available"] is (expected == 200)
        response = client.post(prefix + "/candidates", json=body, headers=headers)
        if expected != 200:
            blocked_export = client.post(prefix + "/export", json=selection, headers=headers)
            for blocked in (response, blocked_export):
                assert blocked.status_code == expected, blocked.text
                if expected == 503:
                    assert blocked.json()["detail"]["code"] == "DOSSIER_UNAVAILABLE"
            if environment == "production":
                # Even a real recent MFA cannot activate the sandbox-only service.
                assert client.post(
                    "/v1/auth/mfa/step-up", json={"code": codes[0]}, headers=headers,
                ).status_code == 200
                for action, payload in (("candidates", body), ("export", selection)):
                    blocked = client.post(prefix + "/" + action, json=payload, headers=headers)
                    assert blocked.status_code == 503
                    assert blocked.json()["detail"]["code"] == "DOSSIER_UNAVAILABLE"
                with db.economy(scope) as store:
                    assert store.records("fm_economy_dossiers") == ()
            return
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "STEP_UP_REQUIRED"
        response = client.post(prefix + "/export", json=selection, headers=headers)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "STEP_UP_REQUIRED"
        response = client.post("/v1/auth/mfa/step-up", json={"code": codes[0]}, headers=headers)
        assert response.status_code == 200, response.text
        assert client.post(prefix + "/candidates", json=body, headers=headers).status_code == 200
        composition = app.state.nfcore_runtime_composition
        original = dossier.render_package

        def revoke(*args, **kwargs):
            raw = original(*args, **kwargs)
            composition.human_identity.logout(human)
            return raw

        with monkeypatch.context() as patch:
            patch.setattr(dossier, "render_package", revoke)
            response = client.post(prefix + "/export", json=selection, headers=headers)
            assert response.status_code == 401, response.text
        with db.economy(scope) as store:
            assert store.records("fm_economy_dossiers") == ()
        renewed = composition.human_identity.issue_session(human.account, now=datetime.now(UTC))
        client.cookies.set(SESSION_COOKIE, renewed.session_token)
        client.cookies.set(CSRF_COOKIE, renewed.csrf_token)
        headers = {CSRF_HEADER: renewed.csrf_token}
        assert client.post(
            "/v1/auth/mfa/step-up", json={"code": codes[1]}, headers=headers,
        ).status_code == 200
        response = client.post(prefix + "/export", json=selection, headers=headers)
        assert response.status_code == 200, response.text
        _inspect(response.content)
