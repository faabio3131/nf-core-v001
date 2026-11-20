"""RTC-RFB-03/04: official Simples calculator adapter never trusts HTTP 200 alone.

Replies are synthetic but follow the record types of the pinned official source
(ObservabilidadeSimplesDomain / ObjetoSimplesDomain / VersaoDomain).
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from kordena_fiscal.tax.rfb_simples_calculator import (
    CALCULATE_PATH,
    SIMPLES_CALCULATOR_PIN,
    RfbCalculationRejected,
    RfbCalculatorError,
    RfbSimplesCalculatorClient,
    SimplesItem,
    build_request,
    compare_shadow,
    parse_response,
)

BASE = "http://nfcore-rtc-simples:8082/api"


def _item(n: int = 1, **extra) -> SimplesItem:
    return SimplesItem(numero=n, c_class_trib="000001", base_calculo=Decimal("950.00"), **extra)


def _reply(*objects: dict) -> bytes:
    return json.dumps({"oper": {"tpDoc": "NFSe"}, "objetos": list(objects),
                       "total": {"vIBSSNtot": 1.9, "vCBSSNtot": 4.75}}).encode()


def _calc(n: int = 1, ibs: float = 1.9, cbs: float = 4.75) -> dict:
    return {"nObj": n, "estadoItem": "CALCULADO",
            "tribCalc": {"vBC": 950.0, "vIBSSN": ibs, "vCBSSN": cbs}, "erros": []}


def _transport(post_reply: bytes, version: dict | None = None, calls: list | None = None):
    def transport(method, url, body, timeout):
        if calls is not None:
            calls.append((method, url, body))
        if url.endswith("/versao"):
            return json.dumps(version or {
                "versaoApp": SIMPLES_CALCULATOR_PIN.application_version, "versaoDb": "15.0.0",
            }).encode(), {}
        return post_reply, {}
    return transport


def test_calculated_items_are_parsed_as_decimals_with_version_evidence() -> None:
    calls: list = []
    client = RfbSimplesCalculatorClient(
        base_url=BASE, transport=_transport(_reply(_calc()), calls=calls),
    )
    request = build_request(operation_id="op-1", date="2026-11-19", document_type="55",
                            crt="1", items=[_item()])
    result = client.calculate(request).require_all_calculated()
    assert result.items[0].values["vIBSSN"] == Decimal("1.9")
    assert isinstance(result.items[0].values["vCBSSN"], Decimal)
    assert result.component_version == "app=1.0.2;db=15.0.0"
    assert calls[1][1] == BASE + CALCULATE_PATH
    sent = json.loads(calls[1][2])
    assert sent["itens"][0] == {"numero": 1, "cClassTrib": "000001", "baseCalculo": "950.00",
                                "valorImpostoSeletivo": "0.00"}
    assert sent["versao"] == "2.0.0"


@pytest.mark.parametrize("state", ["NAO_CALCULADO", "NAO_IMPLEMENTADO",
                                   "INCONSISTENCIA_ENTRADA", "FALHA_TECNICA"])
def test_http_200_with_a_failed_item_is_never_usable_for_issuance(state) -> None:
    failed = {"nObj": 2, "estadoItem": state, "erros": [{"code": "VSN-027"}]}
    client = RfbSimplesCalculatorClient(
        base_url=BASE, transport=_transport(_reply(_calc(1), failed)),
    )
    request = build_request(operation_id="op-2", date="2026-11-19", document_type="55",
                            crt="1", items=[_item(1), _item(2)])
    result = client.calculate(request)
    with pytest.raises(RfbCalculationRejected) as error:
        result.require_all_calculated()
    assert error.value.rejected == ((2, state, ("VSN-027",)),)


@pytest.mark.parametrize("objects", [
    [],                                   # nothing answered
    [_calc(1), _calc(1)],                 # duplicated item
    [_calc(3)],                           # item never requested
    [{"nObj": 1, "estadoItem": "OK"}],    # unknown state
    [{"nObj": 1, "estadoItem": "CALCULADO", "tribCalc": None}],  # calculated without values
])
def test_reply_must_answer_exactly_the_requested_items(objects) -> None:
    with pytest.raises(RfbCalculatorError):
        parse_response(_reply(*objects), expected_items=[1], component_version="x")


def test_unpinned_component_version_is_refused_before_any_calculation() -> None:
    calls: list = []
    client = RfbSimplesCalculatorClient(
        base_url=BASE,
        transport=_transport(_reply(_calc()), {"versaoApp": "0.0.7", "versaoDb": "1"}, calls),
    )
    with pytest.raises(RfbCalculatorError, match="differs from pinned"):
        client.calculate(build_request(operation_id="op", date="2026-11-19",
                                       document_type="55", crt="1", items=[_item()]))
    assert all(method == "GET" for method, _, _ in calls)


@pytest.mark.parametrize("url", [
    "https://piloto-cbs.tributos.gov.br/servico/calculadora-consumo/api",
    "http://user:pw@localhost:8082/api", "http://localhost:8082/other", "ftp://localhost/api",
])
def test_only_internal_component_urls_are_accepted(url) -> None:
    with pytest.raises(RfbCalculatorError):
        RfbSimplesCalculatorClient(base_url=url)


@pytest.mark.parametrize("item", [
    SimplesItem(numero=1, c_class_trib="1", base_calculo=Decimal("1.00")),
    SimplesItem(numero=1, c_class_trib="000001", base_calculo=Decimal("1.001")),
    SimplesItem(numero=1, c_class_trib="000001", base_calculo=Decimal("-1.00")),
    SimplesItem(numero=1, c_class_trib="000001", base_calculo=Decimal("1.00"), c_ativ_sn="1"),
    SimplesItem(
        numero=1, c_class_trib="000001", base_calculo=Decimal("1.00"), p_ibs_sn=Decimal("101"),
    ),
])
def test_invalid_inputs_never_reach_the_component(item) -> None:
    with pytest.raises(RfbCalculatorError):
        build_request(
            operation_id="op", date="2026-11-19", document_type="55", crt="1", items=[item],
        )


def test_shadow_comparison_only_reports_divergences() -> None:
    official = parse_response(_reply(_calc(1), _calc(2, ibs=2.0)), expected_items=[1, 2],
                              component_version="x")
    ours = {1: {"vIBSSN": Decimal("1.90"), "vCBSSN": Decimal("4.75"), "vBC": Decimal("950.00")},
            2: {"vIBSSN": Decimal("1.90"), "vCBSSN": Decimal("4.75"), "vBC": Decimal("950.00")}}
    divergences = compare_shadow(official, ours)
    assert [(d.numero, d.field, d.nfcore, d.official) for d in divergences] == [
        (2, "vIBSSN", Decimal("1.90"), Decimal("2.0")),
    ]


@pytest.mark.parametrize(("document_type", "crt", "regime"), [
    ("99", "1", None),     # NFS-e is not in the official database load yet
    ("55", "4", None),     # MEI is out of the official scope
    ("55", "3", None),     # CRT 3 only with tpRegimeIBSCBS=2
    ("55", "1", "2"),      # tpRegimeIBSCBS=2 only with CRT 3
])
def test_official_scope_is_enforced_before_calling(document_type, crt, regime) -> None:
    with pytest.raises(RfbCalculatorError):
        build_request(operation_id="op", date="2026-11-19", document_type=document_type,
                      crt=crt, items=[_item()], ibs_cbs_regime=regime)
    assert build_request(operation_id="op", date="2026-11-19", document_type="55", crt="3",
                         items=[_item()], ibs_cbs_regime="2")["tpRegimeIBSCBS"] == "2"
