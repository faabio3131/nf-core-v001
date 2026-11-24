"""National cancellation event is built for any issuer UF, bound to the key's UF."""
from __future__ import annotations

import importlib.util
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kordena_fiscal.domain import BrazilianJurisdiction
from kordena_fiscal.gateway.nfse_nacional_event_homologation import (
    NationalNfseEventError,
    build_signed_national_cancellation,
)

_spec = importlib.util.spec_from_file_location(
    "cancel_any_uf_wiring",
    Path(__file__).resolve().parents[1]
    / "runtime/test_nfv1_nfse_dps_builder_and_preaudit_wiring.py",
)
assert _spec and _spec.loader
_wiring = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_wiring)


def _request(municipality: str, uf: str):
    request = _wiring._request()
    document = request.document
    address = replace(
        document.issuer.address, jurisdiction=BrazilianJurisdiction(uf, municipality),
    )
    issuer = replace(
        document.issuer, address=address,
        state_registration=replace(document.issuer.state_registration, state_code=uf),
    )
    return type(request).build(replace(document, issuer=issuer))


def _key(request, municipality: str) -> str:
    # Official 50-digit layout: municipality(7) + env(1) + CNPJ marker(1) + CNPJ(14) + 27.
    return municipality + "2" + "2" + request.document.issuer.cnpj.value + "0" * 27


def _cancel(request, key: str):
    return build_signed_national_cancellation(
        request=request, key=key, reason_code="1",
        reason_description="Erro na emissao do documento fiscal",
        approval_reference="approval-12345", occurred_at=datetime.now(UTC),
        material=_wiring._certificate(),
    )


@pytest.mark.parametrize(("municipality", "uf"), [("3106200", "MG"), ("3550308", "SP")])
def test_event_is_built_for_any_issuer_uf(municipality, uf) -> None:
    request = _request(municipality, uf)
    key = _key(request, municipality)
    intent = _cancel(request, key)
    assert intent.invoice_reference == key
    assert b"<tpAmb>2</tpAmb>" in intent.signed_event_xml


def test_key_from_another_uf_is_refused() -> None:
    request = _request("3106200", "MG")
    with pytest.raises(NationalNfseEventError):
        _cancel(request, _key(request, "3550308"))
