"""Barueri PMB004 v4.2 officially distinct cancel and substitution RPS numbers."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, time
from decimal import Decimal

import pytest

from kordena_fiscal.domain import (
    Cnpj,
    ExecutionScope,
    FiscalEnvironment,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.barueri_pmb004_cancellation_builder import (
    BarueriCancellationBuilderError,
    build_barueri_cancellation_remittance,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)


def _source() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="barueri", unit_id="u",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="cancel",
        ),
        document_id="original-rps", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3505708",
        competence_date=date(2026, 10, 31), rps_number="42",
        rps_series="", gross_amount=Decimal("150.00"),
        municipal_batch_id="20261031001",
    )


def _issued() -> Sp4VerifiedInvoice:
    src = _source()
    return Sp4VerifiedInvoice(
        issuer_cnpj=src.issuer_cnpj, issuer_ibge=src.issuer_ibge,
        competence_date=src.competence_date, rps_number=src.rps_number,
        rps_series=src.rps_series, gross_amount=src.gross_amount,
        invoice_number="8765", verification_code="ABCD1234",
        invoice_reference="8765", authorized_xml=b"<IssuedNfse/>",
    )


def _original_detail() -> bytes:
    detail = bytearray(b"2RPS  " + b" " * 1964)
    detail[15:25] = b"0000000042"
    detail[25:33] = b"20261031"
    detail[33:39] = b"120000"
    detail[39:40] = b"E"
    detail[457:463] = b"000001"
    detail[463:478] = b"000000000015000"
    return bytes(detail)


def _build(reason: str, **overrides):
    original = overrides.pop("original", _source())
    issued = overrides.pop("issued", _issued())
    return build_barueri_cancellation_remittance(
        original=original, issued=issued,
        regime=TaxRegimeCode.NORMAL,
        municipal_registration="1234567",
        event_remittance="20261113001",
        event_day=date(2026, 11, 13), event_time=time(12, 30, 0),
        invoice_issued_on=date(2026, 10, 31),
        reason_code=reason,
        description="Servico nao prestado",
        original_rps_detail=overrides.pop("original_rps_detail", _original_detail()),
        reviewed_rtc_record=b"4" + b"1" + b" " * 529,
        human_approved=overrides.pop("human_approved", True),
        **overrides,
    )


@pytest.mark.parametrize("reason", ["01", "02"])
def test_normal_cancel_has_zero_rps_and_original_nota_in_official_positions(
    reason: str,
) -> None:
    batch = _build(reason)
    rows = batch.rps_bytes.split(b"\r\n")
    assert [len(r) for r in rows[:-1]] == [25, 1970, 531, 38]
    detail = rows[1]
    assert detail[15:25] == b"0000000000"
    assert detail[39:40] == b"C"
    assert detail[40:42] == reason.encode("ascii")
    assert detail[42:49] == b"0008765"
    assert detail[54:62] == b"20261031"
    assert detail[62:242].rstrip() == b"Servico nao prestado"
    assert batch.remittance != _source().municipal_batch_id
    assert rows[-2] == b"90000004" + b"000000000015000" + b"0" * 15


def test_substitute_requires_new_durable_rps_not_original_one() -> None:
    batch = _build("03", replacement_rps_number="43")
    detail = batch.rps_bytes.split(b"\r\n")[1]
    assert detail[15:25] == b"0000000043"
    assert detail[40:42] == b"03"
    assert detail[42:49] == b"0008765"


@pytest.mark.parametrize("reason", ["01", "03"])
def test_unapproved_event_cannot_be_prepared(reason: str) -> None:
    data = {"replacement_rps_number": "43"} if reason == "03" else {}
    with pytest.raises(BarueriCancellationBuilderError):
        _build(reason, human_approved=False, **data)


def test_wrong_fiscal_note_never_enters_event_remittance() -> None:
    with pytest.raises(BarueriCancellationBuilderError):
        _build("01", issued=replace(_issued(), rps_number="43"))


@pytest.mark.parametrize("number", ["0", "42", "200000000", None])
def test_replacement_cannot_reuse_original_or_invent_sequence(number: str | None) -> None:
    with pytest.raises(BarueriCancellationBuilderError):
        _build("03", replacement_rps_number=number)


def test_normal_cancel_does_not_burn_a_new_rps_number() -> None:
    with pytest.raises(BarueriCancellationBuilderError):
        _build("02", replacement_rps_number="44")


def test_existing_original_remittance_must_not_be_resubmitted_as_cancel() -> None:
    with pytest.raises(BarueriCancellationBuilderError):
        build_barueri_cancellation_remittance(
            original=_source(), issued=_issued(),
            regime=TaxRegimeCode.NORMAL, municipal_registration="1234567",
            event_remittance="20261031001",
            event_day=date(2026, 11, 13), event_time=time(12, 0),
            invoice_issued_on=date(2026, 10, 31), reason_code="01",
            description="Servico nao prestado",
            original_rps_detail=_original_detail(),
            reviewed_rtc_record=b"4" + b"1" + b" " * 529,
            human_approved=True,
        )


def test_two_different_cancelled_notes_with_zero_rps_can_share_one_lot() -> None:
    single = _build("01")
    header, detail1, rtc, _, _ = single.rps_bytes.split(b"\r\n")
    detail2 = bytearray(detail1)
    detail2[42:49] = b"0008766"
    trailer = (
        b"90000006" + b"000000000030000" + b"0" * 15
    )
    multi = b"\r\n".join((
        header, detail1, rtc, bytes(detail2), rtc, trailer,
    )) + b"\r\n"
    approved = replace(single, rps_bytes=multi)
    assert approved.rps_bytes == multi


def test_same_note_cannot_be_cancelled_twice_in_same_remittance() -> None:
    from kordena_fiscal.gateway.barueri_pmb004_homologation import BarueriContractError

    single = _build("01")
    header, detail, rtc, _, _ = single.rps_bytes.split(b"\r\n")
    trailer = b"90000006" + b"000000000030000" + b"0" * 15
    duplicate = b"\r\n".join((
        header, detail, rtc, detail, rtc, trailer,
    )) + b"\r\n"
    with pytest.raises(BarueriContractError, match="Duplicate"):
        replace(single, rps_bytes=duplicate)
