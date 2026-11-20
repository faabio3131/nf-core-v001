"""Cajamar municipal component spine: canonical RPS -> GeisWeb -> original-lot query.

No application/Portal integration is claimed by this synthetic isolated test.
Official schema, signature and external network are provided as test doubles.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock
from xml.sax.saxutils import escape

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    ExecutionScope,
    FiscalAddress,
    FiscalEnvironment,
    FiscalProfile,
    Money,
    SourceReference,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.cajamar_geisweb_homologation import (
    CajamarGeiswebHomologationTransport,
    CajamarGeiswebResult,
)
from kordena_fiscal.gateway.cajamar_geisweb_issue_builder import CajamarGeiswebIssueData
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4VerifiedInvoice
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseCanonicalDocument,
    NfseServiceLine,
)
from kordena_fiscal.issuance.sp4_original_rps_archive import (
    build_sp4_original_from_reservation,
)
from kordena_fiscal.numbering import (
    FiscalNumberReservation,
    FiscalSequenceKey,
    InternalFiscalSequenceStream,
)
from kordena_fiscal.runtime.sp4_municipal_canonical_composition import (
    build_sp4_canonical_clients,
)
from kordena_fiscal.runtime.sp4_municipal_provider_bridges import (
    Sp4BridgeAuthority,
    build_cajamar_reviewed_ports,
    build_cajamar_verified_cancellation_port,
)
from kordena_fiscal.runtime.sp4_municipal_request_factories import (
    build_cajamar_geisweb_issue_request_factory,
)


def _canonical_request() -> NfseAuthorizationRequest:
    scope = ExecutionScope(
        host_namespace="nfcore", tenant_id="cajamar-spine",
        unit_id="unit-1", environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="synthetic-cajamar-spine",
    )
    city = BrazilianJurisdiction("SP", "3509205")
    issuer = FiscalProfile(
        profile_id="cajamar-issuer", scope=scope,
        cnpj=Cnpj("11222333000181"), legal_name="Emissor de Testes",
        tax_regime=TaxRegimeCode.NORMAL,
        state_registration=StateRegistration("SP", "123456789"),
        primary_cnae=CnaeCode("6201501"),
        address=FiscalAddress(
            street="Rua Ficticia", number="10", district="Centro",
            municipality_name="Cajamar", jurisdiction=city,
            postal_code="07750000",
        ),
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    document = NfseCanonicalDocument(
        document_id="cajamar-spine-doc", scope=scope,
        source=SourceReference("service-order", "cajamar-spine-1"),
        issued_at=datetime(2026, 11, 12, 12, tzinfo=UTC),
        competence_date=date(2026, 10, 31),
        issuer=issuer, service_jurisdiction=city,
        services=(NfseServiceLine(
            line_number=1, municipal_service_code="0107",
            national_taxation_code="010701",
            description="Servico de software sintetico",
            gross_amount=Money(Decimal("150.00")),
            iss_amount=Money(Decimal("3.00")),
            source_normative="urn:nfcore:synthetic:cajamar-2026",
        ),),
    )
    return NfseAuthorizationRequest.build(document)


def _fields() -> CajamarGeiswebIssueData:
    return CajamarGeiswebIssueData(
        municipal_registration="1234567", service_code="0107",
        launch_type="N", issuer_regime="6", iss_rate=Decimal("2.00"),
        service_city="Cajamar", recipient_tax_id="11222333000181",
        recipient_name="Tomador de Testes", recipient_street="Rua das Flores",
        recipient_number="21", recipient_neighborhood="Centro",
        recipient_city="Jundiai", recipient_state="SP",
        recipient_postal_code="07750000",
    )


def _mock_consulta_lote_response(cnpj: str, rps_number: str) -> bytes:
    official = (
        "<ConsultaLoteRpsResposta><Rps><IdentificacaoNfse>"
        f"<NumeroRps>{rps_number}</NumeroRps>"
        "<NumeroNfse>8765</NumeroNfse>"
        "<CodigoVerificacao>ABCDEF1234</CodigoVerificacao>"
        "</IdentificacaoNfse><Competencia>2026-10</Competencia>"
        "<Servico><Valores><ValorServicos>150,00</ValorServicos></Valores>"
        "<PrestadorServico><IdentificacaoPrestador>"
        f"<CnpjCpf>{cnpj}</CnpjCpf>"
        "</IdentificacaoPrestador></PrestadorServico></Servico>"
        "</Rps></ConsultaLoteRpsResposta>"
    )
    return (
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:g="http://www.geisweb.com.br/"><soap:Body>'
        f"<g:ConsultaLoteRpsResponse><g:ConsultaLoteRpsResult>{escape(official)}"
        "</g:ConsultaLoteRpsResult></g:ConsultaLoteRpsResponse>"
        "</soap:Body></soap:Envelope>"
    ).encode()


def test_one_cajamar_rps_issue_and_read_only_recovery_with_verified_invoice() -> None:
    request = _canonical_request()
    key = FiscalSequenceKey.from_scope(
        request.document.scope, model=InternalFiscalSequenceStream.NFSE_RPS,
        series=1,
    )
    number = 42
    reservation = FiscalNumberReservation(
        key=key, number=number,
        reservation_token=hashlib.sha256(
            f"{key.canonical_material}|{number}".encode(),
        ).hexdigest(),
    )
    source = build_sp4_original_from_reservation(
        request, reservation, rps_series="NF",
    )
    assert source.municipal_batch_id == "42"

    validate_issue = Mock()
    validate_query = Mock()
    validate_identity = Mock()
    validate_official = Mock()
    fake_transport = Mock(spec=CajamarGeiswebHomologationTransport)

    def call_transport(operation):
        if operation.method == "EnviaLoteRps":
            return CajamarGeiswebResult(method=operation.method)
        assert operation.method == "ConsultaLoteRps"
        return CajamarGeiswebResult(
            method=operation.method,
            response_xml=_mock_consulta_lote_response(
                source.issuer_cnpj.value, source.rps_number,
            ),
        )

    fake_transport.invoke.side_effect = call_transport
    builder = build_cajamar_geisweb_issue_request_factory(
        resolve_issue_fields=lambda _req, _source: _fields(),
        sign_issue=lambda xml: xml, validate_signed_issue=validate_issue,
        sign_lot_query=lambda xml: xml, validate_signed_query=validate_query,
    )
    local_loader = Mock(side_effect=AssertionError("untrusted loader used"))
    authority = Sp4BridgeAuthority(
        load_original_rps=local_loader,
        fiscal_issuer_policy=Mock(),
        validate_prepared_rps=Mock(),
        verify_official_invoice_xml=validate_official,
    )
    reviewed = build_cajamar_reviewed_ports(
        authority=authority,
        transport=fake_transport,
        build_signed_operation=builder,
        verify_signed_rps_identity=validate_identity,
    )
    canonical_loader = Mock(return_value=source)
    resolver = Mock()
    resolver.resolve_provider_id.return_value = "cajamar-geisweb-homologation"
    issuance, recovery = build_sp4_canonical_clients(
        canonical_resolver=resolver,
        configured_municipalities={"cajamar-geisweb-homologation": reviewed},
        canonical_rps_loader=canonical_loader,
    )
    first = issuance["cajamar-geisweb-homologation"].authorize(request)
    assert first.status is AuthorizationStatus.PENDING
    assert first.invoice_number is None
    assert fake_transport.invoke.call_count == 1
    assert fake_transport.invoke.call_args.args[0].method == "EnviaLoteRps"

    final = recovery["cajamar-geisweb-homologation"].query(request)
    assert final.status is AuthorizationStatus.AUTHORIZED
    assert final.invoice_number == "8765"
    assert final.verification_code == "ABCDEF1234"
    assert final.authorized_xml is not None
    assert final.authorized_xml.startswith(b"<ConsultaLoteRpsResposta>")
    assert [call.args[0].method for call in fake_transport.invoke.call_args_list] == [
        "EnviaLoteRps", "ConsultaLoteRps",
    ]
    assert canonical_loader.call_count == 2
    local_loader.assert_not_called()
    validate_identity.assert_called()
    validate_issue.assert_called_once()
    validate_query.assert_called_once()
    validate_official.assert_called_once()


def test_cajamar_cancellation_traverses_signed_original_note_and_verified_transport() -> None:
    """No second RPS: CancelaNfse references already-authorized RPS and NFS-e."""
    req = _canonical_request()
    key = FiscalSequenceKey.from_scope(
        req.document.scope, model=InternalFiscalSequenceStream.NFSE_RPS, series=1,
    )
    reservation = FiscalNumberReservation(
        key=key, number=42,
        reservation_token=hashlib.sha256(
            f"{key.canonical_material}|42".encode(),
        ).hexdigest(),
    )
    original = build_sp4_original_from_reservation(
        req, reservation, rps_series="NF",
    )
    invoice = Sp4VerifiedInvoice(
        issuer_cnpj=original.issuer_cnpj,
        issuer_ibge=original.issuer_ibge,
        competence_date=original.competence_date,
        rps_number=original.rps_number,
        rps_series=original.rps_series,
        gross_amount=original.gross_amount,
        invoice_number="8765", verification_code="ABCDEF1234",
        invoice_reference="8765",
        authorized_xml=b"<ConsultaLoteRpsResposta>fixture</ConsultaLoteRpsResposta>",
    )
    inner = (
        "<CancelaNfseResposta><Nfse><IdentificacaoNfse>"
        "<NumeroRps>42</NumeroRps>"
        "<NumeroNfse>8765</NumeroNfse>"
        "<CodigoVerificacao>ABCDEF1234</CodigoVerificacao>"
        "</IdentificacaoNfse></Nfse></CancelaNfseResposta>"
    )
    soap = (
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"'
        ' xmlns:g="http://www.geisweb.com.br/"><soap:Body>'
        '<g:CancelaNfseResponse><g:CancelaNfseResult>'
        f"{escape(inner)}</g:CancelaNfseResult>"
        "</g:CancelaNfseResponse></soap:Body></soap:Envelope>"
    ).encode()
    transport = Mock(spec=CajamarGeiswebHomologationTransport)
    transport.invoke.return_value = CajamarGeiswebResult(
        method="CancelaNfse", response_xml=soap,
    )
    signed = Mock(side_effect=lambda scope, issuer, data: data)
    validate_signed = Mock()
    validate_official = Mock()
    cancel = build_cajamar_verified_cancellation_port(
        transport=transport, sign_cancel=signed,
        validate_signed_cancel=validate_signed,
        verify_official_cancel=validate_official,
    )
    decision = cancel(req, original, invoice)
    assert decision.confirmed is True
    assert decision.response_xml == inner.encode()
    assert decision.rejection_code is None
    transport.invoke.assert_called_once()
    sent = transport.invoke.call_args.args[0]
    assert sent.method == "CancelaNfse"
    assert sent.scope.identity_partition_key == original.scope.identity_partition_key
    assert sent.issuer_cnpj == original.issuer_cnpj
    assert b"<NumeroNfse>8765</NumeroNfse>" in sent.signed_request_xml
    assert b"<NumeroRps>" not in sent.signed_request_xml
    signed.assert_called_once()
    assert signed.call_args.args[:2] == (original.scope, original.issuer_cnpj)
    validate_signed.assert_called_once()
    assert validate_signed.call_args.args[:2] == (
        original.scope, original.issuer_cnpj,
    )
    validate_official.assert_called_once_with(
        original.scope, original.issuer_cnpj, inner.encode(),
    )
