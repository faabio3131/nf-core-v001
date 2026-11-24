"""Source-bound Barueri cancellation proof from official ExportaNFe v3.

These are synthetic bytes, not municipal homologation.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.barueri_official_cancel_return import (
    BarueriCancellationProofError,
    verify_barueri_cancellation_return,
)
from kordena_fiscal.gateway.barueri_pmb004_homologation import (
    BarueriReceipt,
    BarueriRpsBatch,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4VerifiedInvoice


def _event() -> BarueriRpsBatch:
    rec = bytearray(b"2RPS  " + b" " * 1964)
    rec[15:25] = b"0000000000"
    rec[25:33] = b"20261114"
    rec[33:39] = b"120000"
    rec[39:40] = b"C"
    rec[40:42] = b"01"
    rec[42:49] = b"0008765"
    rec[49:54] = b"NF   "
    rec[54:62] = b"20261113"
    rec[62:242] = b"Nota duplicada".ljust(180)
    rec[457:463] = b"000001"
    rec[463:478] = b"000000000015000"
    rows = (
        b"11234567PMB00420261114001", bytes(rec),
        b"41" + b" " * 529,
        b"90000004" + b"000000000015000" + b"0" * 15,
    )
    return BarueriRpsBatch(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="tenant-a", unit_id="unit-b",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="cancel",
        ),
        issuer_cnpj=Cnpj("11222333000181"), municipal_registration="1234567",
        tax_regime=TaxRegimeCode.NORMAL, competence_date=date(2026, 11, 13),
        remittance="20261114001", file_name="20261114001.txt",
        rps_bytes=b"\r\n".join(rows) + b"\r\n",
    )


def _issued() -> Sp4VerifiedInvoice:
    return Sp4VerifiedInvoice(
        issuer_cnpj=Cnpj("11222333000181"),
        issuer_ibge="3505708", competence_date=date(2026, 11, 13),
        rps_number="42", rps_series="", gross_amount=Decimal("150.00"),
        invoice_number="8765", verification_code="AUTHCODE1234567890",
        invoice_reference="35" + "0" * 48,
        authorized_xml=b"<Invoice>official-test-fixture</Invoice>",
    )


def _file() -> bytes:
    head = b"1" + b"1234567" + b" " * 16 + b"PMB003" + b"20261114001"
    note = bytearray(b" " * 1678)
    note[0:1] = b"2"
    note[1:5] = b"NF  "
    note[5:12] = b"0008765"
    note[12:20] = b"20261113"
    note[20:26] = b"120000"
    note[26:50] = b"AUTHCODE1234567890".ljust(24)
    note[50:54] = b"    "
    note[54:64] = b"0000000042"
    note[66:67] = b"C"
    note[67:75] = b"20261114"
    note[1628:1678] = b"35" + b"0" * 48
    service = bytearray(b" " * 95)
    service[0:1] = b"3"
    service[1:7] = b"000001"
    service[76:91] = b"000000000015000"
    footer = b"9" + b"0000004" + b"000000000015000" + b"0" * 15
    return b"\r\n".join((head, bytes(note), bytes(service), footer)) + b"\r\n"


def _receipt(raw: bytes) -> BarueriReceipt:
    return BarueriReceipt(
        operation="NFeLoteBaixarArquivo", code="OK200",
        remittance_protocol="protocol123", situation="1",
        downloaded_file=raw,
    )


def test_cancel_proof_must_match_event_and_authorized_original() -> None:
    evidence = verify_barueri_cancellation_return(
        event=_event(), issued=_issued(), receipt=_receipt(_file()),
    )
    assert evidence.cancelled_on == date(2026, 11, 14)
    assert evidence.event_remittance == "20261114001"
    assert evidence.invoice_number == "8765"


@pytest.mark.parametrize("offset,replacement", [
    (30, b"9"),  # Different remittance.
    (41 + 2 + 66, b"A"),  # Still active, not cancelled.
    (41 + 2 + 71, b"9"),  # Invalid cancellation date.
    (41 + 2 + 5, b"9"),  # Different fiscal note.
    (41 + 2 + 1628, b"9"),  # Different ADN access key.
    (41 + 2 + 1678 + 2 + 76, b"9"),  # Different service total.
])
def test_accepted_soap_never_overrides_unmatched_official_evidence(
    offset: int, replacement: bytes,
) -> None:
    data = bytearray(_file())
    data[offset:offset + len(replacement)] = replacement
    with pytest.raises(BarueriCancellationProofError):
        verify_barueri_cancellation_return(
            event=_event(), issued=_issued(), receipt=_receipt(bytes(data)),
        )


def test_municipal_ok200_without_verified_cancelled_file_is_not_confirmation() -> None:
    with pytest.raises(BarueriCancellationProofError):
        verify_barueri_cancellation_return(
            event=_event(), issued=_issued(),
            receipt=_receipt(b"OK200"),
        )
