"""Model-65 DANFCe validation, independent from model-55 DANFE and NFS-e."""
from __future__ import annotations

import pytest

from kordena_fiscal.archive.danfce_pdf import (
    render_authorized_nfce_danfce,
    validate_authorized_nfce_danfce,
)
from kordena_fiscal.domain import FiscalValidationError

_NFE = "http://www.portalfiscal.inf.br/nfe"
_DS = "http://www.w3.org/2000/09/xmldsig#"
_KEY = "3" * 44


def _nfce(
    *, model: str = "65", status: str = "100", environment: str = "2",
    protocol_key: str = _KEY, with_qr: bool = True, with_signature: bool = True,
) -> bytes:
    signature = (
        f'<Signature xmlns="{_DS}"><SignedInfo/></Signature>' if with_signature else ""
    )
    supplement = (
        f'<infNFeSupl><qrCode>https://sefaz.example/nfce?p={_KEY}</qrCode></infNFeSupl>'
        if with_qr else ""
    )
    return (
        f'<nfeProc xmlns="{_NFE}" versao="4.00">'
        f'<NFe><infNFe Id="NFe{_KEY}"><ide><mod>{model}</mod>'
        f'<tpAmb>{environment}</tpAmb></ide></infNFe>{supplement}{signature}</NFe>'
        f'<protNFe><infProt><chNFe>{protocol_key}</chNFe>'
        f'<tpAmb>{environment}</tpAmb><cStat>{status}</cStat>'
        f'<nProt>123456789</nProt></infProt></protNFe></nfeProc>'
    ).encode()


def test_danfce_uses_local_renderer_on_authorized_model65(monkeypatch: pytest.MonkeyPatch) -> None:
    import brazilfiscalreport.danfce as module

    class FakeDanfce:
        def __init__(self, *, xml: str) -> None:
            assert '<nfeProc' in xml and '<mod>65</mod>' in xml

        def output(self) -> bytearray:
            return bytearray(b"%PDF-1.7\nNFCore NFC-e model65")

    monkeypatch.setattr(module, "Danfce", FakeDanfce)
    assert render_authorized_nfce_danfce(_nfce()).startswith(b"%PDF-")


@pytest.mark.parametrize(
    "xml",
    [
        _nfce(model="55"),
        _nfce(status="101"),
        _nfce(environment="1"),
        _nfce(protocol_key="4" * 44),
        _nfce(with_qr=False),
        _nfce(with_signature=False),
        b"<NFe/>",
        b"<!DOCTYPE nfeProc><nfeProc/>",
    ],
)
def test_danfce_refuses_invalid_or_unauthorized_content(xml: bytes) -> None:
    with pytest.raises(FiscalValidationError):
        validate_authorized_nfce_danfce(xml)


def test_danfce_fails_when_pdf_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    import brazilfiscalreport.danfce as module

    class BrokenDanfce:
        def __init__(self, *, xml: str) -> None:
            assert xml

        def output(self) -> bytes:
            return b"not a pdf"

    monkeypatch.setattr(module, "Danfce", BrokenDanfce)
    with pytest.raises(FiscalValidationError):
        render_authorized_nfce_danfce(_nfce())
