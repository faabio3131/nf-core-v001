"""Barueri PMB004 official January/2026 fixed-width batch assembler.

The owner of fiscal mapping builds a 1970-byte Type 2 RPS and its 531-byte
RTC/ADN Type 4 companion from the existing tax domain. This assembler
constructs the exact 25-byte header and fiscal Type 9 checksums, with source
RPS identity and amount reconciliation, without replacing the field-by-field
official RPS 4.2 XSD/position validator.

Reference: Barueri RPS_Layout-v4.2.pdf, January/2026. No network calls.
"""
from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from kordena_fiscal.domain import FiscalValidationError, TaxRegimeCode
from kordena_fiscal.gateway.barueri_pmb004_homologation import BarueriRpsBatch
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps


class BarueriBatchBuilderError(FiscalValidationError):
    """The prepared municipal RPS record disagrees with its durable authority."""


def _row(value: bytes, name: str, prefix: bytes, length: int) -> bytes:
    if (
        not isinstance(value, bytes)
        or len(value) != length
        or not value.startswith(prefix)
        or not value.isascii()
        or b"\r" in value or b"\n" in value
    ):
        raise BarueriBatchBuilderError(f"Invalid official Barueri {name} record")
    return value


def build_barueri_single_rps_batch(
    *, source: Sp4OriginalRps, regime: TaxRegimeCode,
    municipal_registration: str,
    rps_detail: bytes, rtc_adn_detail: bytes,
    retained_tax_record: bytes | None = None,
    retained_tax_records: Sequence[bytes] = (),
    optional_record_5: Sequence[bytes] = (),
) -> BarueriRpsBatch:
    """Assemble one immutable, source-scoped PMB004 fiscal remittance.

    No value is invented: the 2026 RPS/RTC records come from the tax engine.
    The builder supplies a fixed-width header/footer and checks original RPS.
    """
    if (
        not isinstance(source, Sp4OriginalRps)
        or source.issuer_ibge != "3505708"
        or not isinstance(regime, TaxRegimeCode)
        or source.municipal_batch_id is None
        or len(source.municipal_batch_id) != 11
        or not isinstance(municipal_registration, str)
        or len(municipal_registration) != 7
        or not municipal_registration.isascii()
        or not municipal_registration.isalnum()
    ):
        raise BarueriBatchBuilderError("Original Barueri municipal RPS authority unavailable")
    detail = _row(rps_detail, "RPS", b"2RPS  ", 1970)
    companion = _row(rtc_adn_detail, "RTC/ADN", b"4", 531)
    if retained_tax_record is not None and retained_tax_records:
        raise BarueriBatchBuilderError("Ambiguous Barueri retention inputs")
    supplied = (
        (retained_tax_record,) if retained_tax_record is not None
        else retained_tax_records
    )
    if not isinstance(supplied, (tuple, list)):
        raise BarueriBatchBuilderError("Barueri retention entries must be a sequence")
    retentions = [
        _row(item, "retention", b"3", 18)
        for item in supplied
    ]
    seen: set[bytes] = set()
    for row in retentions:
        code = row[1:3]
        if code not in (b"01", b"02", b"03", b"04", b"05", b"VN"):
            raise BarueriBatchBuilderError("Unrecognized Barueri Type 3 fiscal code")
        if code in seen or not row[3:18].isdigit() or int(row[3:18]) <= 0:
            raise BarueriBatchBuilderError("Invalid or duplicate Type 3 fiscal value")
        seen.add(code)
    extra = [
        _row(item, "optional VAT", b"5", 697)
        for item in optional_record_5
    ]
    number = detail[15:25]
    series = detail[6:10].decode("ascii").strip()
    if (
        not number.isdigit()
        or int(number) != int(source.rps_number)
        or series != source.rps_series
        or detail[39:40] != b"E"
        or not detail[457:463].isdigit()
        or not detail[463:478].isdigit()
    ):
        raise BarueriBatchBuilderError("Barueri RPS detail differs from original")
    quantity = int(detail[457:463])
    unit_cents = int(detail[463:478])
    if quantity < 1 or unit_cents < 1:
        raise BarueriBatchBuilderError("Barueri RPS service quantity/value invalid")
    cents = quantity * unit_cents
    if Decimal(cents) / 100 != source.gross_amount or cents >= 10**15:
        raise BarueriBatchBuilderError("Official Barueri service total differs from source")
    retained_cents = sum(int(row[3:18]) for row in retentions)
    federal_cents = sum(
        int(row[3:18]) for row in retentions if row[1:3] != b"VN"
    )
    if retained_cents >= 10**15 or federal_cents >= 10**15:
        raise BarueriBatchBuilderError("Barueri Type 3 fiscal total overflow")
    # The mandatory Type 2 retained-tax total must agree with Type 3 even
    # when no records were supplied. Otherwise a caller could declare a
    # positive withholding in Type 2 without any recoverable tax detail.
    withheld = detail[483:498]
    if not withheld.isdigit() or int(withheld) != federal_cents:
        raise BarueriBatchBuilderError(
            "Barueri Type 2 withheld tax conflicts with Type 3 details"
        )
    if federal_cents > cents:
        raise BarueriBatchBuilderError(
            "Barueri federal withholding exceeds original service amount"
        )
    header = (
        b"1" + municipal_registration.encode("ascii")
        + b"PMB004" + source.municipal_batch_id.encode("ascii")
    )
    rows = [header, detail]
    rows.extend(retentions)
    rows.append(companion)
    rows.extend(extra)
    line_count = len(rows) + 1
    if line_count > 9_999_999:
        raise BarueriBatchBuilderError("Barueri batch line count overflow")
    footer = (
        b"9" + f"{line_count:07d}".encode("ascii")
        + f"{cents:015d}".encode("ascii")
        + f"{retained_cents:015d}".encode("ascii")
    )
    content = b"\r\n".join((*rows, footer)) + b"\r\n"
    return BarueriRpsBatch(
        scope=source.scope, issuer_cnpj=source.issuer_cnpj,
        municipal_registration=municipal_registration,
        tax_regime=regime, competence_date=source.competence_date,
        remittance=source.municipal_batch_id,
        file_name=source.municipal_batch_id + ".txt",
        rps_bytes=content,
    )
