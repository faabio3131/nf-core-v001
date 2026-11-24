"""Barueri official January/2026 return layout v3 structural parser.

Confirmed against Prefeitura de Barueri Guia para Conversao RPS em Lote
v1.07 (January/2026), section 7 and annexes: return NFE_Layout-v3.pdf
(August/2025). The current input RPS_Layout.pdf is revision 4.4
(May/2026), still transmitted as PMB004; its additional conditional
service-address rules do not change this return-file structure.
Do not confuse the version 5.5 ERROR LIST with return layout. An error
mirror or OK200 does not prove authorization. The actual fiscal XML must
still be recovered and independently verified by the canonical gateway.

Even a fully correlated source is not XML: the canonical AUTHORIZED transition
requires separate retrieval and verification of the official NFS-e XML/ADN
using its provider-issued access key. This module never synthesizes that XML.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.gateway.barueri_pmb004_homologation import (
    BarueriReceipt,
    BarueriRpsBatch,
)

_LIMIT = 2_097_152


class BarueriReturnError(FiscalValidationError):
    """A bounded, sanitized Barueri return-file parse failure."""


@dataclass(frozen=True, slots=True)
class BarueriConvertedNfseEvidence:
    """Provider return-file evidence: cannot itself authorize a fiscal XML."""

    remittance: str
    note_number: str
    note_series: str
    verification_code: str
    access_key: str
    rps_number: str
    rps_series: str
    service_total: Decimal
    return_file: bytes

    def __post_init__(self) -> None:
        if (
            not isinstance(self.return_file, bytes)
            or not 0 < len(self.return_file) <= _LIMIT
            or not isinstance(self.service_total, Decimal)
            or not self.service_total.is_finite()
            or self.service_total <= 0
            or self.service_total * 100
            != (self.service_total * 100).to_integral_value()
            or not isinstance(self.access_key, str)
            or len(self.access_key) != 50
            or not self.access_key.isascii()
            or not self.access_key.isdecimal()
            or not isinstance(self.rps_number, str)
            or not self.rps_number.isascii()
            or not self.rps_number.isdecimal()
            or not isinstance(self.note_number, str)
            or not self.note_number.isascii()
            or not self.note_number.isdecimal()
            or not isinstance(self.verification_code, str)
            or not 1 <= len(self.verification_code) <= 64
            or any(ord(c) < 33 or ord(c) > 126 for c in self.verification_code)
            or not isinstance(self.remittance, str)
            or len(self.remittance) != 11
            or not self.remittance.isascii()
            or not self.remittance.isdecimal()
        ):
            raise BarueriReturnError("Untrusted Barueri return-file invoice evidence")


def _as_digits(raw: bytes, name: str, *, width: int) -> str:
    if len(raw) != width or not raw.isascii() or not raw.isdigit():
        raise BarueriReturnError(f"Invalid Barueri {name}")
    return raw.decode("ascii")


def _rows(raw: bytes) -> list[bytes]:
    if (
        not isinstance(raw, bytes) or not 0 < len(raw) <= _LIMIT
        or b"\x00" in raw or b"\n" in raw.replace(b"\r\n", b"")
    ):
        raise BarueriReturnError("Invalid Barueri return-file framing")
    rows = raw.replace(b"\r\n", b"\r").split(b"\r")
    if rows and rows[-1] == b"":
        rows.pop()
    if len(rows) < 4:
        raise BarueriReturnError("Missing Barueri NFE return records")
    return rows


def parse_barueri_official_return_file(
    *,
    batch: BarueriRpsBatch,
    receipt: BarueriReceipt,
) -> BarueriConvertedNfseEvidence:
    """Accept one active NFS-e only when original PMB004 remittance matches."""
    if (
        not isinstance(batch, BarueriRpsBatch)
        or not isinstance(receipt, BarueriReceipt)
        or receipt.operation != "NFeLoteBaixarArquivo"
        or receipt.code != "OK200"
        or not receipt.downloaded_file
        or receipt.situation not in (None, "1")
    ):
        raise BarueriReturnError("Barueri has no completed converted invoice file")
    rows = _rows(receipt.downloaded_file)
    header, *rest = rows
    footer = rest.pop()
    if (
        len(header) != 41 or not header.startswith(b"1")
        or header[1:8] != batch.municipal_registration.encode("ascii")
        or header[24:30] != b"PMB003"
        or header[30:41] != batch.remittance.encode("ascii")
        or len(footer) != 38 or not footer.startswith(b"9")
    ):
        raise BarueriReturnError("Official Barueri return header/remittance mismatch")
    if _as_digits(footer[1:8], "footer count", width=7) != f"{len(rows):07d}":
        raise BarueriReturnError("Barueri return file line count differs")
    note_records = [line for line in rest if line[:1] == b"2"]
    service_records = [line for line in rest if line[:1] == b"3"]
    if len(note_records) != 1 or not service_records:
        raise BarueriReturnError("Barueri return must contain exactly one NFS-e")
    if any(
        line[:1] not in (b"2", b"3", b"4")
        or len(line) != {b"2": 1678, b"3": 95, b"4": 18}[line[:1]]
        for line in rest
    ):
        raise BarueriReturnError("Barueri return-file record width/type mismatch")
    if rest[0][:1] != b"2" or any(
        line[:1] == b"2" for line in rest[1:]
    ):
        raise BarueriReturnError("Barueri return-file invoice ordering mismatch")
    note = note_records[0]
    # The official return layout uses absolute 1-based PDF positions.
    note_number = _as_digits(note[5:12], "NFS-e number", width=7)
    rps_number = _as_digits(note[54:64], "RPS number", width=10)
    key = note[1628:1678].decode("ascii", "strict").strip()
    code = note[26:50].decode("ascii", "strict").strip()
    rps_series = note[50:54].decode("ascii", "strict").strip()
    note_series = note[1:5].decode("ascii", "strict").strip()
    if (
        not code or len(code) > 24 or any(ord(c) < 33 for c in code)
        or not key.isascii() or len(key) != 50 or not key.isdecimal()
        or note[66:67] != b"A"
        or int(rps_number) < 1
        or not note_series
    ):
        raise BarueriReturnError("Barueri return is not an active verified-key invoice")
    # Original PMB004 RPS number/series is source-of-truth, never trusted from
    # the downloaded file alone. Its detail record is the first 1970-byte type 2.
    original = batch.rps_bytes.split(b"\r\n")[1]
    original_number = _as_digits(original[15:25], "original RPS number", width=10)
    original_series = original[6:10].decode("ascii", "strict").strip()
    if (
        int(original_number) != int(rps_number)
        or original_series != rps_series
    ):
        raise BarueriReturnError("Official Barueri note refers to a different RPS")
    total_cents = 0
    for line in service_records:
        quantity = int(_as_digits(line[1:7], "service quantity", width=6))
        unit_cents = int(_as_digits(line[76:91], "unit service value", width=15))
        if quantity <= 0:
            raise BarueriReturnError("Barueri service quantity must be positive")
        total_cents += quantity * unit_cents
    if total_cents != int(_as_digits(footer[8:23], "footer total", width=15)):
        raise BarueriReturnError("Barueri service total differs from footer")
    # PMB004 original service value is cents in the type 2 record.
    original_cents = int(_as_digits(original[463:478], "original amount", width=15))
    if total_cents != original_cents:
        raise BarueriReturnError("Barueri official total differs from original PMB004 RPS")
    return BarueriConvertedNfseEvidence(
        remittance=batch.remittance,
        note_number=note_number,
        note_series=note_series,
        verification_code=code,
        access_key=key,
        rps_number=rps_number,
        rps_series=rps_series,
        service_total=Decimal(total_cents) / 100,
        return_file=receipt.downloaded_file,
    )
