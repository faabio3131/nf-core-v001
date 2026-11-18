"""Extrema/WebISS 2.02 IBS/CBS E160 preflight: identifier-first, no XML rewrite.

The actual municipality-specific XSD must be provided and hash-pinned separately.
Passing these tests does not certify Extrema emission or approval at city hall.
"""
from __future__ import annotations

import pytest

from kordena_fiscal.gateway.webiss_2026_schema import (
    WebissMunicipalSchemaUnverified,
    require_extrema_rtc_destination_order,
)

_NS = "http://www.abrasf.org.br/nfse.xsd"


def _rps(destination: str) -> bytes:
    return (
        f'<GerarNfseEnvio xmlns="{_NS}"><Rps><InfDeclaracaoPrestacaoServico>'
        f"<IBSCBS><dest>{destination}</dest></IBSCBS>"
        "</InfDeclaracaoPrestacaoServico></Rps></GerarNfseEnvio>"
    ).encode()


@pytest.mark.parametrize(
    "destination",
    [
        "<CNPJ>11222333000181</CNPJ><xNome>Tomador de teste</xNome>",
        "<CPF>12345678909</CPF><email>tomador@example.invalid</email>",
        "<NIF>FR123456789</NIF><xNome>Teste estrangeiro</xNome>",
        "<cNaoNIF>2</cNaoNIF><xNome>Tomador exterior</xNome>",
    ],
)
def test_extrema_rtc_destination_identifier_first_is_accepted(
    destination: str,
) -> None:
    require_extrema_rtc_destination_order(_rps(destination))


@pytest.mark.parametrize(
    "destination",
    [
        "<xNome>Tomador de teste</xNome><CNPJ>11222333000181</CNPJ>",
        "<end><xLgr>Rua</xLgr></end><CPF>12345678909</CPF>",
        "<email>teste@example.invalid</email><NIF>FR123456789</NIF>",
        "",
    ],
)
def test_extrema_rtc_e160_wrong_destination_order_is_fail_closed(
    destination: str,
) -> None:
    with pytest.raises(WebissMunicipalSchemaUnverified):
        require_extrema_rtc_destination_order(_rps(destination))


def test_extrema_rtc_destination_guard_rejects_dtd_and_invalid_xml() -> None:
    with pytest.raises(WebissMunicipalSchemaUnverified, match="DTD"):
        require_extrema_rtc_destination_order(
            b'<!DOCTYPE abc [<!ENTITY ex "insecure">]><abc>&ex;</abc>'
        )
    with pytest.raises(WebissMunicipalSchemaUnverified, match="Invalid municipal RTC"):
        require_extrema_rtc_destination_order(b"<broken")


def test_preflight_does_not_rewrite_legal_payload_or_signature() -> None:
    original = _rps(
        "<CNPJ>11222333000181</CNPJ><xNome>Tomador de teste</xNome>"
    )
    assert require_extrema_rtc_destination_order(original) is None
    assert original == _rps(
        "<CNPJ>11222333000181</CNPJ><xNome>Tomador de teste</xNome>"
    )


def test_unrelated_abrasf_query_remains_unmodified() -> None:
    query = (
        f'<ConsultarLoteRpsEnvio xmlns="{_NS}"><Prestador>'
        "<CpfCnpj><Cnpj>11222333000181</Cnpj></CpfCnpj></Prestador>"
        "<Protocolo>123</Protocolo></ConsultarLoteRpsEnvio>"
    ).encode()
    require_extrema_rtc_destination_order(query)


@pytest.mark.parametrize(
    ("indicator", "recipient", "must_reject"),
    [
        ("0", "", False),
        ("1", "<dest><CNPJ>11222333000181</CNPJ><xNome>Outro</xNome></dest>", False),
        ("0", "<dest><CNPJ>11222333000181</CNPJ><xNome>Outro</xNome></dest>", True),
        ("1", "", True),
    ],
)
def test_extrema_rtc_inddest_and_optional_recipient_must_agree(
    indicator: str, recipient: str, must_reject: bool,
) -> None:
    xml = (
        f'<GerarNfseEnvio xmlns="{_NS}"><Rps><InfDeclaracaoPrestacaoServico>'
        f"<IBSCBS><indDest>{indicator}</indDest>{recipient}</IBSCBS>"
        "</InfDeclaracaoPrestacaoServico></Rps></GerarNfseEnvio>"
    ).encode()
    if must_reject:
        with pytest.raises(WebissMunicipalSchemaUnverified, match="indDest"):
            require_extrema_rtc_destination_order(xml)
    else:
        require_extrema_rtc_destination_order(xml)
