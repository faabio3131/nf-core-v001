"""GissOnline 2.04 exact source lot/RPS correlation, offline only."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.jundiai_giss_homologation import (
    JundiaiGissHomologationTransport,
    JundiaiGissReceipt,
    JundiaiSignedOperation,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.runtime.sp4_municipal_provider_bridges import (
    Sp4BridgeAuthority,
    build_jundiai_reviewed_ports,
)


def _original() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="jundiai", unit_id="u",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="giss-rps",
        ),
        document_id="prepared", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3525904",
        competence_date=date(2026, 11, 13),
        rps_number="42", rps_series="NF", gross_amount=Decimal("150.00"),
        municipal_batch_id="1234",
    )


def _operation(
    source: Sp4OriginalRps, method: str, *,
    number: str = "42", series: str = "NF", lot: str = "1234",
) -> JundiaiSignedOperation:
    sending = method == "RecepcionarLoteRps"
    root = "EnviarLoteRpsEnvio" if sending else "ConsultarNfseRpsEnvio"
    service = "enviar-lote-rps-envio" if sending else "consultar-nfse-rps-envio"
    lot_tag = f"<t:NumeroLote>{lot}</t:NumeroLote>" if sending else ""
    identifier_prefix = "t" if sending else "g"
    signed = (
        f'<g:{root} xmlns:g="http://www.giss.com.br/{service}-v2_04.xsd" '
        'xmlns:t="http://www.giss.com.br/tipos-v2_04.xsd">'
        f"{lot_tag}"
        f'<{identifier_prefix}:IdentificacaoRps><t:Numero>{number}</t:Numero>'
        f'<t:Serie>{series}</t:Serie>'
        f'</{identifier_prefix}:IdentificacaoRps>'
        f'</g:{root}>'
    ).encode()
    return JundiaiSignedOperation(
        scope=source.scope, issuer_cnpj=source.issuer_cnpj,
        tax_regime=TaxRegimeCode.NORMAL, competence_date=source.competence_date,
        method=method, signed_xml=signed,
    )


def _setup(*, number: str = "42", series: str = "NF", lot: str = "1234"):
    original = _original()
    request = Mock(spec=NfseAuthorizationRequest)
    request.document.scope = original.scope
    request.document.issuer.tax_regime = TaxRegimeCode.NORMAL
    transport = Mock(spec=JundiaiGissHomologationTransport)
    transport.invoke.side_effect = lambda op: JundiaiGissReceipt(
        method=op.method, batch_protocol="12345" if op.method == "RecepcionarLoteRps" else None,
        batch_state=4 if op.method == "RecepcionarLoteRps" else None,
        authorized=False, official_response_xml=b"",
    )
    ports = build_jundiai_reviewed_ports(
        authority=Sp4BridgeAuthority(
            load_original_rps=Mock(), fiscal_issuer_policy=Mock(),
            validate_prepared_rps=Mock(), verify_official_invoice_xml=Mock(),
        ),
        transport=transport,
        build_signed_operation=lambda r, src, method: _operation(
            src, method, number=number, series=series, lot=lot,
        ),
        verify_signed_rps_identity=Mock(),
    )
    return ports, transport.invoke, request, original


def test_original_lot_and_rps_are_preserved_during_submission() -> None:
    ports, invoke, request, original = _setup()
    result = ports.submit_official_rps(request, original)
    assert result.status is AuthorizationStatus.PENDING
    assert result.provider_request_id == "12345"
    invoke.assert_called_once()


def test_query_by_exact_original_rps_never_resends_a_batch() -> None:
    ports, invoke, request, original = _setup()
    result = ports.query_official_rps(request, original)
    assert result.status is AuthorizationStatus.PENDING
    assert invoke.call_count == 1
    assert invoke.call_args.args[0].method == "ConsultarNfsePorRps"


@pytest.mark.parametrize("alter", [
    {"number": "43"}, {"series": "NO"}, {"lot": "1235"},
])
def test_mismatched_signed_identity_denied_before_http(alter: dict[str, str]) -> None:
    ports, invoke, request, original = _setup(**alter)
    with pytest.raises(Sp4CanonicalMunicipalError, match="original RPS|persisted lot"):
        ports.submit_official_rps(request, original)
    invoke.assert_not_called()


def test_unreserved_jundiai_lot_blocks_mutating_submission() -> None:
    ports, invoke, request, original = _setup()
    with pytest.raises(Sp4CanonicalMunicipalError, match="persisted lot"):
        ports.submit_official_rps(request, replace(original, municipal_batch_id=None))
    invoke.assert_not_called()
