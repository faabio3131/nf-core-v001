"""Osasco 2026 RTC: emission receipt is not immutable fiscal authorization."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.osasco_rtc_homologation import (
    OsascoNoteReference,
    OsascoOperationReceipt,
    OsascoPreparedOperation,
    OsascoRtcHomologationTransport,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
    Sp4ProviderOutcome,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.runtime.sp4_municipal_provider_bridges import (
    Sp4BridgeAuthority,
    build_osasco_reviewed_ports,
)


def _original() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="osasco", unit_id="u",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="rtc",
        ),
        document_id="prepared", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3534401",
        competence_date=date(2026, 11, 13), rps_number="42",
        rps_series="A", gross_amount=Decimal("150.00"),
    )


def _prepared(original: Sp4OriginalRps, method: str) -> OsascoPreparedOperation:
    pre = "http://schemas.datacontract.org/2004/07/"
    dto = (
        pre + "Eissnfe.Dominio.DataTransferObject.Prestador"
        if method == "RTC_EmitirNFE"
        else pre + "Eissnfe.Negocio.WebServices.Mensagem"
    )
    name = "NumeroRecibo" if method == "RTC_EmitirNFE" else "NumeroReciboUnico"
    xml = (
        f'<tem:{method} xmlns:tem="http://tempuri.org/" '
        f'xmlns:m="{dto}"><tem:request>'
        f"<m:{name}>42</m:{name}>"
        f"</tem:request></tem:{method}>"
    ).encode()
    return OsascoPreparedOperation(
        scope=original.scope, issuer_cnpj=original.issuer_cnpj,
        tax_regime=TaxRegimeCode.NORMAL,
        competence_date=original.competence_date, method=method, request_xml=xml,
    )


def _ports() -> tuple[object, Mock, Mock, Mock, Sp4OriginalRps]:
    original = _original()
    request = Mock(spec=NfseAuthorizationRequest)
    request.document.scope = original.scope
    request.document.issuer.tax_regime = TaxRegimeCode.NORMAL
    operation = Mock(spec=OsascoRtcHomologationTransport)
    operation.invoke.return_value = OsascoOperationReceipt(
        method="RTC_EmitirNFE", fiscal_error=False,
        note_reference=OsascoNoteReference(
            number="765", authenticator="GOOD123", identifier="NOTA123",
        ),
        response_xml=b"<accepted/>",
    )
    interpreter = Mock(
        return_value=Sp4ProviderOutcome(status=AuthorizationStatus.PENDING),
    )
    authority = Sp4BridgeAuthority(
        load_original_rps=Mock(), fiscal_issuer_policy=Mock(),
        validate_prepared_rps=Mock(), verify_official_invoice_xml=Mock(),
    )
    ports = build_osasco_reviewed_ports(
        authority=authority, transport=operation,
        build_wcf_operation=lambda req, src, method: _prepared(src, method),
        verify_wcf_rps_identity=Mock(), interpret_official_result=interpreter,
    )
    return ports, operation.invoke, interpreter, request, original


def test_sync_note_generated_is_pending_until_verified_full_invoice() -> None:
    ports, invoke, interpreter, request, original = _ports()
    outcome = ports.submit_official_rps(request, original)
    assert outcome.status is AuthorizationStatus.PENDING
    assert outcome.provider_request_id == "765"
    invoke.assert_called_once()
    interpreter.assert_not_called()


def test_osasco_full_invoice_query_uses_read_only_source_receipt() -> None:
    ports, invoke, interpreter, request, original = _ports()
    invoke.return_value = OsascoOperationReceipt(
        method="ConsultarNotaCompleta", fiscal_error=False,
        status_available=False, response_xml=b"<official-full-invoice/>",
    )
    outcome = ports.query_official_rps(request, original)
    assert outcome.status is AuthorizationStatus.PENDING
    assert invoke.call_count == 1
    assert invoke.call_args.args[0].method == "ConsultarNotaCompleta"
    interpreter.assert_called_once()


def test_missing_full_note_does_not_invoke_authorization_interpreter() -> None:
    ports, invoke, interpreter, request, original = _ports()
    invoke.return_value = OsascoOperationReceipt(
        method="ConsultarNotaCompleta", fiscal_error=False,
        status_available=False, response_xml=b"",
    )
    assert ports.query_official_rps(request, original).status is AuthorizationStatus.PENDING
    interpreter.assert_not_called()


def test_wcf_reply_for_wrong_method_is_rejected() -> None:
    ports, invoke, interpreter, request, original = _ports()
    invoke.return_value = OsascoOperationReceipt(
        method="RTC_EmitirNFE", fiscal_error=False,
        response_xml=b"<unrelated/>",
    )
    with pytest.raises(Sp4CanonicalMunicipalError, match="unexpected official operation"):
        ports.query_official_rps(request, original)
    interpreter.assert_not_called()
