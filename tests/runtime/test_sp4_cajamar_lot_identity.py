"""Cajamar GeisWeb query needs an immutable lot identifier before any I/O."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.cajamar_geisweb_homologation import (
    CajamarGeiswebHomologationTransport,
    CajamarGeiswebResult,
    CajamarPreparedNfse,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
    Sp4ProviderOutcome,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.runtime.sp4_municipal_provider_bridges import (
    Sp4BridgeAuthority,
    build_cajamar_reviewed_ports,
)


def _original() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            tenant_id="cajamar", unit_id="branch", host_namespace="nfcore",
            environment=FiscalEnvironment.HOMOLOGATION,
            correlation_id="lot-test",
        ),
        document_id="prepared-rps", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3509205",
        competence_date=date(2026, 11, 13), rps_number="42",
        rps_series="NF", gross_amount=Decimal("150.00"),
        municipal_batch_id="12345",
    )


def _setup(lot_in_xml: str = "12345"):
    original = _original()
    request = Mock(spec=NfseAuthorizationRequest)
    request.document.scope = original.scope
    request.document.issuer.tax_regime = TaxRegimeCode.NORMAL
    request.document.services = (object(),)
    transport = Mock(spec=CajamarGeiswebHomologationTransport)
    transport.invoke.return_value = CajamarGeiswebResult(
        method="ConsultaLoteRps", response_xml=b"",
    )
    def build(req, source, method):
        xml = (
            f"<{method}><CnpjCpf>11222333000181</CnpjCpf>"
            f"<Consulta><NumeroLote>{lot_in_xml}</NumeroLote></Consulta>"
            f"</{method}>"
        ).encode()
        return CajamarPreparedNfse(
            scope=source.scope, issuer_cnpj=source.issuer_cnpj,
            tax_regime=TaxRegimeCode.NORMAL,
            competence_date=source.competence_date,
            method=method, signed_request_xml=xml,
        )

    ports = build_cajamar_reviewed_ports(
        authority=Sp4BridgeAuthority(
            load_original_rps=Mock(), fiscal_issuer_policy=Mock(),
            validate_prepared_rps=Mock(), verify_official_invoice_xml=Mock(),
        ),
        transport=transport, build_signed_operation=build,
        verify_signed_rps_identity=Mock(),
        interpret_official_result=Mock(
            return_value=Sp4ProviderOutcome(status=AuthorizationStatus.PENDING),
        ),
    )
    return ports, transport.invoke, request, original


def test_original_lot_number_is_reused_for_safe_read_only_recovery() -> None:
    ports, invoke, request, original = _setup()
    result = ports.query_official_rps(request, original)
    assert result.status is AuthorizationStatus.PENDING
    assert invoke.call_count == 1
    assert invoke.call_args.args[0].method == "ConsultaLoteRps"


@pytest.mark.parametrize("change", [
    {"municipal_batch_id": "12346"},
    {"municipal_batch_id": None},
])
def test_lost_original_lot_cannot_submit_or_query(
    change: dict[str, object],
) -> None:
    ports, invoke, request, original = _setup()
    with pytest.raises(Sp4CanonicalMunicipalError, match="lot|batch"):
        ports.query_official_rps(request, replace(original, **change))
    invoke.assert_not_called()


def test_wrong_lot_identifier_in_signed_xml_never_reaches_transport() -> None:
    ports, invoke, request, original = _setup("12346")
    with pytest.raises(Sp4CanonicalMunicipalError, match="lot XML differs"):
        ports.submit_official_rps(request, original)
    invoke.assert_not_called()


def test_invalid_municipal_batch_id_cannot_be_persisted() -> None:
    with pytest.raises(Sp4CanonicalMunicipalError, match="batch ID"):
        replace(_original(), municipal_batch_id="../other-tenant")
