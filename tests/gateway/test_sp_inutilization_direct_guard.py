"""Direct SEFAZ-SP gateway must enforce November 2026 negative operation policy.

The provider/registry guard cannot be the only protective boundary because a
direct fiscal operations gateway is also used by runtime composition.
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import (
    ElectronicInvoiceModel,
    ExecutionScope,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.gateway.nfe_sp_operations_homologation import (
    SefazSpHomologationOperationsGateway,
)
from kordena_fiscal.operations import InutilizationRequest


def test_direct_sp_gateway_denies_inutilization_before_a1_or_transport() -> None:
    certificate = Mock(side_effect=AssertionError("Must not open the A1 vault"))
    issuer = Mock(side_effect=AssertionError("Must not load issuer"))
    exchange = Mock(side_effect=AssertionError("Must not transmit to SEFAZ"))
    adapter = SefazSpHomologationOperationsGateway(
        resolve_certificate=certificate, resolve_issuer=issuer, exchange=exchange,
    )
    scope = ExecutionScope(
        tenant_id="test-sp", unit_id="unit-sp",
        environment=FiscalEnvironment.HOMOLOGATION, correlation_id="test-sp-direct",
    )
    request = InutilizationRequest.build(
        scope=scope, model=ElectronicInvoiceModel.NFE,
        series=1, first_number=50, last_number=51,
        justification="Justificativa exclusivamente sintetica para teste.",
    )
    with pytest.raises(FiscalValidationError, match="SP NF-e/NFC-e inutilization"):
        adapter.inutilize(request)
    issuer.assert_not_called()
    certificate.assert_not_called()
    exchange.assert_not_called()
