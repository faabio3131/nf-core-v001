"""DANFE rendering requires a real, protocol-consistent signed model-55 XML."""
from __future__ import annotations

import pytest

from kordena_fiscal.archive.danfe_pdf import render_authorized_nfe_danfe
from kordena_fiscal.domain import FiscalValidationError

_KEY = "3" * 44
_NFE = "http://www.portalfiscal.inf.br/nfe"
_DS = "http://www.w3.org/2000/09/xmldsig#"


def _authorized_xml(
    *, status: str = "100", environment: str = "2",
    model: str = "55", key: str = _KEY, signed: bool = True,
) -> bytes:
    signature = (
        f'<Signature xmlns="{_DS}"><SignedInfo/></Signature>' if signed else ""
    )
    return (
        f'<nfeProc xmlns="{_NFE}" versao="4.00">'
        f'<NFe><infNFe Id="NFe{_KEY}"><ide><mod>{model}</mod></ide>'
        f'</infNFe>{signature}</NFe>'
        f'<protNFe><infProt><chNFe>{key}</chNFe>'
        f'<tpAmb>{environment}</tpAmb><cStat>{status}</cStat>'
        f'<nProt>123456789</nProt></infProt></protNFe></nfeProc>'
    ).encode()


def test_renderer_uses_offline_pdf_library_on_verified_xml(monkeypatch: pytest.MonkeyPatch) -> None:
    import brazilfiscalreport.danfe as module

    class FakeDanfe:
        def __init__(self, *, xml: str) -> None:
            assert "<nfeProc" in xml

        def output(self) -> bytearray:
            return bytearray(b"%PDF-1.7\nNFCore signed XML test")

    monkeypatch.setattr(module, "Danfe", FakeDanfe)
    assert render_authorized_nfe_danfe(_authorized_xml()).startswith(b"%PDF-")


@pytest.mark.parametrize(
    "xml",
    [
        _authorized_xml(status="101"),
        _authorized_xml(environment="1"),
        _authorized_xml(model="65"),
        _authorized_xml(key="4" * 44),
        _authorized_xml(signed=False),
        b"<NFe/>",
        b"<!DOCTYPE nfeProc [<!ENTITY external SYSTEM 'file:///etc/passwd'>]><nfeProc/>",
    ],
)
def test_renderer_rejects_non_authorized_content(xml: bytes) -> None:
    with pytest.raises(FiscalValidationError):
        render_authorized_nfe_danfe(xml)


def test_invalid_pdf_result_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import brazilfiscalreport.danfe as module

    class FakeDanfe:
        def __init__(self, *, xml: str) -> None:
            assert xml

        def output(self) -> bytes:
            return b"not pdf"

    monkeypatch.setattr(module, "Danfe", FakeDanfe)
    with pytest.raises(FiscalValidationError):
        render_authorized_nfe_danfe(_authorized_xml())
