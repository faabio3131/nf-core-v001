"""Real fiscal handler composition consumes the same reviewed SP4 ports.

No Prefeitura network, certificate or production migration is performed.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    SP4_MUNICIPAL_PROVIDERS,
    Sp4CanonicalMunicipalError,
)
from kordena_fiscal.issuance.nfe_nfse import NfseGatewayClient
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.runtime.canonical_fiscal_composition import (
    build_runtime_fiscal_handler_factory,
)
from kordena_fiscal.runtime.sp4_municipal_canonical_composition import (
    Sp4ReviewedMunicipalPorts,
)


def _reviewed() -> Sp4ReviewedMunicipalPorts:
    return Sp4ReviewedMunicipalPorts(
        load_original_rps=Mock(),
        fiscal_issuer_policy=Mock(),
        validate_prepared_rps=Mock(),
        submit_official_rps=Mock(),
        query_official_rps=Mock(),
        verify_official_invoice_xml=Mock(),
    )


def _application(tmp_path: Path) -> FiscalApplicationService:
    db = SqliteFiscalDatabase(tmp_path / "sp4-composition.sqlite")
    db.initialize()
    return FiscalApplicationService(db)


def test_all_four_reviewed_city_ports_install_into_canonical_handler_factory(
    tmp_path: Path,
) -> None:
    factory = build_runtime_fiscal_handler_factory(
        sp4_reviewed_municipalities={
            provider: _reviewed() for provider in SP4_MUNICIPAL_PROVIDERS
        },
        nfse_preaudit=Mock(),
    )
    handlers = factory(_application(tmp_path))
    assert {
        "issueFiscalDocument", "queryFiscalDocument",
        "cancelFiscalDocument", "reconcileFiscalOperation",
    }.issubset(handlers)


def test_unknown_city_cannot_enter_real_handler_factory(tmp_path: Path) -> None:
    factory = build_runtime_fiscal_handler_factory(
        sp4_reviewed_municipalities={"fake-global-provider": _reviewed()},
        nfse_preaudit=Mock(),
    )
    with pytest.raises(Sp4CanonicalMunicipalError, match="Unknown SP4"):
        factory(_application(tmp_path))


def test_handler_factory_refuses_two_municipal_provider_authorities() -> None:
    with pytest.raises(ValueError, match="cannot coexist"):
        build_runtime_fiscal_handler_factory(
            sp4_reviewed_municipalities={"osasco-rtc-homologation": _reviewed()},
            nfse_gateway=Mock(spec=NfseGatewayClient),
            nfse_preaudit=Mock(),
        )


def test_no_reviewed_municipal_provider_does_not_enable_cities_implicitly(
    tmp_path: Path,
) -> None:
    factory = build_runtime_fiscal_handler_factory(
        sp4_reviewed_municipalities={},
    )
    handlers = factory(_application(tmp_path))
    assert "issueFiscalDocument" in handlers
    assert "reconcileFiscalOperation" in handlers
