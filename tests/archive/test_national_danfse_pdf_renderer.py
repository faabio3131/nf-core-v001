"""National DANFSe is generated locally only from consistent XML evidence."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from kordena_fiscal.archive.danfse_pdf import render_authorized_national_danfse
from kordena_fiscal.domain import FiscalValidationError

_NS = "http://www.sped.fazenda.gov.br/nfse"
_KEY = "35" + "0" * 48
_XML = f'<NFSe xmlns="{_NS}"><infNFSe Id="NFS{_KEY}"/></NFSe>'.encode()


def test_danfse_renderer_consumes_national_xml_without_external_http() -> None:
    with patch("brazilfiscalreport.danfse.Danfse") as renderer:
        renderer.return_value.output.return_value = b"%PDF-1.4\nSYNTHETIC"
        assert render_authorized_national_danfse(_XML).startswith(b"%PDF-")
        assert renderer.call_args.kwargs["xml"].startswith("<NFSe")
        renderer.return_value.output.assert_called_once_with(dest="S")


@pytest.mark.parametrize("xml", [
    b"<root/>",
    f'<NFSe xmlns="{_NS}"><infNFSe Id="NFS35111"/></NFSe>'.encode(),
    b'<!DOCTYPE NFSe [<!ENTITY a "x">]><NFSe/>',
    b"",
])
def test_danfse_rejects_wrong_root_or_untrusted_key(xml: bytes) -> None:
    with pytest.raises(FiscalValidationError):
        render_authorized_national_danfse(xml)


def test_danfse_rejects_corrupt_pdf() -> None:
    with patch("brazilfiscalreport.danfse.Danfse") as renderer:
        renderer.return_value.output.return_value = b"not-a-pdf"
        with pytest.raises(FiscalValidationError):
            render_authorized_national_danfse(_XML)
