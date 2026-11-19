"""PMB004 v4.2 binary position tests from the published January 2026 layout."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.barueri_pmb004_record_builder import (
    BarueriPmb004IssueFields,
    BarueriPmb004Recipient,
    BarueriPmb004RecordError,
    BarueriPmb004Type5Data,
    build_barueri_reviewed_issue_batch,
    build_barueri_rps_type2,
    build_barueri_rtc_type4,
    build_barueri_special_rtc_type5,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.runtime.sp4_municipal_request_factories import (
    build_barueri_pmb004_issue_remittance_factory,
)


def _original() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            tenant_id="barueri", unit_id="branch", host_namespace="nfcore",
            environment=FiscalEnvironment.HOMOLOGATION,
            correlation_id="pmb004-records",
        ),
        document_id="barueri-rps", request_fingerprint="c" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3505708",
        competence_date=date(2026, 11, 12), rps_number="42",
        rps_series="R1", gross_amount=Decimal("150.00"),
        municipal_batch_id="20261112001",
    )


def _request(source: Sp4OriginalRps) -> NfseAuthorizationRequest:
    req = Mock(spec=NfseAuthorizationRequest)
    d = req.document
    d.scope = source.scope
    d.document_id = source.document_id
    d.issuer.cnpj = source.issuer_cnpj
    d.issuer.tax_regime = TaxRegimeCode.NORMAL
    d.competence_date = source.competence_date
    d.totals.gross_amount.amount = source.gross_amount
    d.issued_at = datetime(2026, 11, 12, 9, 30, 45, tzinfo=UTC)
    d.service_jurisdiction.state_code = "SP"
    d.service_jurisdiction.municipality_ibge_code = "3505708"
    service = Mock()
    service.gross_amount.amount = source.gross_amount
    service.deduction_amount.amount = Decimal("0")
    service.description = "Servico prestado conforme contrato"
    d.services = (service,)
    req.request_fingerprint = source.request_fingerprint
    return req


def _fields() -> BarueriPmb004IssueFields:
    return BarueriPmb004IssueFields(
        service_code="010701000", service_location_code="1", public_way_code="2",
        street="Rua do Centro", street_number="55", district="Centro",
        city="Barueri", state="SP", postal_code="06401220",
        recipient=BarueriPmb004Recipient(
            tax_id="11222333000181", legal_name="Cliente Teste",
            street="Rua do Tomador", street_number="15",
            district="Jardim", city="Barueri", state="SP",
            postal_code="06401220", city_ibge="3505708",
            email="fiscal@example.com",
        ),
        nbs_code="120011000", operation_indicator="050101",
        tax_classification="000001", ibs_cbs_status="000",
    )


def test_type_2_positions_and_type_4_rtc_codes_reconcile_original() -> None:
    original = _original()
    req = _request(original)
    detail = build_barueri_rps_type2(request=req, original=original, fields=_fields())
    rtc = build_barueri_rtc_type4(request=req, original=original, fields=_fields())
    assert len(detail) == 1970
    assert len(rtc) == 531
    assert detail[:6] == b"2RPS  "
    assert detail[6:10] == b"R1  "
    assert detail[15:25] == b"0000000042"
    assert detail[25:33] == b"20261112"
    assert detail[33:39] == b"093045"
    assert detail[39:40] == b"E"
    assert detail[242:251] == b"010701000"
    assert detail[457:463] == b"000001"
    assert detail[463:478] == b"000000000015000"
    assert detail[498:499] == b"2"
    assert detail[503:504] == b"2"
    assert detail[504:518] == b"11222333000181"
    assert rtc[0:2] == b"41"
    assert rtc[6:13] == b"3505708"
    assert rtc[13:20] == b"3505708"
    assert rtc[60:69] == b"120011000"
    assert rtc[514:520] == b"050101"
    assert rtc[520:526] == b"000001"
    assert rtc[526:529] == b"000"
    assert rtc[529:531] == b"00"


def test_full_header_records_footer_and_original_remittance_id() -> None:
    original = _original()
    batch = build_barueri_reviewed_issue_batch(
        request=_request(original), original=original,
        fields=_fields(), municipal_registration="1234567",
    )
    rows = batch.rps_bytes.split(b"\r\n")
    assert len(rows) == 5  # header, RPS, RTC, footer, trailing empty
    assert rows[0] == b"11234567PMB00420261112001"
    assert rows[1][:6] == b"2RPS  "
    assert len(rows[1]) == 1970
    assert rows[2][:1] == b"4"
    assert len(rows[2]) == 531
    assert rows[3][:8] == b"90000004"


@pytest.mark.parametrize("change", [
    {"gross_amount": Decimal("149.00")},
    {"document_id": "different-invoice"},
    {"issuer_ibge": "3534401"},
])
def test_record_rejects_source_conflicts(change: dict[str, object]) -> None:
    original = _original()
    with pytest.raises(BarueriPmb004RecordError):
        build_barueri_rps_type2(
            request=_request(original), original=replace(original, **change),
            fields=_fields(),
        )


def test_ibs_cbs_cst_and_classification_must_agree() -> None:
    original = _original()
    for fields in (
        replace(_fields(), ibs_cbs_status="999"),
        replace(_fields(), nbs_code="20.01.10"),
        replace(_fields(), recipient=replace(_fields().recipient, email="")),
    ):
        with pytest.raises(BarueriPmb004RecordError):
            build_barueri_rtc_type4(
                request=_request(original), original=original, fields=fields,
            )


def test_pmb004_canonical_remittance_port_uses_reviewed_source() -> None:
    original = _original()
    factory = build_barueri_pmb004_issue_remittance_factory(
        resolve_issue_fields=lambda _req, _src: _fields(),
        resolve_municipal_registration=lambda _scope, _cnpj: "1234567",
    )
    batch = factory(_request(original), original)
    assert batch.remittance == original.municipal_batch_id
    assert batch.issuer_cnpj == original.issuer_cnpj
    assert batch.rps_bytes.split(b"\r\n")[1][15:25] == b"0000000042"


def test_reviewed_federal_taxes_generate_correlated_type2_type3_and_type9() -> None:
    original = _original()
    fields = replace(
        _fields(), federal_retentions=(
            ("01", Decimal("10.00")), ("02", Decimal("5.00")),
        ),
    )
    batch = build_barueri_reviewed_issue_batch(
        request=_request(original), original=original,
        fields=fields, municipal_registration="1234567",
    )
    parts = batch.rps_bytes.split(b"\r\n")
    assert len(parts[:-1]) == 6
    assert parts[1][483:498] == b"000000000001500"
    assert parts[2] == b"301000000000001000"
    assert parts[3] == b"302000000000000500"
    assert parts[-2][23:38] == b"000000000001500"


def test_reviewed_federal_taxes_reject_repeated_codes_and_excessive_amounts() -> None:
    original = _original()
    for taxes in (
        (("01", Decimal("1.00")), ("01", Decimal("2.00"))),
        (("XX", Decimal("1.00")),),
        (("01", Decimal("0.00")),),
        (("01", Decimal("151.00")),),
    ):
        with pytest.raises(BarueriPmb004RecordError):
            build_barueri_reviewed_issue_batch(
                request=_request(original), original=original,
                fields=replace(_fields(), federal_retentions=taxes),
                municipal_registration="1234567",
            )


def test_type5_domestic_recipient_different_from_taker_is_position_accurate() -> None:
    original = _original()
    destination = replace(
        _fields().recipient,
        tax_id="12345678901", legal_name="Destinatario Distinto",
        city="Osasco", city_ibge="3534401", state="SP",
        postal_code="06018090", email="destino@example.com",
    )
    fields = replace(
        _fields(), recipient_differs="1",
        special_rtc=BarueriPmb004Type5Data(final_recipient=destination),
    )
    rows = build_barueri_special_rtc_type5(
        request=_request(original), original=original, fields=fields,
    )
    assert len(rows) == 1
    row = rows[0]
    assert len(row) == 697
    assert row[0:1] == b"5"
    assert row[217:218] == b"2"
    assert row[218:232] == b"00012345678901"
    assert row[232:292].rstrip() == b"Destinatario Distinto"
    assert row[486:493] == b"3534401"
    assert row[493:495] == b"SP"
    assert row[498:506] == b"06018090"
    batch = build_barueri_reviewed_issue_batch(
        request=_request(original), original=original,
        fields=fields, municipal_registration="1234567",
    )
    lines = batch.rps_bytes.split(b"\r\n")
    assert lines[3] == row
    assert lines[-2][:8] == b"90000005"


def test_type5_presumed_credit_government_and_referenced_nfse() -> None:
    original = _original()
    fields = replace(
        _fields(),
        special_rtc=BarueriPmb004Type5Data(
            presumed_credit_code="01", government_entity_type="4",
            government_operation_type="2", referenced_nfse_key="1" * 50,
        ),
    )
    row = build_barueri_special_rtc_type5(
        request=_request(original), original=original, fields=fields,
    )[0]
    assert row[:5] == b"50142"
    assert row[5:55] == b"1" * 50


def test_type5_required_by_rtc_class_and_rental_activity() -> None:
    original = _original()
    for fields in (
        replace(_fields(), recipient_differs="1"),
        replace(_fields(), tax_classification="410003", ibs_cbs_status="410"),
        replace(_fields(), service_code="990401000"),
    ):
        with pytest.raises(BarueriPmb004RecordError, match="Type 5"):
            build_barueri_reviewed_issue_batch(
                request=_request(original), original=original, fields=fields,
                municipal_registration="1234567",
            )
    donation = replace(
        _fields(), tax_classification="410003", ibs_cbs_status="410",
        special_rtc=BarueriPmb004Type5Data(donation_indicator="1"),
    )
    assert build_barueri_special_rtc_type5(
        request=_request(original), original=original, fields=donation,
    )[0][216:217] == b"1"
    lease = replace(
        _fields(), service_code="990401000",
        special_rtc=BarueriPmb004Type5Data(
            rental_ncm="84713012", rental_description="Computadores portateis",
            rental_quantity=2,
        ),
    )
    row = build_barueri_special_rtc_type5(
        request=_request(original), original=original, fields=lease,
    )[0]
    assert row[55:63] == b"84713012"
    assert row[63:213].rstrip() == b"Computadores portateis"
    assert row[213:216] == b"002"


def test_reviewed_vn_deduction_reconciles_type3_and_type9_without_withholding() -> None:
    original = _original()
    request = _request(original)
    request.document.services[0].deduction_amount.amount = Decimal("10.00")
    fields = replace(_fields(), non_base_amount=Decimal("10.00"))
    batch = build_barueri_reviewed_issue_batch(
        request=request, original=original, fields=fields,
        municipal_registration="1234567",
    )
    parts = batch.rps_bytes.split(b"\r\n")
    assert [part[:1] for part in parts[:-1]] == [
        b"1", b"2", b"3", b"4", b"9",
    ]
    assert parts[1][483:498] == b"000000000000000"
    assert parts[2] == b"3VN000000000001000"
    assert parts[-2][8:23] == b"000000000015000"
    assert parts[-2][23:38] == b"000000000001000"


@pytest.mark.parametrize("reported", [
    None, Decimal("0.00"), Decimal("9.99"),
    Decimal("10.01"), Decimal("-1.00"),
])
def test_vn_requires_exact_reviewed_canonical_deduction(
    reported: Decimal | None,
) -> None:
    original = _original()
    request = _request(original)
    request.document.services[0].deduction_amount.amount = Decimal("10.00")
    with pytest.raises(BarueriPmb004RecordError):
        build_barueri_reviewed_issue_batch(
            request=request, original=original,
            fields=replace(_fields(), non_base_amount=reported),
            municipal_registration="1234567",
        )


def test_vn_cannot_be_invented_if_canonical_deduction_is_zero() -> None:
    original = _original()
    with pytest.raises(BarueriPmb004RecordError, match="no canonical"):
        build_barueri_reviewed_issue_batch(
            request=_request(original), original=original,
            fields=replace(_fields(), non_base_amount=Decimal("10.00")),
            municipal_registration="1234567",
        )


def test_federal_retention_and_vn_use_distinct_pmb004_totals() -> None:
    original = _original()
    request = _request(original)
    request.document.services[0].deduction_amount.amount = Decimal("10.00")
    fields = replace(
        _fields(), non_base_amount=Decimal("10.00"),
        federal_retentions=(("01", Decimal("2.00")),),
    )
    rows = build_barueri_reviewed_issue_batch(
        request=request, original=original,
        fields=fields, municipal_registration="1234567",
    ).rps_bytes.split(b"\r\n")
    assert rows[1][483:498] == b"000000000000200"
    assert rows[2] == b"301000000000000200"
    assert rows[3] == b"3VN000000000001000"
    assert rows[-2][23:38] == b"000000000001200"
