"""ABRASF 2.03 base contract verified after SOAP round-trip."""
import base64
import hashlib
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree
from test_mg_homologation_authorization import CNPJ, _request
from test_mg_homologation_authorization import material as material

from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.gateway.nfse_abrasf203_envelope import (
    Abrasf203Operation,
    prepare_abrasf203_soap,
)

_A = "http://www.abrasf.org.br/nfse.xsd"
_DS = "http://www.w3.org/2000/09/xmldsig#"
_RPS = (
    '<Rps><InfDeclaracaoPrestacaoServico Id="RPS1">'
    '<Competencia>2026-11-06</Competencia><Servico><Valores>'
    '<ValorServicos>100.00</ValorServicos><Aliquota>2.00</Aliquota></Valores>'
    '<IssRetido>2</IssRetido><ItemListaServico>01.01</ItemListaServico>'
    '<Discriminacao>Teste sintetico</Discriminacao><CodigoMunicipio>5002704</CodigoMunicipio>'
    '<ExigibilidadeISS>1</ExigibilidadeISS></Servico>'
    f'<Prestador><CpfCnpj><Cnpj>{CNPJ}</Cnpj></CpfCnpj></Prestador>'
    '<OptanteSimplesNacional>2</OptanteSimplesNacional><IncentivoFiscal>2</IncentivoFiscal>'
    '</InfDeclaracaoPrestacaoServico></Rps>'
)


def _payload(operation):
    name, _ = operation.value
    body = _RPS
    if operation is Abrasf203Operation.SUBMIT_BATCH:
        body = (
            '<LoteRps Id="LOTE1" versao="2.03"><NumeroLote>1</NumeroLote>'
            f'<CpfCnpj><Cnpj>{CNPJ}</Cnpj></CpfCnpj><QuantidadeRps>1</QuantidadeRps>'
            f'<ListaRps>{_RPS}</ListaRps></LoteRps>'
        )
    elif operation is Abrasf203Operation.QUERY_BATCH:
        body = (
            f'<Prestador><CpfCnpj><Cnpj>{CNPJ}</Cnpj></CpfCnpj></Prestador>'
            '<Protocolo>123456</Protocolo>'
        )
    elif operation is Abrasf203Operation.QUERY_ISSUED:
        body = (
            f'<Prestador><CpfCnpj><Cnpj>{CNPJ}</Cnpj></CpfCnpj></Prestador>'
            '<NumeroNfse>123</NumeroNfse><Pagina>1</Pagina>'
        )
    return f'<{name} xmlns="{_A}">{body}</{name}>'.encode()


@pytest.mark.parametrize("operation,count", [
    (Abrasf203Operation.GENERATE, 1),
    (Abrasf203Operation.SUBMIT_BATCH, 2),
    (Abrasf203Operation.QUERY_BATCH, 0),
    (Abrasf203Operation.QUERY_ISSUED, 0),
])
def test_soap_contains_correct_parts_and_verifiable_signatures(material, operation, count):
    calls = Mock()
    calls.resolve.return_value = material
    scope = _request().scope
    result = prepare_abrasf203_soap(
        operation=operation, xml=_payload(operation), scope=scope, issuer_cnpj=Cnpj(CNPJ),
        resolve_certificate=calls.resolve, preaudit=calls.audit,
    )
    soap = etree.fromstring(result.body)
    wrapper = soap[0][0]
    assert wrapper.tag == "{http://nfse.abrasf.org.br}" + operation.value[1] + "Request"
    assert result.soap_action == f'"http://nfse.abrasf.org.br/{operation.value[1]}"'
    header = etree.fromstring(wrapper.findtext("nfseCabecMsg").encode())
    assert header.findtext(f"{{{_A}}}versaoDados") == "2.03"
    payload = etree.fromstring(wrapper.findtext("nfseDadosMsg").encode())
    signatures = payload.findall(f".//{{{_DS}}}Signature")
    assert len(signatures) == count
    if not count:
        assert not calls.mock_calls
        return
    assert [call[0] for call in calls.mock_calls] == ["audit", "resolve"]
    assert calls.audit.call_args.args[0][0].service_code == "01.01"
    assert calls.resolve.call_args.args == (scope, CNPJ)
    _, cert, _ = pkcs12.load_key_and_certificates(material.pkcs12_bytes, material.password)
    for signature in signatures:
        info = signature.find(f"{{{_DS}}}SignedInfo")
        reference = info.find(f"{{{_DS}}}Reference")
        target = payload.xpath("//*[@Id=$id]", id=reference.get("URI")[1:])[0]
        assert signature.getparent() is target.getparent()
        canonical = etree.tostring(target, method="c14n", with_comments=False)
        assert base64.b64decode(reference.findtext(f"{{{_DS}}}DigestValue")) == (
            hashlib.sha1(canonical).digest()
        )
        cert.public_key().verify(
            base64.b64decode(signature.findtext(f"{{{_DS}}}SignatureValue")),
            etree.tostring(info, method="c14n", with_comments=False),
            padding.PKCS1v15(), hashes.SHA1(),
        )


def test_failed_preaudit_never_accesses_vault():
    resolve = Mock()
    audit = Mock(side_effect=FiscalValidationError("tax review required"))
    with pytest.raises(FiscalValidationError, match="tax review required"):
        prepare_abrasf203_soap(
            operation=Abrasf203Operation.GENERATE, xml=_payload(Abrasf203Operation.GENERATE),
            scope=_request().scope, issuer_cnpj=Cnpj(CNPJ),
            resolve_certificate=resolve, preaudit=audit,
        )
    resolve.assert_not_called()


_CANCEL = (
    '<CancelarNfseEnvio xmlns="http://www.abrasf.org.br/nfse.xsd">'
    '<Pedido><InfPedidoCancelamento Id="CANCEL1">'
    '<IdentificacaoNfse><Numero>123</Numero><CpfCnpj>'
    f'<Cnpj>{CNPJ}</Cnpj>'
    '</CpfCnpj><CodigoMunicipio>3125101</CodigoMunicipio></IdentificacaoNfse>'
    '<CodigoCancelamento>1</CodigoCancelamento>'
    '</InfPedidoCancelamento></Pedido></CancelarNfseEnvio>'
)


def test_cancellation_uses_independent_audit_scoped_a1_and_verified_xmldsig(
    material,
) -> None:
    calls = Mock()
    calls.resolve.return_value = material
    signed = prepare_abrasf203_soap(
        operation=Abrasf203Operation.CANCEL,
        xml=_CANCEL.encode(), scope=_request().scope,
        issuer_cnpj=Cnpj(CNPJ), resolve_certificate=calls.resolve,
        preaudit=calls.audit, preaudit_cancel=calls.cancel_audit,
    )
    assert [call[0] for call in calls.mock_calls] == ["cancel_audit", "resolve"]
    facts = calls.cancel_audit.call_args.args[0]
    assert facts.issuer_cnpj == CNPJ
    assert facts.municipality_ibge == "3125101"
    assert facts.invoice_number == "123"
    assert facts.cancellation_code == "1"
    wrapper = etree.fromstring(signed.body)[0][0]
    assert wrapper.tag == "{http://nfse.abrasf.org.br}CancelarNfseRequest"
    payload = etree.fromstring(wrapper.findtext("nfseDadosMsg").encode())
    signature = payload.find(f".//{{{_DS}}}Signature")
    assert signature is not None
    assert signature.getparent().tag == f"{{{_A}}}Pedido"
    signed_info = signature.find(f"{{{_DS}}}SignedInfo")
    reference = signed_info.find(f"{{{_DS}}}Reference")
    target = payload.xpath("//*[@Id=$id]", id=reference.get("URI")[1:])[0]
    assert target.tag == f"{{{_A}}}InfPedidoCancelamento"
    assert base64.b64decode(reference.findtext(f"{{{_DS}}}DigestValue")) == (
        hashlib.sha1(etree.tostring(target, method="c14n")).digest()
    )
    _, cert, _ = pkcs12.load_key_and_certificates(
        material.pkcs12_bytes, material.password
    )
    cert.public_key().verify(
        base64.b64decode(signature.findtext(f"{{{_DS}}}SignatureValue")),
        etree.tostring(signed_info, method="c14n"),
        padding.PKCS1v15(), hashes.SHA1(),
    )


def test_cancel_must_fail_before_certificate_for_wrong_issuer_or_policy(material) -> None:
    calls = Mock()
    calls.resolve.return_value = material
    original_scope = _request().scope
    with pytest.raises(FiscalValidationError, match="Explicit cancellation preaudit"):
        prepare_abrasf203_soap(
            operation=Abrasf203Operation.CANCEL, xml=_CANCEL.encode(),
            scope=original_scope, issuer_cnpj=Cnpj(CNPJ),
            resolve_certificate=calls.resolve, preaudit=calls.audit,
        )
    calls.resolve.assert_not_called()
    with pytest.raises(FiscalValidationError, match="identity mismatch"):
        prepare_abrasf203_soap(
            operation=Abrasf203Operation.CANCEL, xml=_CANCEL.encode(),
            scope=original_scope, issuer_cnpj=Cnpj("12345678000195"),
            resolve_certificate=calls.resolve, preaudit=calls.audit,
            preaudit_cancel=calls.cancel_audit,
        )
    calls.resolve.assert_not_called()
    calls.cancel_audit.assert_not_called()
    calls.cancel_audit.side_effect = FiscalValidationError("cancellation denied by policy")
    with pytest.raises(FiscalValidationError, match="cancellation denied by policy"):
        prepare_abrasf203_soap(
            operation=Abrasf203Operation.CANCEL, xml=_CANCEL.encode(),
            scope=original_scope, issuer_cnpj=Cnpj(CNPJ),
            resolve_certificate=calls.resolve, preaudit=calls.audit,
            preaudit_cancel=calls.cancel_audit,
        )
    calls.resolve.assert_not_called()
