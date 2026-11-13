"""SP4 runtime opt-in client composition cannot promote WSDL labels to providers."""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from kordena_fiscal.gateway.sp4_municipal_canonical import (
    SP4_MUNICIPAL_PROVIDERS,
    Sp4CanonicalMunicipalError,
)
from kordena_fiscal.issuance.nfe_nfse import NfseGatewayClient, NfseQueryClient
from kordena_fiscal.runtime.sp4_municipal_canonical_composition import (
    Sp4ReviewedMunicipalPorts,
    build_sp4_canonical_clients,
)


def _ports() -> Sp4ReviewedMunicipalPorts:
    return Sp4ReviewedMunicipalPorts(
        load_original_rps=Mock(),
        fiscal_issuer_policy=Mock(),
        validate_prepared_rps=Mock(),
        submit_official_rps=Mock(),
        query_official_rps=Mock(),
        verify_official_invoice_xml=Mock(),
    )


def test_exact_four_provider_contracts_can_be_installed_as_reviewed_optional_clients() -> None:
    resolver = Mock()
    issue, read = build_sp4_canonical_clients(
        canonical_resolver=resolver,
        configured_municipalities={
            provider: _ports() for provider in SP4_MUNICIPAL_PROVIDERS
        },
    )
    assert set(issue) == set(read) == set(SP4_MUNICIPAL_PROVIDERS)
    assert all(isinstance(client, NfseGatewayClient) for client in issue.values())
    assert all(isinstance(client, NfseQueryClient) for client in read.values())
    with pytest.raises(TypeError):
        issue["another-provider"] = Mock()  # type: ignore[index]


def test_empty_provider_map_leaves_all_four_municipalities_disabled() -> None:
    issue, read = build_sp4_canonical_clients(
        canonical_resolver=Mock(),
        configured_municipalities={},
    )
    assert not issue
    assert not read


def test_unreviewed_candidate_never_gets_installed_in_runtime() -> None:
    with pytest.raises(Sp4CanonicalMunicipalError, match="Unknown SP4"):
        build_sp4_canonical_clients(
            canonical_resolver=Mock(),
            configured_municipalities={"generic-ginfes": _ports()},
        )


def test_missing_authenticity_verifier_for_one_city_refuses_entire_install() -> None:
    incomplete = _ports()
    object.__setattr__(incomplete, "verify_official_invoice_xml", None)
    with pytest.raises(Sp4CanonicalMunicipalError, match="proof ports"):
        build_sp4_canonical_clients(
            canonical_resolver=Mock(),
            configured_municipalities={
                "osasco-rtc-homologation": incomplete,
            },
        )
