"""RTC-RFB-04/07: NF-e shadow comparison never changes values and never raises."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from test_bling_canonical import (  # noqa: F401
    map_bling_document,
    mapping,
    order,
    preparation_database,
    sale_document,
    signing_material,
)

from kordena_fiscal.tax.rfb_simples_calculator import (
    SIMPLES_CALCULATOR_PIN,
    RfbSimplesCalculatorClient,
)
from kordena_fiscal.tax.rtc_shadow import nfe_rtc_lines, run_nfe_rtc_shadow

AT = datetime(2026, 11, 19, tzinfo=UTC)


def _rtc_document(mapping, *, classified: bool = True):  # noqa: F811
    sale_document(mapping)  # Simples Nacional issuer (CSOSN 102) from the shared fixture
    rule = mapping["rules"][0]
    rates = replace(
        rule.outcome.nfe_rates, rtc_uf_rate=Decimal("0.1"), rtc_municipal_rate=Decimal("0"),
        rtc_cbs_rate=Decimal("0.9"), rtc_base_mode="net", rtc_financial_mode="informational_2026",
    )
    outcome = replace(
        rule.outcome, ibs_cbs_cst_code="000", ibs_cbs_classification_code="000001",
        ibs_cbs_classification_table_version="IT-2025.002-v1.71", nfe_rates=rates,
    ) if classified else rule.outcome
    mapping["rules"] = (replace(rule, outcome=outcome),)
    return map_bling_document(order(), **mapping)


def _client(objects: list, calls: list):
    def transport(method, url, body, timeout):
        calls.append((method, url, body))
        if url.endswith("/versao"):
            return json.dumps({"versaoApp": SIMPLES_CALCULATOR_PIN.application_version,
                               "versaoDb": "15.0.0"}).encode(), {}
        return json.dumps({"objetos": objects, "total": {}}).encode(), {}
    return RfbSimplesCalculatorClient(base_url="http://nfcore-rtc-simples:8082/api",
                                      transport=transport)


def test_nfcore_values_come_from_the_builder_function(mapping) -> None:  # noqa: F811
    lines = nfe_rtc_lines(_rtc_document(mapping))
    assert lines and lines[0]["cClassTrib"] == "000001"
    assert lines[0]["vCBS"] > 0


def test_shadow_records_divergences_without_touching_the_document(mapping) -> None:  # noqa: F811
    document = _rtc_document(mapping)
    ours = nfe_rtc_lines(document)[0]
    calls: list = []
    official = [{"nObj": 1, "estadoItem": "CALCULADO", "tribCalc": {
        "vBC": float(ours["base"]), "vIBSSN": float(ours["vIBS"]),  # same IBS
        "vCBSSN": float(Decimal(str(ours["vCBS"])) + Decimal("0.01")),  # CBS differs
    }}]
    record = run_nfe_rtc_shadow(_client(official, calls), document, model="55", occurred_at=AT)
    if record["status"] == "skipped_outside_official_simples_scope":
        pytest.skip("fixture issuer is not Simples Nacional")
    assert record["status"] == "compared" and record["authoritative"] is False
    assert [d["field"] for d in record["divergences"]] == ["vCBSSN"]
    assert record["component_version"] == "app=1.0.2;db=15.0.0"
    sent = json.loads(calls[1][2])
    assert sent["tpDoc"] == "55" and sent["itens"][0]["cClassTrib"] == "000001"
    json.dumps(record)  # archivable as-is


def test_official_failure_or_outage_is_a_status_never_an_exception(mapping) -> None:  # noqa: F811
    document = _rtc_document(mapping)

    def down(*_args):
        raise OSError("connection refused")

    client = RfbSimplesCalculatorClient(base_url="http://nfcore-rtc-simples:8082/api",
                                        transport=down)
    record = run_nfe_rtc_shadow(client, document, model="55", occurred_at=AT)
    assert record["status"] in {"shadow_unavailable", "skipped_outside_official_simples_scope"}


def test_lines_without_rtc_classification_are_skipped(mapping) -> None:  # noqa: F811
    calls: list = []
    record = run_nfe_rtc_shadow(_client([], calls), _rtc_document(mapping, classified=False),
                                model="55", occurred_at=AT)
    assert record["status"] == "skipped_no_rtc_classification" and not calls


def test_crt3_issuer_is_compared_with_the_regime_regular_calculator(
    mapping, monkeypatch,  # noqa: F811
) -> None:
    from kordena_fiscal.tax import rtc_shadow
    from kordena_fiscal.tax.rfb_regime_regular_calculator import (
        CALCULATOR_DATABASE_VERSION,
        REGIME_REGULAR_CALCULATOR_PIN,
        RfbRegimeRegularCalculatorClient,
    )

    document = _rtc_document(mapping)
    ours = nfe_rtc_lines(document)[0]
    # Route as a CRT 3 (Lucro Presumido/Real) issuer; the line values stay NFCore's.
    monkeypatch.setattr(rtc_shadow, "_crt", lambda _document: "3")
    calls: list = []

    def transport(method, url, body, timeout):
        calls.append((method, url, body))
        if url.endswith("/versao"):
            return json.dumps({"versaoApp": REGIME_REGULAR_CALCULATOR_PIN.application_version,
                               "versaoDb": CALCULATOR_DATABASE_VERSION}).encode(), {}
        return json.dumps({"objetos": [{"nObj": 1, "estadoItem": "CALCULADO", "tribCalc": {
            "IBSCBS": {"gIBSCBS": {
                "vBC": str(Decimal(str(ours["base"])).quantize(Decimal("0.01"))),
                "vIBS": str(ours["vIBS"]),
                "gCBS": {"vCBS": str(ours["vCBS"])},
            }}}}]}).encode(), {}

    simples_calls: list = []
    record = run_nfe_rtc_shadow(
        _client([], simples_calls), document, model="55", occurred_at=AT,
        regime_regular_client=RfbRegimeRegularCalculatorClient(
            base_url="http://nfcore-rtc-regime-regular:8080/api", transport=transport),
    )
    assert record["status"] == "compared" and record["calculator"] == "regime_regular"
    assert record["divergences"] == [] and not simples_calls
    sent = json.loads(calls[1][2])
    assert sent["tpDoc"] == 55 and sent["itens"][0]["cst"] == "000"
    assert len(sent["itens"][0]["ncm"]) == 8
    json.dumps(record)


def test_rule_cativsn_is_sent_to_the_simples_calculator(mapping) -> None:  # noqa: F811
    from kordena_fiscal.domain import FiscalValidationError

    document = _rtc_document(mapping)
    rule = mapping["rules"][0]
    with pytest.raises(FiscalValidationError):
        replace(rule.outcome, simples_activity_code="15")
    mapping["rules"] = (replace(rule, outcome=replace(rule.outcome, simples_activity_code="01")),)
    document = map_bling_document(order(), **mapping)
    assert nfe_rtc_lines(document)[0]["cAtivSN"] == "01"
    calls: list = []
    record = run_nfe_rtc_shadow(_client([{"nObj": 1, "estadoItem": "CALCULADO", "tribCalc": {
        "vBC": "1.00", "vIBSSN": "0.00", "vCBSSN": "0.00"}}], calls), document, model="55",
        occurred_at=AT)
    if record["status"] == "skipped_outside_official_simples_scope":
        pytest.skip("fixture issuer is not Simples Nacional")
    assert json.loads(calls[1][2])["itens"][0]["cAtivSN"] == "01"


def test_preparation_archives_the_shadow_after_commit_and_never_breaks_it(
    mapping, signing_material, preparation_database, monkeypatch,  # noqa: F811
) -> None:
    from kordena_fiscal.application import rtc_shadow_recorder
    from kordena_fiscal.application.nfe_preparation import prepare_nfe_sale
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions
    from kordena_fiscal.tax.rtc_shadow import SHADOW_MEDIA_TYPE

    document = _rtc_document(mapping)
    ours = nfe_rtc_lines(document)[0]
    official = [{"nObj": 1, "estadoItem": "CALCULADO", "tribCalc": {
        "vBC": str(ours["base"]), "vIBSSN": str(ours["vIBS"]), "vCBSSN": str(ours["vCBS"])}}]
    calls: list = []
    monkeypatch.setattr(rtc_shadow_recorder, "shadow_clients_from_env",
                        lambda: (_client(official, calls), None))
    result = prepare_nfe_sale(
        preparation_database, document, options=NfeSaleOptions("VENDA", 1, 9), series=1,
        certificate=signing_material, now=datetime.now(UTC),
    )
    with preparation_database() as uow:
        entries = uow.archive.list_for_document(document.scope, result)
    shadows = [entry for entry in entries if entry.media_type == SHADOW_MEDIA_TYPE]
    assert len(shadows) == 1
    record = json.loads(shadows[0].content)
    assert record["authoritative"] is False
    assert record["status"] in {"compared", "skipped_outside_official_simples_scope"}


def test_shadow_recorder_swallows_archive_failures(mapping) -> None:  # noqa: F811
    from kordena_fiscal.application.rtc_shadow_recorder import record_rtc_shadow

    def broken_factory():
        raise RuntimeError("database down")

    document = _rtc_document(mapping)
    assert record_rtc_shadow(
        broken_factory, document, model="55", occurred_at=AT,
        simples=_client([], []), regime_regular=None,
    ) is None
    assert record_rtc_shadow(
        broken_factory, document, model="55", occurred_at=AT,
        simples=None, regime_regular=None,
    ) is None
