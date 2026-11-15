"""Official ExportaNFe v3 cancellation evidence, correlated to an immutable PMB004 event.

Barueri export record 2, position 67: A (active) or C (cancelled); positions
68-75: cancellation date. A SOAP OK200 or batch status is never this evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.gateway.barueri_official_return_file import (
    BarueriConvertedNfseEvidence,
    parse_barueri_official_return_file,
)
from kordena_fiscal.gateway.barueri_pmb004_homologation import (
    BarueriReceipt,
    BarueriRpsBatch,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4VerifiedInvoice


class BarueriCancellationProofError(FiscalValidationError):
    """The exported event cannot establish the cancellation of this specific NFS-e."""


@dataclass(frozen=True, slots=True)
class BarueriCancellationEvidence:
    cancelled_on: date
    event_remittance: str
    invoice_number: str
    official_return: bytes
    replacement_return: BarueriConvertedNfseEvidence | None = None
    replacement_invoice: Sp4VerifiedInvoice | None = None


def verify_barueri_cancellation_return(
    *, event: BarueriRpsBatch, issued: Sp4VerifiedInvoice, receipt: BarueriReceipt,
) -> BarueriCancellationEvidence:
    """Require a source-bound Type-2 C and validated ExportaNFe-v3 trailer."""
    if (
        not isinstance(event, BarueriRpsBatch)
        or not isinstance(issued, Sp4VerifiedInvoice)
        or not isinstance(receipt, BarueriReceipt)
        or receipt.operation != "NFeLoteBaixarArquivo"
        or receipt.code != "OK200"
        or receipt.situation not in (None, "1")
        or not isinstance(receipt.downloaded_file, bytes)
        or not 0 < len(receipt.downloaded_file) <= 2_097_152
    ):
        raise BarueriCancellationProofError("Official Barueri cancelled file is absent")
    raw = receipt.downloaded_file
    if b"\x00" in raw or b"\n" in raw.replace(b"\r\n", b""):
        raise BarueriCancellationProofError("Invalid Barueri cancellation file framing")
    rows = raw.replace(b"\r\n", b"\r").split(b"\r")
    if rows and not rows[-1]:
        rows.pop()
    if len(rows) < 4:
        raise BarueriCancellationProofError("Incomplete Barueri cancellation export")
    head, *details, footer = rows
    if (
        len(head) != 41
        or head[0:1] != b"1"
        or head[1:8] != event.municipal_registration.encode("ascii")
        or head[24:30] != b"PMB003"
        or head[30:41] != event.remittance.encode("ascii")
        or len(footer) != 38 or footer[:1] != b"9"
        or not footer[1:8].isdigit()
        or int(footer[1:8]) != len(rows)
        or not footer[8:38].isdigit()
        or len([row for row in details if row[:1] == b"2"]) != 1
        or not any(row[:1] == b"3" for row in details)
        or details[0][:1] != b"2"
        or any(
            row[:1] not in (b"2", b"3", b"4")
            or len(row) != {b"2": 1678, b"3": 95, b"4": 18}[row[:1]]
            for row in details
        )
    ):
        raise BarueriCancellationProofError("Barueri cancellation layout does not match event")
    note = details[0]
    event_records = event.rps_bytes.split(b"\r\n")
    if len(event_records) < 3 or len(event_records[1]) != 1970:
        raise BarueriCancellationProofError("Missing approved event RPS record")
    event_detail = event_records[1]
    if (
        event_detail[39:40] != b"C"
        or event_detail[40:42] not in (b"01", b"02", b"03")
        or not event_detail[42:49].isdigit()
        or not note[5:12].isdigit()
        or not note[54:64].isdigit()
        or int(event_detail[42:49]) != int(issued.invoice_number)
        or int(note[5:12]) != int(issued.invoice_number)
        or int(note[54:64]) != int(issued.rps_number)
        or note[50:54].decode("ascii", "strict").strip() != issued.rps_series
        or note[26:50].decode("ascii", "strict").strip() != issued.verification_code
        or note[1628:1678].decode("ascii", "strict").strip() != issued.invoice_reference
        or note[66:67] != b"C"
    ):
        raise BarueriCancellationProofError("Barueri cancelled note differs from original")
    when = note[67:75]
    try:
        if not when.isdigit():
            raise ValueError
        cancelled = datetime.strptime(when.decode("ascii"), "%Y%m%d").date()
    except ValueError:
        raise BarueriCancellationProofError("Invalid Barueri official cancellation date") from None
    service_cents = 0
    for detail in details[1:]:
        if detail[:1] != b"3":
            continue
        quantity, unit = detail[1:7], detail[76:91]
        if not quantity.isdigit() or not unit.isdigit() or int(quantity) < 1:
            raise BarueriCancellationProofError("Invalid Barueri cancelled service amount")
        service_cents += int(quantity) * int(unit)
    if (
        service_cents != int(footer[8:23])
        or Decimal(service_cents) / 100 != issued.gross_amount
    ):
        raise BarueriCancellationProofError("Barueri cancelled service total differs")
    return BarueriCancellationEvidence(
        cancelled_on=cancelled, event_remittance=event.remittance,
        invoice_number=issued.invoice_number, official_return=raw,
    )



def verify_barueri_substitution_return(
    *,
    event: BarueriRpsBatch,
    issued: Sp4VerifiedInvoice,
    replacement_batch: BarueriRpsBatch,
    receipt: BarueriReceipt,
) -> BarueriCancellationEvidence:
    """Verify BOTH sides of a PMB004 reason-03 substitution in one official export.

    ExportaNFe v3 allows repeated Type-2 invoice groups. The return file must
    contain the old C and new A records, each source-correlated with their
    independent RPS and totals; otherwise neither lifecycle can be finalized.
    The projected single-note groups below are only strict parser inputs.
    The raw full municipal return is preserved as original event evidence.
    """
    if (
        not isinstance(event, BarueriRpsBatch)
        or not isinstance(replacement_batch, BarueriRpsBatch)
        or not isinstance(receipt, BarueriReceipt)
        or receipt.operation != "NFeLoteBaixarArquivo"
        or receipt.code != "OK200"
        or not isinstance(receipt.downloaded_file, bytes)
        or not 0 < len(receipt.downloaded_file) <= 2_097_152
        or event.scope.identity_partition_key
        != replacement_batch.scope.identity_partition_key
        or event.issuer_cnpj != replacement_batch.issuer_cnpj
        or event.municipal_registration != replacement_batch.municipal_registration
    ):
        raise BarueriCancellationProofError("Untrusted Barueri substitution batch")
    raw = receipt.downloaded_file
    if b"\x00" in raw or b"\n" in raw.replace(b"\r\n", b""):
        raise BarueriCancellationProofError("Malformed Barueri substitution framing")
    rows = raw.replace(b"\r\n", b"\r").split(b"\r")
    if rows and rows[-1] == b"":
        rows.pop()
    if len(rows) < 6:
        raise BarueriCancellationProofError("Incomplete Barueri substitution return")
    head, *records, footer = rows
    if (
        len(head) != 41
        or head[:1] != b"1"
        or head[1:8] != event.municipal_registration.encode("ascii")
        or head[24:30] != b"PMB003"
        or head[30:41] != event.remittance.encode("ascii")
        or len(footer) != 38 or footer[:1] != b"9"
        or not footer[1:38].isdigit()
        or int(footer[1:8]) != len(rows)
    ):
        raise BarueriCancellationProofError("Substitution source remittance changed")
    groups: list[list[bytes]] = []
    for record in records:
        kind = record[:1]
        if kind == b"2":
            if len(record) != 1678:
                raise BarueriCancellationProofError("Invalid substitution invoice record")
            groups.append([record])
        elif kind in (b"3", b"4"):
            if not groups or len(record) != {b"3": 95, b"4": 18}[kind]:
                raise BarueriCancellationProofError("Invalid substitution service grouping")
            groups[-1].append(record)
        else:
            raise BarueriCancellationProofError("Unknown Barueri substitution record")
    if len(groups) != 2:
        raise BarueriCancellationProofError(
            "Substitution requires one old cancelled and one new active note"
        )
    old_groups = [
        group for group in groups if group[0][66:67] == b"C"
        and group[0][5:12].isdigit()
        and int(group[0][5:12]) == int(issued.invoice_number)
        and group[0][54:64].isdigit()
        and int(group[0][54:64]) == int(issued.rps_number)
    ]
    new_groups = [
        group for group in groups if group[0][66:67] == b"A"
        and group[0][54:64].isdigit()
        and int(group[0][54:64]) == int(
            replacement_batch.rps_bytes.split(b"\r\n")[1][15:25]
        )
    ]
    if (
        len(old_groups) != 1 or len(new_groups) != 1
        or old_groups[0] is new_groups[0]
        or any(not any(row[:1] == b"3" for row in g) for g in groups)
        or event.rps_bytes.split(b"\r\n")[1][39:42] != b"C03"
        or event.rps_bytes.split(b"\r\n")[1][15:25]
        != replacement_batch.rps_bytes.split(b"\r\n")[1][15:25]
        or event.rps_bytes.split(b"\r\n")[1][513:514]
        not in (b"1", b"2", b"3", b"4", b"5", b"9")
    ):
        raise BarueriCancellationProofError("Substitution event identity mismatch")

    def total(group: list[bytes]) -> int:
        result = 0
        for record in group[1:]:
            if record[:1] != b"3":
                continue
            if (
                not record[1:7].isdigit() or not record[76:91].isdigit()
                or int(record[1:7]) <= 0
            ):
                raise BarueriCancellationProofError("Invalid substitution service total")
            result += int(record[1:7]) * int(record[76:91])
        return result

    grand_total = sum(total(group) for group in groups)
    if grand_total != int(footer[8:23]):
        raise BarueriCancellationProofError("Substitution official totals disagree")

    def single(group: list[bytes]) -> bytes:
        # The canonical validators already verify single-note structure,
        # series, RPS, ADN key, service total and source fingerprint.
        cents = total(group)
        projected_footer = (
            b"9" + f"{len(group) + 2:07d}".encode("ascii")
            + f"{cents:015d}".encode("ascii") + b"0" * 15
        )
        return b"\r\n".join((head, *group, projected_footer)) + b"\r\n"

    old = verify_barueri_cancellation_return(
        event=event, issued=issued,
        receipt=replace(receipt, downloaded_file=single(old_groups[0])),
    )
    # A Type-2 replacement source still uses its own immutable RPS, but
    # the municipal return header correctly identifies the EVENT remittance.
    new_header = (
        b"1" + event.municipal_registration.encode("ascii")
        + b"PMB004" + event.remittance.encode("ascii")
    )
    replacement_lines = replacement_batch.rps_bytes.split(b"\r\n")
    remapped = BarueriRpsBatch(
        scope=replacement_batch.scope,
        issuer_cnpj=replacement_batch.issuer_cnpj,
        municipal_registration=replacement_batch.municipal_registration,
        tax_regime=replacement_batch.tax_regime,
        competence_date=replacement_batch.competence_date,
        remittance=event.remittance, file_name=event.file_name,
        rps_bytes=b"\r\n".join(
            (new_header, *replacement_lines[1:-1]),
        ) + b"\r\n",
    )
    active = parse_barueri_official_return_file(
        batch=remapped,
        receipt=replace(receipt, downloaded_file=single(new_groups[0])),
    )
    if (
        active.note_number == str(int(issued.invoice_number)).zfill(7)
        or active.access_key == issued.invoice_reference
        or active.service_total
        != Decimal(int(replacement_lines[1][463:478])) / 100
    ):
        raise BarueriCancellationProofError(
            "Substitute fiscal note not independent of cancelled original"
        )
    return replace(
        old, official_return=raw, replacement_return=active,
    )
