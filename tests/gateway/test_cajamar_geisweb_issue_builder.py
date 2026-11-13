"""GeisWeb20 emission from canonical tax facts, not an arbitrary XML string."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from lxml import etree

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.cajamar_geisweb_issue_builder import (
    CajamarGeiswebIssueData,
    CajamarGeiswebIssueError,
    build_cajamar_issue_xml,
    prepare_cajamar_signed_issue,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.runtime.sp4_municipal_request_factories import (
    build_cajamar_geisweb_issue_request_factory,
)

_NS = {"g": "http://www.geisweb.net.br/xsd/envio_lote_rps.xsd"}


def _source() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            tenant_id="cajamar", unit_id="north", host_namespace="nfcore",
            environment=FiscalEnvironment.HOMOLOGATION,
            correlation_id="geis-issue",
        ),
        document_id="rps-original", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3509205",
        competence_date=date(2026, 10, 31), rps_number="42",
        rps_series="NF", gross_amount=Decimal("150.00"),
        municipal_batch_id="12345",
    )


def _request(source: Sp4OriginalRps) -> NfseAuthorizationRequest:
    request = Mock(spec=NfseAuthorizationRequest)
    request.document.scope = source.scope
    request.document.document_id = source.document_id
    request.document.issuer.cnpj = source.issuer_cnpj
    request.document.issuer.tax_regime = TaxRegimeCode.NORMAL
    request.document.competence_date = source.competence_date
    request.document.totals.gross_amount.amount = source.gross_amount
    request.document.issued_at = datetime(2026, 10, 31, tzinfo=UTC)
    request.request_fingerprint = source.request_fingerprint
    service = Mock()
    service.gross_amount.amount = source.gross_amount
    service.taxable_amount.amount = Decimal("150.00")
    service.description = "Consultoria de tecnologia"
    request.document.services = (service,)
    return request


def _data() -> CajamarGeiswebIssueData:
    return CajamarGeiswebIssueData(
        municipal_registration="1234567", service_code="0107",
        launch_type="N", issuer_regime="6", iss_rate=Decimal("2.00"),
        service_city="Cajamar",
        recipient_tax_id="11222333000181", recipient_name="Cliente Teste",
        recipient_street="Rua das Flores", recipient_number="21",
        recipient_neighborhood="Centro", recipient_city="Jundiai",
        recipient_state="SP", recipient_postal_code="07750000",
        pis=Decimal("0.65"), cofins=Decimal("3.00"),
    )


def test_envelope_contains_full_lot_issuer_taker_tax_and_original_rps() -> None:
    source = _source()
    xml = build_cajamar_issue_xml(
        request=_request(source), original=source, fields=_data(),
    )
    root = etree.fromstring(xml)
    assert root.tag == "{http://www.geisweb.net.br/xsd/envio_lote_rps.xsd}EnviaLoteRps"
    assert root.findtext("g:NumeroLote", namespaces=_NS) == "12345"
    assert root.findtext(
        "g:Rps/g:IdentificacaoRps/g:NumeroRps", namespaces=_NS,
    ) == "42"
    assert root.findtext(
        "g:Rps/g:Servico/g:Valores/g:ValorServicos", namespaces=_NS,
    ) == "150.00"
    assert root.findtext(
        "g:Rps/g:Servico/g:TomadorServico/g:IdentificacaoTomador/"
        "g:RazaoSocial", namespaces=_NS,
    ) == "Cliente Teste"
    assert root.findtext(
        "g:Rps/g:Servico/g:OutrosImpostos/g:Cofins", namespaces=_NS,
    ) == "3.00"


@pytest.mark.parametrize("change", [
    {"municipal_batch_id": None},
    {"document_id": "another-document"},
    {"gross_amount": Decimal("151.00")},
])
def test_issue_rejects_original_source_mismatch(change: dict[str, object]) -> None:
    original = _source()
    with pytest.raises(CajamarGeiswebIssueError, match="original RPS"):
        build_cajamar_issue_xml(
            request=_request(original), original=replace(original, **change),
            fields=_data(),
        )


def test_signer_cannot_rewrite_source_lot_or_issuer() -> None:
    source = _source()
    validated = Mock()
    with pytest.raises(CajamarGeiswebIssueError, match="no longer matches"):
        prepare_cajamar_signed_issue(
            request=_request(source), original=source, fields=_data(),
            sign_document=lambda xml: xml.replace(b"12345", b"12346"),
            validate_signed_request=validated,
        )
    validated.assert_not_called()


def test_issue_and_query_share_same_reviewed_factory() -> None:
    source = _source()
    issue_validator = Mock()
    query_validator = Mock()
    factory = build_cajamar_geisweb_issue_request_factory(
        resolve_issue_fields=lambda _req, _src: _data(),
        sign_issue=lambda xml: xml,
        validate_signed_issue=issue_validator,
        sign_lot_query=lambda xml: xml,
        validate_signed_query=query_validator,
    )
    issue = factory(_request(source), source, "EnviaLoteRps")
    query = factory(_request(source), source, "ConsultaLoteRps")
    assert issue.method == "EnviaLoteRps"
    assert query.method == "ConsultaLoteRps"
    assert b"12345" in issue.signed_request_xml
    assert b"12345" in query.signed_request_xml
    issue_validator.assert_called_once()
    query_validator.assert_called_once()


def test_municipal_fields_require_reviewed_classification_and_recipient() -> None:
    source = _source()
    for fields in (
        replace(_data(), service_code="7.02"),
        replace(_data(), launch_type="X"),
        replace(_data(), recipient_tax_id="not-a-document"),
        replace(_data(), iss_rate=Decimal("NaN")),
    ):
        with pytest.raises(CajamarGeiswebIssueError):
            build_cajamar_issue_xml(
                request=_request(source), original=source, fields=fields,
            )


@pytest.mark.parametrize("old,new", [
    (b"BaseCalculo>150.00", b"BaseCalculo>149.00"),
    (b"Aliquota>2.00", b"Aliquota>5.00"),
    (b"CodigoServico>0107", b"CodigoServico>0108"),
    (b"TipoLancamento>N", b"TipoLancamento>T"),
    (b"Regime>6", b"Regime>1"),
    (b"RazaoSocial>Cliente Teste", b"RazaoSocial>Outra Empresa"),
    (b"Cofins>3.00", b"Cofins>4.00"),
    (b"Discriminacao>Consultoria", b"Discriminacao>Engenharia"),
])
def test_signed_issue_rejects_tax_or_recipient_mutation_before_schema(
    old: bytes, new: bytes,
) -> None:
    source = _source()
    checked = Mock()

    def tamper(xml: bytes) -> bytes:
        assert old in xml
        return xml.replace(old, new)

    with pytest.raises(CajamarGeiswebIssueError, match="no longer matches"):
        prepare_cajamar_signed_issue(
            request=_request(source), original=source, fields=_data(),
            sign_document=tamper, validate_signed_request=checked,
        )
    checked.assert_not_called()


def test_signed_issue_detects_removed_mandatory_tax_without_recalculation() -> None:
    source = _source()
    checked = Mock()
    with pytest.raises(CajamarGeiswebIssueError, match="no longer matches"):
        prepare_cajamar_signed_issue(
            request=_request(source), original=source, fields=_data(),
            sign_document=lambda xml: xml.replace(
                b"<geis:Pis>0.65</geis:Pis>", b"",
            ),
            validate_signed_request=checked,
        )
    checked.assert_not_called()
