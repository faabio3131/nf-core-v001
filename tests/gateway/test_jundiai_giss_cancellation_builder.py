"""Jundiaí GissOnline 2.04 cancellation for one verified municipal NFS-e."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest
from lxml import etree

from kordena_fiscal.domain import (
    Cnpj,
    ExecutionScope,
    FiscalEnvironment,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.jundiai_giss_cancellation_builder import (
    JundiaiGissCancelError,
    build_jundiai_cancel_xml,
    prepare_jundiai_cancel,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)

_ROOT = "{http://www.giss.com.br/cancelar-nfse-envio-v2_04.xsd}"
_T = "{http://www.giss.com.br/tipos-v2_04.xsd}"


def _source() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="tenant", unit_id="unit",
            environment=FiscalEnvironment.HOMOLOGATION,
            correlation_id="cancel-giss",
        ),
        document_id="original", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3525904",
        competence_date=date(2026, 10, 15),
        rps_number="42", rps_series="NF", gross_amount=Decimal("150.00"),
    )


def _invoice() -> Sp4VerifiedInvoice:
    s = _source()
    return Sp4VerifiedInvoice(
        issuer_cnpj=s.issuer_cnpj, issuer_ibge=s.issuer_ibge,
        competence_date=s.competence_date, rps_number=s.rps_number,
        rps_series=s.rps_series, gross_amount=s.gross_amount,
        invoice_number="8765", verification_code="ABCD1234",
        invoice_reference="8765", authorized_xml=b"<CompNfse/>",
    )


def _fields() -> dict[str, object]:
    return {
        "source": _source(),
        "issued": _invoice(),
        "cancel_code": "4",
        "signature_reference_id": "IDCancel42",
        "municipal_registration": "1234567",
    }


def test_giss_cancel_xml_correlates_nota_and_issuer_with_unique_xml_id() -> None:
    xml = build_jundiai_cancel_xml(**_fields())
    root = etree.fromstring(xml)
    assert etree.QName(root).localname == "CancelarNfseEnvio"
    info = root.find(f"{_ROOT}Pedido/{_T}InfPedidoCancelamento")
    assert info is not None
    assert info.get("Id") == "IDCancel42"
    assert info.findtext(f"{_T}IdentificacaoNfse/{_T}Numero") == "8765"
    assert info.findtext(f".//{_T}CpfCnpj/{_T}Cnpj") == "11222333000181"
    assert info.findtext(f".//{_T}CodigoMunicipio") == "3525904"
    assert info.findtext(f"{_T}CodigoCancelamento") == "4"


def test_signed_giss_cancel_keeps_source_signature_and_schema() -> None:
    sign = Mock(side_effect=lambda raw: raw)
    validate = Mock()
    prepared = prepare_jundiai_cancel(
        **_fields(), regime=TaxRegimeCode.NORMAL, human_approved=True,
        sign_document=sign, validate_signed_request=validate,
    )
    assert prepared.method == "CancelarNfse"
    assert prepared.human_approved is True
    assert prepared.scope.identity_partition_key == _source().scope.identity_partition_key
    sign.assert_called_once()
    validate.assert_called_once_with(prepared.signed_xml)


@pytest.mark.parametrize("code", ["3", "5", "0", "", "7"])
def test_municipally_reserved_or_unknown_cancel_reason_not_claimed(code: str) -> None:
    data = _fields()
    data["cancel_code"] = code
    with pytest.raises(JundiaiGissCancelError):
        build_jundiai_cancel_xml(**data)


def test_cancel_needs_explicit_workflow_approval() -> None:
    with pytest.raises(JundiaiGissCancelError):
        prepare_jundiai_cancel(
            **_fields(), regime=TaxRegimeCode.NORMAL,
            human_approved=False, sign_document=Mock(),
            validate_signed_request=Mock(),
        )


def test_cross_invoice_cancel_fails() -> None:
    data = _fields()
    data["issued"] = replace(_invoice(), rps_number="99")
    with pytest.raises(JundiaiGissCancelError):
        build_jundiai_cancel_xml(**data)


def test_signer_cannot_retarget_cancel_to_different_nota() -> None:
    def tamper(raw: bytes) -> bytes:
        return raw.replace(b"<tipos:Numero>8765</tipos:Numero>",
                           b"<tipos:Numero>9999</tipos:Numero>")
    validated = Mock()
    with pytest.raises(JundiaiGissCancelError, match="altered original note"):
        prepare_jundiai_cancel(
            **_fields(), regime=TaxRegimeCode.NORMAL,
            human_approved=True, sign_document=tamper,
            validate_signed_request=validated,
        )
    validated.assert_not_called()
