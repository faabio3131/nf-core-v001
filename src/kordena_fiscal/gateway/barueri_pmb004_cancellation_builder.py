"""Barueri PMB004 v4.2 cancellation and substitution remittance builder.

Official Prefeitura de Barueri RPS_Layout-v4.2.pdf (06/01/2026), page 2:
record 2 position 40 'C'; reason 41-42 = 01/02/03; fiscal note
43-49; series 50-54; original note issuance date 55-62; reason
description 63-242. For reasons 01/02 the RPS number (16-25)
is ALL ZERO; for 03 it identifies a new, previously reserved RPS.

This constructor does not send, accept, or confirm a cancellation. The
existing authorized transport submits a separate, immutable remittance;
external fiscal reconciliation and operator audit remain in the core.
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from kordena_fiscal.domain import FiscalValidationError, TaxRegimeCode
from kordena_fiscal.gateway.barueri_pmb004_homologation import BarueriRpsBatch
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)


class BarueriCancellationBuilderError(FiscalValidationError):
    """Original RPS and note cannot produce the requested PMB004 event."""


def _ascii_field(value: str, length: int, label: str) -> bytes:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or len(value) > length
        or any(ord(c) < 32 for c in value)
    ):
        raise BarueriCancellationBuilderError(f"Invalid Barueri {label}")
    return value.ljust(length).encode("ascii")


def build_barueri_cancellation_remittance(
    *,
    original: Sp4OriginalRps,
    issued: Sp4VerifiedInvoice,
    regime: TaxRegimeCode,
    municipal_registration: str,
    event_remittance: str,
    event_day: date,
    event_time: time,
    invoice_issued_on: date,
    reason_code: str,
    description: str,
    original_rps_detail: bytes,
    reviewed_rtc_record: bytes,
    replacement_rps_number: str | None = None,
    invoice_series: str = "",
    human_approved: bool,
) -> BarueriRpsBatch:
    """Create one new approved fiscal event from already reviewed source data."""
    if (
        not isinstance(original, Sp4OriginalRps)
        or not isinstance(issued, Sp4VerifiedInvoice)
        or original.issuer_ibge != "3505708"
        or issued.issuer_ibge != original.issuer_ibge
        or issued.issuer_cnpj != original.issuer_cnpj
        or issued.rps_number != original.rps_number
        or issued.rps_series != original.rps_series
        or issued.competence_date != original.competence_date
        or issued.gross_amount != original.gross_amount
        or not isinstance(regime, TaxRegimeCode)
        or human_approved is not True
        or type(event_day) is not date
        or type(event_time) is not time
        or type(invoice_issued_on) is not date
        or reason_code not in ("01", "02", "03")
        or not isinstance(event_remittance, str)
        or len(event_remittance) != 11
        or not event_remittance.isascii()
        or not event_remittance.isdecimal()
        or event_remittance == original.municipal_batch_id
        or not isinstance(municipal_registration, str)
        or len(municipal_registration) != 7
        or not municipal_registration.isascii()
        or not municipal_registration.isalnum()
        or not isinstance(original_rps_detail, bytes)
        or len(original_rps_detail) != 1970
        or not original_rps_detail.startswith(b"2RPS  ")
        or not isinstance(reviewed_rtc_record, bytes)
        or len(reviewed_rtc_record) != 531
        or not reviewed_rtc_record.startswith(b"4")
    ):
        raise BarueriCancellationBuilderError("Invalid Barueri approved fiscal event source")
    if (
        not issued.invoice_number.isascii()
        or not issued.invoice_number.isdecimal()
        or not 1 <= len(issued.invoice_number) <= 7
        or int(issued.invoice_number) < 1
        or original_rps_detail[39:40] != b"E"
        or not original_rps_detail[15:25].isdigit()
        or int(original_rps_detail[15:25]) != int(original.rps_number)
        or original_rps_detail[6:10].decode("ascii", "strict").strip()
        != original.rps_series
    ):
        raise BarueriCancellationBuilderError("Original RPS or municipal note number differs")
    if reason_code == "03":
        if (
            not isinstance(replacement_rps_number, str)
            or not 1 <= len(replacement_rps_number) <= 7
            or not replacement_rps_number.isascii()
            or not replacement_rps_number.isdecimal()
            or int(replacement_rps_number) <= 0
            or int(replacement_rps_number) == int(original.rps_number)
        ):
            raise BarueriCancellationBuilderError("New replacement RPS must be reserved")
        rps_number = str(int(replacement_rps_number)).zfill(10).encode("ascii")
    elif replacement_rps_number is not None:
        raise BarueriCancellationBuilderError("Normal cancellation cannot allocate a new RPS")
    else:
        rps_number = b"0000000000"
    series = _ascii_field(invoice_series, 5, "official invoice series")
    if not isinstance(description, str) or not description.strip():
        raise BarueriCancellationBuilderError("Cancellation description required")
    if "\r" in description or "\n" in description:
        raise BarueriCancellationBuilderError("Cancellation description contains line break")
    try:
        encoded_description = description.encode("cp1252")
    except UnicodeEncodeError:
        raise BarueriCancellationBuilderError("Municipal cancellation text not encodable") from None
    if len(encoded_description) > 180:
        raise BarueriCancellationBuilderError("Municipal cancellation text exceeds layout")
    detail = bytearray(original_rps_detail)
    detail[15:25] = rps_number
    detail[25:33] = event_day.strftime("%Y%m%d").encode("ascii")
    detail[33:39] = event_time.strftime("%H%M%S").encode("ascii")
    detail[39:40] = b"C"
    detail[40:42] = reason_code.encode("ascii")
    detail[42:49] = issued.invoice_number.zfill(7).encode("ascii")
    detail[49:54] = series
    detail[54:62] = invoice_issued_on.strftime("%Y%m%d").encode("ascii")
    detail[62:242] = encoded_description.ljust(180, b" ")
    if not detail[457:463].isdigit() or not detail[463:478].isdigit():
        raise BarueriCancellationBuilderError("Original service totals were malformed")
    total_cents = int(detail[457:463]) * int(detail[463:478])
    if (
        total_cents >= 10**15
        or Decimal(total_cents) / 100 != original.gross_amount
    ):
        raise BarueriCancellationBuilderError("Original fiscal service amount differs")
    header = (
        b"1" + municipal_registration.encode("ascii") + b"PMB004"
        + event_remittance.encode("ascii")
    )
    # The separate 531-byte RTC/ADN record is supplied by the canonical
    # tax mapper. Its semantics are not fabricated by this event builder.
    footer = (
        b"90000004"
        + f"{total_cents:015d}".encode("ascii")
        + b"000000000000000"
    )
    content = b"\r\n".join(
        (header, bytes(detail), reviewed_rtc_record, footer),
    ) + b"\r\n"
    return BarueriRpsBatch(
        scope=original.scope, issuer_cnpj=original.issuer_cnpj,
        municipal_registration=municipal_registration,
        tax_regime=regime, competence_date=original.competence_date,
        remittance=event_remittance,
        file_name=event_remittance + ".txt",
        rps_bytes=content,
    )
