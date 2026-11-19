"""Barueri PMB004: asynchronous remittance is never a fiscal authorization.

No live municipal endpoint or taxpayer certificate is contacted.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import (
    Cnpj,
    ExecutionScope,
    FiscalEnvironment,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.barueri_official_return_file import (
    BarueriConvertedNfseEvidence,
)
from kordena_fiscal.gateway.barueri_pmb004_homologation import (
    BarueriContractError,
    BarueriListedFile,
    BarueriPmb004HomologationTransport,
    BarueriReceipt,
    BarueriRpsBatch,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
    Sp4ProviderOutcome,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.runtime.sp4_municipal_provider_bridges import (
    Sp4BridgeAuthority,
    build_barueri_reviewed_ports,
)


def _scope() -> ExecutionScope:
    return ExecutionScope(
        host_namespace="nfcore", tenant_id="tenant-a", unit_id="unit-b",
        environment=FiscalEnvironment.HOMOLOGATION, correlation_id="barueri-async",
    )


def _rps() -> bytes:
    rec2 = bytearray(b"2RPS  " + b" " * (1970 - 6))
    rec2[15:25] = b"0000000042"
    rec2[25:33] = b"20261113"
    rec2[33:39] = b"120000"
    rec2[39:40] = b"E"
    rec2[457:463] = b"000001"
    rec2[463:478] = b"000000000015000"
    return b"\r\n".join((
        b"11234567PMB00420261113001",
        bytes(rec2),
        b"41" + b" " * 529,
        b"90000004" + b"000000000015000" + b"0" * 15,
    )) + b"\r\n"


def _setup(
    retrieve_xml: Mock | None = None,
    *,
    protocol: str | None = "PROTOCOL42",
    submitted_on: date | None = None,
    rps_action: str = "E",
) -> tuple[object, Mock, Mock, Mock, NfseAuthorizationRequest, Sp4OriginalRps]:
    scope = _scope()
    original = Sp4OriginalRps(
        scope=scope, document_id="original", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3505708",
        competence_date=date(2026, 11, 13), rps_number="42",
        rps_series="NF", gross_amount=Decimal("150.00"),
        municipal_batch_id="20261113001",
    )
    request = Mock(spec=NfseAuthorizationRequest)
    request.document.scope = scope
    request.document.document_id = "original"
    request.document.issuer.tax_regime = TaxRegimeCode.NORMAL
    rps_content = bytearray(_rps())
    rps_content[27 + 39] = ord(rps_action)
    if rps_action == "C":
        # Official Jan/2026 PMB004: cancellation uses ZERO RPS number,
        # an explicit reason and the number/date of the original invoice.
        rps_content[27 + 15:27 + 25] = b"0000000000"
        rps_content[27 + 40:27 + 42] = b"01"
        rps_content[27 + 42:27 + 49] = b"0008765"
        rps_content[27 + 54:27 + 62] = b"20261113"
        rps_content[27 + 62:27 + 242] = b"Cancelamento de teste".ljust(180)
    batch = BarueriRpsBatch(
        scope=scope, issuer_cnpj=original.issuer_cnpj,
        municipal_registration="1234567", tax_regime=TaxRegimeCode.NORMAL,
        competence_date=original.competence_date,
        remittance="20261113001", file_name="20261113001.txt",
        rps_bytes=bytes(rps_content),
    )
    transport = BarueriPmb004HomologationTransport(
        provider_resolver=Mock(), resolve_certificate=Mock(),
        validate_pmb004=Mock(), exchange=Mock(),
    )
    submit = Mock(return_value=BarueriReceipt(
        operation="NFeLoteEnviarArquivo", code="OK200",
        remittance_protocol="PROTOCOL42",
    ))
    status = Mock(return_value=BarueriReceipt(
        operation="NFeLoteStatusArquivo", code="OK200",
        remittance_protocol="PROTOCOL42",
    ))
    download = Mock(return_value=BarueriReceipt(
        operation="NFeLoteBaixarArquivo", code="OK200",
        remittance_protocol="PROTOCOL42",
        return_file_name="result.txt", downloaded_file=b"municipal-return",
    ))
    transport.submit = submit  # type: ignore[method-assign]
    transport.status = status  # type: ignore[method-assign]
    transport.download = download  # type: ignore[method-assign]
    def list_files(*, batch, situation, submitted_on):
        assert batch.remittance == "20261113001"
        assert submitted_on == date(2026, 11, 13)
        files = (
            (BarueriListedFile(
                original_file_name="20261113001.txt",
                remittance="20261113001", situation="1",
                return_file_name="result.txt", validation_only=False,
            ),) if situation == "1" else ()
        )
        return BarueriReceipt(
            operation="NFeLoteListarArquivos", code="OK200", listed_files=files,
        )
    transport.list_on_date = Mock(side_effect=list_files)  # type: ignore[method-assign]
    interpreter = Mock(return_value=Sp4ProviderOutcome(status=AuthorizationStatus.PENDING))
    authority = Sp4BridgeAuthority(
        load_original_rps=Mock(), fiscal_issuer_policy=Mock(),
        validate_prepared_rps=Mock(), verify_official_invoice_xml=Mock(),
    )
    ports = build_barueri_reviewed_ports(
        authority=authority, transport=transport,
        build_remittance=Mock(return_value=batch),
        verify_fixed_width_rps_identity=Mock(),
        load_approved_remittance_protocol=Mock(return_value=protocol),
        load_original_submission_date=Mock(return_value=submitted_on),
        interpret_official_result=interpreter,
        retrieve_official_invoice_xml=retrieve_xml,
        validate_return_file=Mock(return_value=BarueriConvertedNfseEvidence(
            remittance="20261113001", note_number="0008765", note_series="NF",
            verification_code="VERIFIER", access_key="35" + "0" * 48,
            rps_number="0000000042", rps_series="NF",
            service_total=Decimal("150.00"), return_file=b"municipal-return",
        )),
    )
    return ports, submit, status, download, request, original


def test_async_send_only_yields_pending_even_if_interpreter_would_authorize() -> None:
    ports, submit, status, download, request, original = _setup()
    result = ports.submit_official_rps(request, original)
    assert result.status is AuthorizationStatus.PENDING
    assert result.provider_request_id == "PROTOCOL42"
    submit.assert_called_once()
    status.assert_not_called()
    download.assert_not_called()


def test_status_without_return_file_remains_pending_and_never_downloads() -> None:
    ports, submit, status, download, request, original = _setup()
    result = ports.query_official_rps(request, original)
    assert result.status is AuthorizationStatus.PENDING
    assert result.provider_request_id == "PROTOCOL42"
    submit.assert_not_called()
    status.assert_called_once()
    download.assert_not_called()


def test_status_protocol_mismatch_is_rejected_without_return_download() -> None:
    ports, submit, status, download, request, original = _setup()
    status.return_value = BarueriReceipt(
        operation="NFeLoteStatusArquivo", code="OK200",
        remittance_protocol="ANOTHERPROTOCOL", return_file_name="result.txt",
    )
    with pytest.raises(Sp4CanonicalMunicipalError, match="original remittance"):
        ports.query_official_rps(request, original)
    submit.assert_not_called()
    download.assert_not_called()


def test_only_correlated_provider_return_file_reaches_invoice_interpreter() -> None:
    ports, submit, status, download, request, original = _setup()
    status.return_value = BarueriReceipt(
        operation="NFeLoteStatusArquivo", code="OK200",
        remittance_protocol="PROTOCOL42", return_file_name="result.txt",
    )
    result = ports.query_official_rps(request, original)
    assert result.status is AuthorizationStatus.PENDING
    submit.assert_not_called()
    download.assert_called_once()


def test_empty_return_file_never_promotes_fiscal_note() -> None:
    ports, submit, status, download, request, original = _setup()
    status.return_value = BarueriReceipt(
        operation="NFeLoteStatusArquivo", code="OK200",
        remittance_protocol="PROTOCOL42", return_file_name="result.txt",
    )
    download.return_value = BarueriReceipt(
        operation="NFeLoteBaixarArquivo", code="OK200",
        downloaded_file=None, return_file_name="result.txt",
    )
    with pytest.raises(Sp4CanonicalMunicipalError, match="cannot be correlated"):
        ports.query_official_rps(request, original)
    submit.assert_not_called()


def test_unrelated_download_file_cannot_pass_current_layout_verifier() -> None:
    ports, submit, status, download, request, original = _setup()
    status.return_value = BarueriReceipt(
        operation="NFeLoteStatusArquivo", code="OK200",
        remittance_protocol="PROTOCOL42", return_file_name="result.txt",
    )
    download.return_value = BarueriReceipt(
        operation="NFeLoteBaixarArquivo", code="OK200",
        remittance_protocol="PROTOCOL42", return_file_name="result.txt",
        downloaded_file=b"different-physical-return",
    )
    with pytest.raises(Sp4CanonicalMunicipalError, match="original RPS"):
        ports.query_official_rps(request, original)
    submit.assert_not_called()


def test_unpersisted_remittance_prevents_mutating_barueri_http() -> None:
    from dataclasses import replace

    ports, submit, status, download, request, original = _setup()
    with pytest.raises(Sp4CanonicalMunicipalError, match="remittance conflicts"):
        ports.submit_official_rps(
            request, replace(original, municipal_batch_id="20261113002"),
        )
    submit.assert_not_called()
    status.assert_not_called()
    download.assert_not_called()


def test_barueri_invoice_requires_downloaded_original_xml_and_approved_validator() -> None:
    retrieve = Mock(return_value=b"<CompNfse>OFFLINE-UNVERIFIED</CompNfse>")
    ports, submit, status, download, request, original = _setup(retrieve)
    status.return_value = BarueriReceipt(
        operation="NFeLoteStatusArquivo", code="OK200",
        remittance_protocol="PROTOCOL42", return_file_name="result.txt",
    )
    candidate = ports.query_official_rps(request, original)
    assert candidate.status is AuthorizationStatus.AUTHORIZED
    assert candidate.official_invoice is not None
    assert candidate.official_invoice.invoice_reference == "35" + "0" * 48
    assert candidate.official_invoice.authorized_xml == retrieve.return_value
    retrieve.assert_called_once()
    submit.assert_not_called()


def test_barueri_xml_unavailable_keeps_previous_remittance_unresolved() -> None:
    retrieve = Mock(return_value=b"")
    ports, submit, status, download, request, original = _setup(retrieve)
    status.return_value = BarueriReceipt(
        operation="NFeLoteStatusArquivo", code="OK200",
        remittance_protocol="PROTOCOL42", return_file_name="result.txt",
    )
    with pytest.raises(Sp4CanonicalMunicipalError, match="XML is missing"):
        ports.query_official_rps(request, original)
    submit.assert_not_called()


def test_ambiguous_barueri_post_is_recovered_by_read_only_listing() -> None:
    ports, submit, status, download, request, original = _setup(
        protocol=None, submitted_on=date(2026, 11, 13),
    )
    outcome = ports.query_official_rps(request, original)
    assert outcome.status is AuthorizationStatus.PENDING
    submit.assert_not_called()
    status.assert_not_called()
    download.assert_called_once()
    assert download.call_args.kwargs["file_name"] == "result.txt"


def test_unrecoverable_post_without_original_sent_date_never_retransmits() -> None:
    ports, submit, status, download, request, original = _setup(
        protocol=None, submitted_on=None,
    )
    assert ports.query_official_rps(request, original).status is AuthorizationStatus.PENDING
    submit.assert_not_called()
    status.assert_not_called()
    download.assert_not_called()


def test_listing_parser_rejects_duplicate_fiscal_origin() -> None:
    with pytest.raises(BarueriContractError):
        BarueriListedFile(
            original_file_name="../other.txt", remittance="20261113001",
            situation="1", return_file_name="result.txt",
            validation_only=False,
        )


@pytest.mark.parametrize("action", ["C", "R"])
def test_issuance_bridge_never_sends_cancel_or_substitution_without_approval(
    action: str,
) -> None:
    ports, submit, status, download, request, original = _setup(rps_action=action)
    with pytest.raises(Sp4CanonicalMunicipalError, match="cancellation or substitution"):
        ports.submit_official_rps(request, original)
    submit.assert_not_called()
    status.assert_not_called()
    download.assert_not_called()
