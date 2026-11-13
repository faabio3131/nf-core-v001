"""Jundiai GissOnline 2.04 municipal invoice proof is never inferred from lot status."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.jundiai_giss_homologation import JundiaiGissReceipt
from kordena_fiscal.gateway.jundiai_giss_invoice_interpreter import (
    interpret_jundiai_giss_result,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest

_CNPJ = "11222333000181"
_NS = "http://www.giss.com.br/consultar-nfse-rps-resposta-v2_04.xsd"
_T = "http://www.giss.com.br/tipos-v2_04.xsd"


def _original() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="jundiai-pilot", unit_id="unit-1",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="rps-lookup",
        ),
        document_id="prepared-rps42", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj(_CNPJ), issuer_ibge="3525904",
        competence_date=date(2026, 11, 13), rps_number="42",
        rps_series="NF", gross_amount=Decimal("150.00"),
    )


def _official(*, cnpj: str = _CNPJ, ibge: str = "3525904", amount: str = "150.00",
              number: str = "42") -> bytes:
    return (
        f'<ConsultarNfseRpsResposta xmlns="{_NS}" xmlns:t="{_T}">'
        '<t:CompNfse><t:Nfse><t:InfNfse>'
        '<t:Numero>8765</t:Numero><t:CodigoVerificacao>ABCD1234</t:CodigoVerificacao>'
        f'<t:OrgaoGerador><t:CodigoMunicipio>{ibge}</t:CodigoMunicipio></t:OrgaoGerador>'
        '<t:PrestadorServico><t:IdentificacaoPrestador><t:CpfCnpj>'
        f'<t:Cnpj>{cnpj}</t:Cnpj>'
        '</t:CpfCnpj></t:IdentificacaoPrestador></t:PrestadorServico>'
        '<t:DeclaracaoPrestacaoServico><t:InfDeclaracaoPrestacaoServico>'
        '<t:Rps><t:IdentificacaoRps>'
        f'<t:Numero>{number}</t:Numero><t:Serie>NF</t:Serie>'
        '</t:IdentificacaoRps></t:Rps><t:Competencia>2026-11-13</t:Competencia>'
        '<t:Prestador><t:CpfCnpj>'
        f'<t:Cnpj>{cnpj}</t:Cnpj>'
        '</t:CpfCnpj></t:Prestador>'
        '<t:Servico><t:Valores>'
        f'<t:ValorServicos>{amount}</t:ValorServicos>'
        '</t:Valores></t:Servico>'
        '</t:InfDeclaracaoPrestacaoServico></t:DeclaracaoPrestacaoServico>'
        '</t:InfNfse></t:Nfse></t:CompNfse></ConsultarNfseRpsResposta>'
    ).encode()


def _receipt(method: str, xml: bytes = b"", state: int | None = None):
    return JundiaiGissReceipt(
        method=method, batch_protocol="90045",
        batch_state=state, authorized=state == 4,
        official_response_xml=xml,
    )


def test_matching_giss_official_rps_lookup_produces_candidate_for_further_verification() -> None:
    result = interpret_jundiai_giss_result(
        _receipt("ConsultarNfsePorRps", _official()),
        Mock(spec=NfseAuthorizationRequest), _original(),
    )
    assert result.status is AuthorizationStatus.AUTHORIZED
    assert result.official_invoice is not None
    assert result.official_invoice.invoice_reference == "8765"
    assert result.official_invoice.rps_series == "NF"
    assert result.official_invoice.authorized_xml == _official()


@pytest.mark.parametrize("field", [
    {"cnpj": "00944029000121"}, {"ibge": "3505708"},
    {"amount": "150.01"}, {"number": "43"},
])
def test_unrelated_giss_official_invoice_is_never_accepted(
    field: dict[str, str],
) -> None:
    with pytest.raises(Sp4CanonicalMunicipalError, match="differs from original"):
        interpret_jundiai_giss_result(
            _receipt("ConsultarNfsePorRps", _official(**field)),
            Mock(spec=NfseAuthorizationRequest), _original(),
        )


def test_giss_async_submission_and_status_four_cannot_be_invoice_authority() -> None:
    for method in ("RecepcionarLoteRps", "ConsultarNfsePorRps"):
        result = interpret_jundiai_giss_result(
            _receipt(method, state=4),
            Mock(spec=NfseAuthorizationRequest), _original(),
        )
        assert result.status is AuthorizationStatus.PENDING
        assert result.official_invoice is None


def test_giss_wrong_response_namespace_and_dtd_are_forbidden() -> None:
    for xml in (
        _official().replace(_NS.encode(), b"http://www.abrasf.org.br/nfse.xsd"),
        _official().replace(
            b"<ConsultarNfseRpsResposta",
            b"<!DOCTYPE x [<!ENTITY xx SYSTEM 'file:///etc/passwd'>]>"
            b"<ConsultarNfseRpsResposta",
            1,
        ),
    ):
        with pytest.raises(Sp4CanonicalMunicipalError):
            interpret_jundiai_giss_result(
                _receipt("ConsultarNfsePorRps", xml),
                Mock(spec=NfseAuthorizationRequest), _original(),
            )
