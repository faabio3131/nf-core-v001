"""PMB004 official v4.2 single-note batch built from canonical RPS records."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.barueri_pmb004_batch_builder import (
    BarueriBatchBuilderError,
    build_barueri_single_rps_batch,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps


def _rps() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="barueri", unit_id="u",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="pmb004",
        ),
        document_id="prepared", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3505708",
        competence_date=date(2026, 11, 13), rps_number="42",
        rps_series="", gross_amount=Decimal("150.00"),
        municipal_batch_id="20261113001",
    )


def _detail() -> bytes:
    data = bytearray(b"2RPS  " + b" " * 1964)
    data[15:25] = b"0000000042"
    data[25:33] = b"20261113"
    data[33:39] = b"120000"
    data[39:40] = b"E"
    data[457:463] = b"000001"
    data[463:478] = b"000000000015000"
    data[483:498] = b"000000000000000"
    assert len(data) == 1970
    return bytes(data)


def _rtc() -> bytes:
    return b"4" + b"1" + b" " * 529


def _build(**overrides):
    return build_barueri_single_rps_batch(
        source=overrides.pop("source", _rps()),
        regime=TaxRegimeCode.NORMAL,
        municipal_registration="1234567",
        rps_detail=overrides.pop("rps_detail", _detail()),
        rtc_adn_detail=overrides.pop("rtc_adn_detail", _rtc()),
        **overrides,
    )


def test_original_pmb004_batch_has_exact_header_footer_count_and_rtc_companion() -> None:
    batch = _build()
    lines = batch.rps_bytes.split(b"\r\n")
    assert len(lines[:-1]) == 4
    assert [len(line) for line in lines[:-1]] == [25, 1970, 531, 38]
    assert lines[0] == b"11234567PMB00420261113001"
    assert lines[-2] == b"90000004" + b"000000000015000" + b"0" * 15
    assert batch.file_name == "20261113001.txt"
    assert batch.scope.identity_partition_key == _rps().scope.identity_partition_key


def test_original_id_or_fiscal_amount_cannot_be_replaced_in_rps_bytes() -> None:
    with pytest.raises(BarueriBatchBuilderError, match="service total"):
        _build(source=replace(_rps(), gross_amount=Decimal("149.99")))
    wrong_number = _detail().replace(b"0000000042", b"0000000043", 1)
    with pytest.raises(BarueriBatchBuilderError, match="original"):
        _build(rps_detail=wrong_number)


def test_cancel_action_is_not_mistaken_for_regular_issuance() -> None:
    corrupt = bytearray(_detail())
    corrupt[39:40] = b"C"
    with pytest.raises(BarueriBatchBuilderError):
        _build(rps_detail=bytes(corrupt))


def test_optional_retention_record_is_accounted_for_in_trailer() -> None:
    retained = b"301" + b"000000000001000"
    assert len(retained) == 18
    detail = bytearray(_detail())
    detail[483:498] = b"000000000001000"
    batch = _build(rps_detail=bytes(detail), retained_tax_record=retained)
    parts = batch.rps_bytes.split(b"\r\n")
    assert len(parts[:-1]) == 5
    assert parts[-2] == (
        b"90000005" + b"000000000015000" + b"000000000001000"
    )


def test_multiple_federal_withholdings_reconcile_type2_and_trailer() -> None:
    detail = bytearray(_detail())
    detail[483:498] = b"000000000001500"
    rows = (
        b"301000000000001000",
        b"302000000000000500",
    )
    batch = _build(rps_detail=bytes(detail), retained_tax_records=rows)
    parts = batch.rps_bytes.split(b"\r\n")
    assert [x[:1] for x in parts[:-1]] == [b"1", b"2", b"3", b"3", b"4", b"9"]
    assert parts[-2] == (
        b"90000006" + b"000000000015000" + b"000000000001500"
    )


def test_duplicate_and_unbalanced_type3_entries_rejected() -> None:
    valid = b"301000000000001000"
    with pytest.raises(BarueriBatchBuilderError, match="duplicate"):
        _build(retained_tax_records=(valid, valid))
    with pytest.raises(BarueriBatchBuilderError, match="conflicts"):
        _build(retained_tax_records=(valid,))
    with pytest.raises(BarueriBatchBuilderError, match="code"):
        _build(retained_tax_records=(b"3XX000000000001000",))


def test_vn_is_not_federal_withholding_but_counts_in_trailer() -> None:
    vn = b"3VN000000000001000"
    detail = bytearray(_detail())
    detail[483:498] = b"000000000000000"
    batch = _build(rps_detail=bytes(detail), retained_tax_records=(vn,))
    parts = batch.rps_bytes.split(b"\r\n")
    assert parts[-2] == (
        b"90000005" + b"000000000015000" + b"000000000001000"
    )


def test_type2_withheld_without_type3_cannot_be_silently_accepted() -> None:
    detail = bytearray(_detail())
    detail[483:498] = b"000000000001000"
    with pytest.raises(BarueriBatchBuilderError, match="Type 2 withheld"):
        _build(rps_detail=bytes(detail))


def test_type2_withholding_requires_exact_federal_reconciliation_even_with_vn() -> None:
    detail = bytearray(_detail())
    detail[483:498] = b"000000000000000"
    with pytest.raises(BarueriBatchBuilderError, match="Type 2 withheld"):
        _build(
            rps_detail=bytes(detail),
            retained_tax_records=(
                b"301000000000001000",
                b"3VN000000000000500",
            ),
        )


def test_federal_withholding_cannot_exceed_original_gross_amount() -> None:
    detail = bytearray(_detail())
    detail[483:498] = b"000000000020000"
    with pytest.raises(BarueriBatchBuilderError, match="exceeds"):
        _build(
            rps_detail=bytes(detail),
            retained_tax_records=(b"301000000000020000",),
        )
