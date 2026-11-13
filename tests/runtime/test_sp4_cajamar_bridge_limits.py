"""GeisWeb20 permits only one service per note and 8-digit RPS maximum."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment
from kordena_fiscal.gateway.cajamar_geisweb_homologation import (
    CajamarGeiswebHomologationTransport,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.runtime.sp4_municipal_provider_bridges import (
    Sp4BridgeAuthority,
    build_cajamar_reviewed_ports,
)


def _original(number: str = "42") -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="pilot-cajamar", unit_id="unit",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="cajamar",
        ),
        document_id="prepared", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3509205",
        competence_date=date(2026, 11, 13), rps_number=number,
        rps_series="NF", gross_amount=Decimal("150.00"),
    )


@pytest.mark.parametrize("services,rps_number", [
    ((), "42"),
    ((object(), object()), "42"),
    ((object(),), "123456789"),
    ((object(),), "0"),
    ((object(),), "-1"),
])
def test_cajamar_rejects_noncanonical_service_count_and_rps_before_transport(
    services: tuple[object, ...], rps_number: str,
) -> None:
    request = Mock(spec=NfseAuthorizationRequest)
    request.document.services = services
    authority = Sp4BridgeAuthority(
        load_original_rps=Mock(),
        fiscal_issuer_policy=Mock(),
        validate_prepared_rps=Mock(),
        verify_official_invoice_xml=Mock(),
    )
    builder, identity, interpreter = Mock(), Mock(), Mock()
    transport = Mock(spec=CajamarGeiswebHomologationTransport)
    ports = build_cajamar_reviewed_ports(
        authority=authority, transport=transport,
        build_signed_operation=builder,
        verify_signed_rps_identity=identity,
        interpret_official_result=interpreter,
    )
    with pytest.raises(Sp4CanonicalMunicipalError, match="one service"):
        ports.submit_official_rps(request, _original(rps_number))
    builder.assert_not_called()
    identity.assert_not_called()
    transport.invoke.assert_not_called()
    interpreter.assert_not_called()
