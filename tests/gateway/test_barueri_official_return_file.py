"""Barueri official return-file v3 and PMB004 original RPS must reconcile.

The returned text is NOT a signed XML authorization. All examples are synthetic
and never visit a real municipality.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.barueri_official_return_file import (
    BarueriReturnError,
    parse_barueri_official_return_file,
)
from kordena_fiscal.gateway.barueri_pmb004_homologation import (
    BarueriReceipt,
    BarueriRpsBatch,
)


def _original_rps() -> bytes:
    rec = bytearray(b"2RPS  " + b" " * 1964)
    rec[15:25] = b"0000000042"
    rec[25:33] = b"20261113"
    rec[33:39] = b"120000"
    rec[39:40] = b"E"
    rec[457:463] = b"000001"
    rec[463:478] = b"000000000015000"
    return b"\r\n".join((
        b"11234567PMB00420261113001",
        bytes(rec),
        b"41" + b" " * 529,
        b"90000004" + b"000000000015000" + b"0" * 15,
    )) + b"\r\n"


def _batch() -> BarueriRpsBatch:
    return BarueriRpsBatch(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="barueri", unit_id="tax-unit",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="return",
        ),
        issuer_cnpj=Cnpj("11222333000181"), municipal_registration="1234567",
        tax_regime=TaxRegimeCode.NORMAL, competence_date=date(2026, 11, 13),
        remittance="20261113001", file_name="20261113001.txt", rps_bytes=_original_rps(),
    )


def _nfe_return() -> bytes:
    header = b"1" + b"1234567" + b" " * 16 + b"PMB003" + b"20261113001"
    note = bytearray(b" " * 1678)
    note[0:1] = b"2"
    note[1:5] = b"NF  "
    note[5:12] = b"0008765"
    note[12:20] = b"20261113"
    note[20:26] = b"120000"
    note[26:50] = b"AUTHCODE1234567890" + b" " * 6
    note[50:54] = b"    "
    note[54:64] = b"0000000042"
    note[64:65] = b"1"
    note[65:66] = b"N"
    note[66:67] = b"A"
    note[1628:1678] = b"35" + b"0" * 48
    item = bytearray(b" " * 95)
    item[0:1] = b"3"
    item[1:7] = b"000001"
    item[67:76] = b"000001401"
    item[76:91] = b"000000000015000"
    item[91:95] = b"0200"
    trailer = b"9" + b"0000004" + b"000000000015000" + b"0" * 15
    assert (len(header), len(note), len(item), len(trailer)) == (41, 1678, 95, 38)
    return b"\r\n".join((header, bytes(note), bytes(item), trailer)) + b"\r\n"


def _receipt(content: bytes | None = None) -> BarueriReceipt:
    return BarueriReceipt(
        operation="NFeLoteBaixarArquivo", code="OK200",
        remittance_protocol="protocol42", situation="1",
        downloaded_file=_nfe_return() if content is None else content,
    )


def test_official_barueri_return_has_source_correlated_rps_and_adn_key() -> None:
    proof = parse_barueri_official_return_file(batch=_batch(), receipt=_receipt())
    assert proof.note_number == "0008765"
    assert proof.rps_number == "0000000042"
    assert proof.rps_series == ""
    assert proof.service_total == Decimal("150")
    assert len(proof.access_key) == 50
    assert proof.remittance == "20261113001"
    assert proof.return_file.startswith(b"1")


@pytest.mark.parametrize("offset,replacement", [
    (0, b"9"),  # header
    (30, b"0"),  # remittance
    (24, b"X"),  # version
    (41 + 2 + 54, b"9"),  # original RPS number
    (41 + 2 + 66, b"C"),  # cancelled note
])
def test_corrupted_fiscal_header_remittance_or_note_identity_fails(
    offset: int, replacement: bytes,
) -> None:
    content = bytearray(_nfe_return())
    content[offset:offset+len(replacement)] = replacement
    with pytest.raises(BarueriReturnError):
        parse_barueri_official_return_file(
            batch=_batch(), receipt=_receipt(bytes(content)),
        )


def test_returned_rps_error_mirror_cannot_authorize_invoice() -> None:
    with pytest.raises(BarueriReturnError):
        parse_barueri_official_return_file(
            batch=_batch(), receipt=_receipt(_original_rps()),
        )


def test_zero_service_total_or_mismatched_footer_is_rejected() -> None:
    content = _nfe_return().replace(
        b"000000000015000", b"000000000015001", 1,
    )
    with pytest.raises(BarueriReturnError):
        parse_barueri_official_return_file(
            batch=_batch(), receipt=_receipt(content),
        )


def test_file_presence_and_ok200_cannot_replace_real_return_file() -> None:
    with pytest.raises(BarueriReturnError):
        parse_barueri_official_return_file(
            batch=_batch(),
            receipt=BarueriReceipt(
                operation="NFeLoteBaixarArquivo", code="OK200",
                downloaded_file=b"error;RPS rejected",
            ),
        )
