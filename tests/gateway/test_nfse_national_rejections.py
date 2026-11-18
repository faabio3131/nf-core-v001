"""SEFIN rejection normalization: never truncate official error evidence."""
from __future__ import annotations

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.gateway.nfse_national_homologation import (
    OfficialNfseTransportError,
    parse_national_nfse_rejections,
)


def test_sefin_preserves_all_error_codes_and_long_raw_messages() -> None:
    long_message = "Falha detalhada: " + ("campo fiscal; " * 85)
    errors = parse_national_nfse_rejections({
        "erros": [
            {"Codigo": "E001", "Descricao": long_message},
            {"codigo": 1902, "descricao": "Segunda falha"},
        ],
    })
    assert len(errors) == 2
    assert errors[0].code == "E001"
    assert errors[0].origin == "SEFIN_NACIONAL"
    assert errors[0].raw_message == long_message
    assert len(errors[0].raw_message) > 512
    assert errors[1].code == "1902"
    assert errors[1].raw_message == "Segunda falha"


def test_no_rejection_entries_is_not_equivalent_to_authorization() -> None:
    assert parse_national_nfse_rejections({"status": "processing"}) == ()


@pytest.mark.parametrize("value", [
    {"erros": []},
    {"erros": "erro"},
    {"erros": [{"Codigo": "X"}]},
    {"erros": [{"Descricao": "X"}]},
    {"erros": [None]},
    {"erros": [{"Codigo": True, "Descricao": "invalida"}]},
    {"erros": [{"Codigo": "X", "Descricao": "x"}] * 33},
])
def test_malformed_sefin_rejections_fail_closed(value: object) -> None:
    with pytest.raises(OfficialNfseTransportError):
        parse_national_nfse_rejections(value)


def test_oversized_sefin_rejection_fails_without_silent_truncation() -> None:
    with pytest.raises(FiscalValidationError, match="32768"):
        parse_national_nfse_rejections({
            "erros": [{"Codigo": "X", "Descricao": "x" * 32769}],
        })
