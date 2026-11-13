"""Read-only Barueri NFS-e XML recovery is host-bound and requires XML."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from kordena_fiscal.gateway.barueri_official_invoice_xml import (
    BarueriOfficialXmlError,
    retrieve_barueri_original_invoice_xml,
)
from kordena_fiscal.gateway.barueri_official_return_file import (
    BarueriConvertedNfseEvidence,
)


def _source() -> BarueriConvertedNfseEvidence:
    return BarueriConvertedNfseEvidence(
        remittance="20261113001", note_number="0008765", note_series="NF",
        verification_code="ABCDEF12345", access_key="35" + "0" * 48,
        rps_number="0000000042", rps_series="", service_total=Decimal("150.00"),
        return_file=b"official-return-export-bytes",
    )


def test_approved_note_uses_fixed_official_homologation_url_only() -> None:
    exchange = Mock(return_value=b"<CompNfse><Numero>8765</Numero></CompNfse>")
    value = retrieve_barueri_original_invoice_xml(evidence=_source(), exchange=exchange)
    assert b"<CompNfse>" in value
    args = exchange.call_args.args
    parsed = urlsplit(args[0])
    assert parsed.hostname == "testeeiss.barueri.sp.gov.br"
    assert parsed.scheme == "https"
    assert parsed.path == "/nfe/xmlNFe.ashx"
    assert parse_qs(parsed.query) == {
        "codigoautenticidade": ["ABCDEF12345"], "numdoc": ["0008765"],
    }
    assert args[1] == 15


@pytest.mark.parametrize("raw", [
    b"<html><body>No note exists</body></html>",
    b"invoice not found", b"",
    b"<!DOCTYPE a><CompNfse/>",
    b"<?xml version='1.0'?><!DOCTYPE a [<!ENTITY x SYSTEM 'file:///tmp/x'>]>"
    b"<CompNfse>&x;</CompNfse>",
])
def test_invalid_retrieval_never_promotes_municipal_xml(raw: bytes) -> None:
    with pytest.raises(BarueriOfficialXmlError):
        retrieve_barueri_original_invoice_xml(
            evidence=_source(), exchange=Mock(return_value=raw),
        )


def test_url_validation_rejects_secret_and_unsafe_identifiers() -> None:
    from kordena_fiscal.gateway.barueri_official_return_file import BarueriReturnError

    with pytest.raises(BarueriReturnError):
        replace(_source(), verification_code="ABC DEF")
    for code in ("AA/BB", "ABC?key=leak"):
        bad = replace(_source(), verification_code=code)
        with pytest.raises(BarueriOfficialXmlError):
            retrieve_barueri_original_invoice_xml(evidence=bad, exchange=Mock())
    with pytest.raises(BarueriReturnError):
        replace(_source(), note_number="not-a-number")
