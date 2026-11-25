# ruff: noqa: F811 -- imported integration fixtures requested by name.
"""Synthetic supplier invoices and reviewed bookkeeping, no customer data."""

import base64
import copy
import hashlib
import json
from dataclasses import replace
from datetime import date

import pytest
from test_bling_canonical import mapping  # noqa: F401
from test_t14_authorized_issuance import economy_database  # noqa: F401
from test_t15_historical_audit import MONTH, TODAY, _context, _setup, _xml, fixture

from kordena_fiscal.application.unused_credits import import_credits, verify_credit_unit
from kordena_fiscal.cognitive.historical_audit_api import historical_issuer_context
from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.tax.unused_credits import Batch, detect

BUYER = Cnpj("11222333000181")


def evidence(raw):
    return {"data_b64": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest()}


def batch(tax="icms", purpose="insumo", period=MONTH, as_of=TODAY):
    original = fixture()
    raw = (
        _xml(period, 1)
        .replace(b"</emit>", f"</emit><dest><CNPJ>{BUYER.value}</CNPJ></dest>".encode())
        .replace(b"</prod>", b"<vProd>100.00</vProd></prod>")
        .replace(b"</imposto>", b"<IPI><IPITrib><vIPI>18.00</vIPI></IPITrib></IPI></imposto>")
    )
    legal = {k: original["artifacts"][4][k] for k in ("data_b64", "sha256")}
    citation = original["citations"][0]
    if tax.endswith("_presumido"):
        citation["valid_until"] = "2030-01-01"
    method = {"icms": "highlighted_icms", "ipi": "highlighted_ipi"}.get(tax, "reviewed_base")
    return {
        "competence": period.isoformat(),
        "rules": [
            {
                "tax": tax,
                "purpose": purpose,
                "regime": "lucro_real",
                "uf": "SP",
                "cnae": _context().cnae,
                "ncm": "30049099",
                "supplier_cfop": "5102",
                "method": method,
                "presumed_credit_code": "1" if tax.endswith("_presumido") else None,
                "required_facts": {"synthetic-condition": True},
                "numerator": 1,
                "denominator": 3,
                "citation": citation,
                "legal_source": legal,
            }
        ],
        "purchases": [
            {
                "xml": evidence(raw),
                "status": "active",
                "status_evidence": evidence(b"fixture active"),
                "uses": [
                    {
                        "item": 1,
                        "tax": tax,
                        "purpose": purpose,
                        "observed_facts": {
                            "synthetic-condition": True,
                            "rural_non_contributor": True,
                            "regular_regime_buyer": True,
                            "payment_documented": True,
                            "appropriation_event_history_reviewed": True,
                            "period_rate_officially_reviewed": True,
                        },
                        "basis_cents": 1001,
                        "eligibility_evidence": evidence(b"fixture allocation"),
                    }
                ],
            }
        ],
        "books": {
            "recipient": BUYER.value,
            "competence": period.isoformat(),
            "checked_through": as_of.isoformat(),
            "complete_taxes": [tax],
            "all_units_and_later_adjustments_reviewed": True,
            "entries": [],
            "source": evidence(b"fixture books reviewed"),
        },
    }


def bind_book(data):
    books = data["books"]
    if books is not None:
        extract = {k: v for k, v in books.items() if k != "source"}
        books["source"] = evidence(json.dumps(extract, sort_keys=True).encode())


def run(data, as_of=TODAY):
    bind_book(data)
    return detect(Batch.model_validate(data), BUYER, _context(), as_of)


@pytest.mark.parametrize("tax", ["icms", "ipi", "pis", "cofins", "ibs_presumido", "cbs_presumido"])
@pytest.mark.parametrize("purpose", ["insumo", "energia", "frete", "ativo_imobilizado"])
def test_deterministic_reviewed_rule_and_prior_booking(tax, purpose):
    as_of = date(2027, 2, 1) if tax.endswith("_presumido") else TODAY
    period = date(2027, 1, 1) if tax.endswith("_presumido") else MONTH
    data = batch(tax, purpose, period, as_of)
    report = run(data, as_of)
    row = report["findings"][0]
    assert row["status"] == "unused_candidate" and row["candidate_cents"] == 334
    assert report["partial_totals_cents"] == {tax: 334} and not report["credit_recognized"]
    data["books"]["entries"].append(
        {"access_key": row["access_key"], "item": 1, "tax": tax, "booked_cents": 334}
    )
    assert run(data, as_of)["findings"][0]["status"] == "fully_accounted"
    data["books"]["entries"][0]["booked_cents"] = 34
    assert run(data, as_of)["partial_totals_cents"] == {tax: 300}


@pytest.mark.parametrize(
    "change",
    [
        "missing_books",
        "stale",
        "partial",
        "wrong_tax",
        "expired",
        "wrong_regime",
        "wrong_ncm",
        "over_base",
        "unresolved",
        "cancelled",
    ],
)
def test_no_monetary_result_without_current_evidence(change):
    data = batch()
    if change == "missing_books":
        data["books"] = None
    elif change == "stale":
        data["books"]["checked_through"] = date(2026, 11, 23).isoformat()
    elif change == "partial":
        data["books"]["all_units_and_later_adjustments_reviewed"] = False
    elif change == "wrong_tax":
        data["books"]["complete_taxes"] = ["ipi"]
    elif change == "expired":
        data["rules"][0]["citation"]["valid_until"] = "2025-12-01"
    elif change == "wrong_regime":
        data["rules"][0]["regime"] = "lucro_presumido"
    elif change == "wrong_ncm":
        data["rules"][0]["ncm"] = "00000000"
    elif change == "over_base":
        data["purchases"][0]["uses"][0]["basis_cents"] = 1801
    else:
        data["purchases"][0]["status"] = change
    result = run(data)
    assert result["findings"][0]["candidate_cents"] is None and not result["partial_totals_cents"]


def test_duplicate_xml_and_altered_sources_rejected():
    data = batch()
    data["purchases"].append(copy.deepcopy(data["purchases"][0]))
    with pytest.raises(FiscalValidationError, match="duplicate purchase"):
        run(data)
    data["purchases"].pop()
    data["rules"][0]["legal_source"]["sha256"] = "0" * 64
    with pytest.raises(FiscalValidationError, match="integrity"):
        run(data)


def test_changed_bookkeeping_projection_with_original_hash_is_refused():
    data = batch()
    bind_book(data)
    data["books"]["complete_taxes"].append("ipi")
    with pytest.raises(FiscalValidationError, match="extract differs"):
        detect(Batch.model_validate(data), BUYER, _context(), TODAY)


@pytest.mark.parametrize(
    "observed,status", [({}, "insufficient_basis"), ({"synthetic-condition": False}, "excluded")]
)
def test_reviewed_conditions_distinguish_missing_and_contradicted(observed, status):
    data = batch()
    data["purchases"][0]["uses"][0]["observed_facts"] = observed
    row = run(data)["findings"][0]
    assert row["status"] == status and row["candidate_cents"] is None


def test_postgres_replay_revision_rollback_rls_and_shared_cnpj(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    data = batch()
    data["rules"][0]["cnae"] = context.cnae
    bind_book(data)
    facts = Batch.model_validate(data)

    def write(store, version, payload=facts):
        return import_credits(store, BUYER, MONTH, version, payload, context=context, as_of=TODAY)

    with db.economy(scope) as store:
        first = write(store, 1)
    with db.economy(scope) as store:
        assert write(store, 1) == {
            "replay": True,
            "version": 1,
            "snapshot_digest": first["snapshot_digest"],
        }
    key = f"unused-credits-{BUYER.value}-{MONTH.isoformat()}"
    with db.economy(scope, read_only=True) as store:
        record = store.record("fm_economy_snapshots", key)
        assert record["content"]["partial_totals_cents"] == {"icms": 334}
        page = record["content"]["page_refs"][0]
        assert (
            store.record("fm_economy_snapshots", page["record_id"], 1)["digest"] == page["digest"]
        )
    changed = facts.model_copy(update={"books": None})
    with pytest.raises(FiscalValidationError, match="conflict"), db.economy(scope) as store:
        write(store, 1, changed)
    with pytest.raises(RuntimeError), db.economy(scope) as store:
        write(store, 2, changed)
        raise RuntimeError("induced rollback")
    with db.economy(scope, read_only=True) as store:
        assert store.record("fm_economy_snapshots", key)["version"] == 1
        assert store.snapshot(key + "-source-0", 2) is None
    other = replace(scope, unit_id="second-unit")
    with db.economy(other, read_only=True) as store:
        assert store.record("fm_economy_snapshots", key) is None
    with db() as uow:
        old = uow.control_plane.get_profile(context.profile_id, context.profile_version)
        unit = uow.control_plane.get_unit(scope.tenant_id, scope.unit_id)
        uow.control_plane.add_unit(replace(unit, unit_id=other.unit_id))
        uow.control_plane.add_profile(replace(old, profile_id="second-profile", scope=other))
        uow.commit()
    for unit_scope in (scope, other):
        with pytest.raises(FiscalValidationError, match="ambiguous credit recipient"):
            verify_credit_unit(db, unit_scope, BUYER)


@pytest.mark.parametrize(
    "code,tax,year,expected",
    [
        ("1", "ibs_presumido", 2026, None),
        ("3", "ibs_presumido", 2027, None),
        ("3", "cbs_presumido", 2027, 334),
        ("3", "ibs_presumido", 2029, 334),
        ("2", "cbs_presumido", 2029, None),
    ],
)
def test_presumed_catalog_filters_model_and_tax_effective_date(code, tax, year, expected):
    as_of = date(year, 2, 1)
    data = batch(tax, "insumo", date(year, 1, 1), as_of)
    data["rules"][0]["presumed_credit_code"] = code
    use = data["purchases"][0]["uses"][0]
    use["observed_facts"]["eligible_recycling_acquisition"] = True
    assert run(data, as_of)["findings"][0]["candidate_cents"] == expected
    use["observed_facts"].pop("payment_documented")
    assert run(data, as_of)["findings"][0]["candidate_cents"] is None
