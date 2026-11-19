"""Offline ABRASF 2.03 SOAP preparation using the association's base WSDL.

Municipal WSDL and provider approval are still required before dispatch.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from functools import lru_cache
from importlib.resources import files

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.signing.nfse_xmldsig import append_nfse_signature
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.a1_preflight import validate_a1_for_issuer
from kordena_fiscal.xml.schema import SchemaResource, SchemaSet, XmlSchemaValidator

_ABRASF = "http://www.abrasf.org.br/nfse.xsd"
_WSDL = "http://nfse.abrasf.org.br"
_SOAP11 = "http://schemas.xmlsoap.org/soap/envelope/"
_DS = "http://www.w3.org/2000/09/xmldsig#"
_SCHEMA_SOURCE = "https://abrasf.org.br/biblioteca/arquivos-publicos/nfs-e/versao-2-03"
_SCHEMA_HASHES = {
    "nfse_v2-03.xsd": "7742fca4b417c4371519dff46912e16c445bc9e96002a66ffdda3b60462578d0",
    "xmldsig-core-schema20020212.xsd":
        "0f76f6de8dae190605a1a638f81a0a983e7ecd27a2aa6cc300828be1b48d2510",
}


class Abrasf203Operation(Enum):
    GENERATE = ("GerarNfseEnvio", "GerarNfse")
    SUBMIT_BATCH = ("EnviarLoteRpsEnvio", "RecepcionarLoteRps")
    SUBMIT_BATCH_SYNC = ("EnviarLoteRpsSincronoEnvio", "RecepcionarLoteRpsSincrono")
    QUERY_BATCH = ("ConsultarLoteRpsEnvio", "ConsultarLoteRps")
    QUERY_RPS = ("ConsultarNfseRpsEnvio", "ConsultarNfsePorRps")
    QUERY_ISSUED = ("ConsultarNfseServicoPrestadoEnvio", "ConsultarNfseServicoPrestado")
    QUERY_RECEIVED = ("ConsultarNfseServicoTomadoEnvio", "ConsultarNfseServicoTomado")
    QUERY_RANGE = ("ConsultarNfseFaixaEnvio", "ConsultarNfsePorFaixa")
    CANCEL = ("CancelarNfseEnvio", "CancelarNfse")
    SUBSTITUTE = ("SubstituirNfseEnvio", "SubstituirNfse")


@dataclass(frozen=True, slots=True)
class AbrasfServiceFacts:
    competence: str
    service_code: str
    municipal_tax_code: str | None
    service_municipality: str
    incidence_municipality: str | None
    iss_rate: str | None
    iss_withheld: str


@dataclass(frozen=True, slots=True)
class AbrasfCancellationFacts:
    """Inputs for the existing fiscal cancellation-policy authority."""

    issuer_cnpj: str
    municipality_ibge: str
    invoice_number: str
    cancellation_code: str


@dataclass(frozen=True, slots=True)
class Abrasf203Envelope:
    body: bytes
    soap_action: str
    content_type: str = "text/xml; charset=utf-8"
    schema_version: str = "2.03"
    schema_package_sha256: str | None = None


@lru_cache(maxsize=1)
def _validator() -> XmlSchemaValidator:
    directory = files("kordena_fiscal.xml").joinpath("official", "ABRASF_203")
    return XmlSchemaValidator(SchemaSet(
        version="ABRASF 2.03 normalized",
        root_schema="nfse_v2-03.xsd",
        resources=tuple(
            SchemaResource(name, directory.joinpath(name).read_bytes(), digest)
            for name, digest in _SCHEMA_HASHES.items()
        ),
        source_uri=_SCHEMA_SOURCE,
    ))


def prepare_abrasf203_soap(
    *,
    operation: Abrasf203Operation,
    xml: bytes,
    scope: ExecutionScope,
    issuer_cnpj: Cnpj,
    resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
    preaudit: Callable[[tuple[AbrasfServiceFacts, ...]], None],
    preaudit_cancel: Callable[[AbrasfCancellationFacts], None] | None = None,
    municipal_schema_version: str | None = None,
    municipal_validator: XmlSchemaValidator | None = None,
) -> Abrasf203Envelope:
    """Validate, audit and sign RPS before lot, then serialize SOAP string parts."""
    if scope.environment is not FiscalEnvironment.HOMOLOGATION:
        raise FiscalValidationError("ABRASF preparation is restricted to homologation")
    if not isinstance(operation, Abrasf203Operation):
        raise FiscalValidationError("Unsupported ABRASF operation")
    if not isinstance(xml, bytes) or not 0 < len(xml) <= 2_097_152:
        raise FiscalValidationError("Invalid ABRASF payload size")
    if not callable(preaudit) or not callable(resolve_certificate):
        raise FiscalValidationError("Trusted audit and scoped A1 resolver are required")
    root_name, method = operation.value
    ns = {"a": _ABRASF}
    try:
        root: etree._Element = etree.fromstring(
            xml, parser=etree.XMLParser(resolve_entities=False, no_network=True),
        )
    except etree.XMLSyntaxError:
        raise FiscalValidationError("Invalid ABRASF XML") from None
    if (
        root.tag != f"{{{_ABRASF}}}{root_name}"
        or getattr(root.getroottree().docinfo, "doctype", None)
        or root.find(f".//{{{_DS}}}Signature") is not None
    ):
        raise FiscalValidationError("Unexpected ABRASF payload root or existing signature")
    if (municipal_schema_version is None) != (municipal_validator is None):
        raise FiscalValidationError(
            "Municipal layout version and pinned validator must be supplied together"
        )
    if municipal_schema_version is not None and municipal_schema_version != "2.02":
        raise FiscalValidationError("Unsupported external municipal fiscal schema version")
    schema_version = municipal_schema_version or "2.03"
    validator = municipal_validator or _validator()
    validation = validator.validate_document(xml)
    if operation in (Abrasf203Operation.SUBMIT_BATCH, Abrasf203Operation.SUBMIT_BATCH_SYNC):
        lot = root.find("a:LoteRps", ns)
        if lot is None or lot.get("versao") != schema_version:
            raise FiscalValidationError("ABRASF lot version does not match provider schema")

    if operation in (
        Abrasf203Operation.QUERY_BATCH,
        Abrasf203Operation.QUERY_RPS,
        Abrasf203Operation.QUERY_ISSUED,
        Abrasf203Operation.QUERY_RECEIVED,
        Abrasf203Operation.QUERY_RANGE,
    ):
        requester = (
            "a:Consulente"
            if operation is Abrasf203Operation.QUERY_RECEIVED else "a:Prestador"
        )
        if root.findtext(requester + "/a:CpfCnpj/a:Cnpj", namespaces=ns) != issuer_cnpj.value:
            raise FiscalValidationError("ABRASF query issuer mismatch")
    elif operation is Abrasf203Operation.CANCEL:
        pedido = root.find("a:Pedido", ns)
        info = pedido.find("a:InfPedidoCancelamento", ns) if pedido is not None else None
        identification = (
            info.find("a:IdentificacaoNfse", ns) if info is not None else None
        )
        if identification is None or info is None or pedido is None:
            raise FiscalValidationError("ABRASF cancellation request is incomplete")
        cancellation_cnpj = identification.findtext("a:CpfCnpj/a:Cnpj", "", ns)
        number = identification.findtext("a:Numero", "", ns)
        municipality = identification.findtext("a:CodigoMunicipio", "", ns)
        code = info.findtext("a:CodigoCancelamento", "", ns)
        if (
            cancellation_cnpj != issuer_cnpj.value
            or not number or not number.isdecimal()
            or not municipality or not municipality.isdecimal()
            or code not in ("1", "2", "3", "4", "5")
            or not info.get("Id")
            or sum(node.get("Id") == info.get("Id") for node in root.iter()) != 1
        ):
            raise FiscalValidationError("ABRASF cancellation fiscal identity mismatch")
        if not callable(preaudit_cancel):
            raise FiscalValidationError("Explicit cancellation preaudit is required")
        preaudit_cancel(AbrasfCancellationFacts(
            issuer_cnpj=cancellation_cnpj,
            municipality_ibge=municipality,
            invoice_number=number,
            cancellation_code=code,
        ))
        material = resolve_certificate(scope, issuer_cnpj.value)
        validate_a1_for_issuer(
            material.pkcs12_bytes, material.password,
            issuer_cnpj=issuer_cnpj, at=datetime.now(UTC),
        )
        key, cert, _ = pkcs12.load_key_and_certificates(
            material.pkcs12_bytes, material.password
        )
        if not isinstance(key, rsa.RSAPrivateKey) or cert is None:
            raise FiscalValidationError("ABRASF cancel signature requires RSA A1")
        append_nfse_signature(pedido, info, key, cert, legacy_abrasf=True)
    elif operation is Abrasf203Operation.SUBSTITUTE:
        substitution = root.find("a:SubstituicaoNfse", ns)
        pedido = substitution.find("a:Pedido", ns) if substitution is not None else None
        old_info = pedido.find("a:InfPedidoCancelamento", ns) if pedido is not None else None
        old_note = old_info.find("a:IdentificacaoNfse", ns) if old_info is not None else None
        replacement = substitution.find("a:Rps", ns) if substitution is not None else None
        new_info = (
            replacement.find("a:InfDeclaracaoPrestacaoServico", ns)
            if replacement is not None else None
        )
        if (
            old_info is None or old_note is None or pedido is None
            or replacement is None or new_info is None or substitution is None
        ):
            raise FiscalValidationError("ABRASF substitution intent is incomplete")
        cancellation_cnpj = old_note.findtext("a:CpfCnpj/a:Cnpj", "", ns)
        cancelled_number = old_note.findtext("a:Numero", "", ns)
        municipality = old_note.findtext("a:CodigoMunicipio", "", ns)
        code = old_info.findtext("a:CodigoCancelamento", "", ns)
        new_issuer = new_info.findtext("a:Prestador/a:CpfCnpj/a:Cnpj", "", ns)
        identifiers = (
            old_info.get("Id"), new_info.get("Id"), substitution.get("Id"),
        )
        if (
            cancellation_cnpj != issuer_cnpj.value
            or new_issuer != issuer_cnpj.value
            or not cancelled_number.isdecimal()
            or not municipality.isdecimal()
            or code not in ("1", "2", "3", "4", "5")
            or any(not identifier for identifier in identifiers)
            or len(set(identifiers)) != 3
            or any(sum(node.get("Id") == identifier for node in root.iter()) != 1
                   for identifier in identifiers)
        ):
            raise FiscalValidationError("ABRASF substitution fiscal identity mismatch")
        if not callable(preaudit_cancel):
            raise FiscalValidationError("Substitution requires original-note cancellation preaudit")
        service = new_info.find("a:Servico", ns)
        if service is None:
            raise FiscalValidationError("ABRASF replacement service is missing")
        preaudit_cancel(AbrasfCancellationFacts(
            issuer_cnpj=cancellation_cnpj,
            municipality_ibge=municipality,
            invoice_number=cancelled_number,
            cancellation_code=code,
        ))
        preaudit((AbrasfServiceFacts(
            competence=new_info.findtext("a:Competencia", "", ns),
            service_code=service.findtext("a:ItemListaServico", "", ns),
            municipal_tax_code=service.findtext("a:CodigoTributacaoMunicipio", None, ns),
            service_municipality=service.findtext("a:CodigoMunicipio", "", ns),
            incidence_municipality=service.findtext("a:MunicipioIncidencia", None, ns),
            iss_rate=service.findtext("a:Valores/a:Aliquota", None, ns),
            iss_withheld=service.findtext("a:IssRetido", "", ns),
        ),))
        material = resolve_certificate(scope, issuer_cnpj.value)
        validate_a1_for_issuer(
            material.pkcs12_bytes, material.password,
            issuer_cnpj=issuer_cnpj, at=datetime.now(UTC),
        )
        key, cert, _ = pkcs12.load_key_and_certificates(
            material.pkcs12_bytes, material.password,
        )
        if not isinstance(key, rsa.RSAPrivateKey) or cert is None:
            raise FiscalValidationError("Substitution signature requires RSA A1")
        # Sign the original cancellation and replacement RPS separately.
        # The enclosing substitution is signed LAST, binding both operations.
        append_nfse_signature(pedido, old_info, key, cert, legacy_abrasf=True)
        append_nfse_signature(replacement, new_info, key, cert, legacy_abrasf=True)
        append_nfse_signature(root, substitution, key, cert, legacy_abrasf=True)
    else:
        rps_path = "a:Rps"
        batch = root.find("a:LoteRps", ns)
        if operation in (Abrasf203Operation.SUBMIT_BATCH, Abrasf203Operation.SUBMIT_BATCH_SYNC):
            if (
                batch is None
                or batch.findtext("a:CpfCnpj/a:Cnpj", namespaces=ns) != issuer_cnpj.value
            ):
                raise FiscalValidationError("ABRASF batch issuer mismatch")
            rps_path = "a:LoteRps/a:ListaRps/a:Rps"
        items = root.findall(rps_path, ns)
        if not items or (
            batch is not None and int(batch.findtext("a:QuantidadeRps", "0", ns)) != len(items)
        ):
            raise FiscalValidationError("ABRASF RPS count mismatch")
        facts = []
        targets = []
        for rps in items:
            info = rps.find("a:InfDeclaracaoPrestacaoServico", ns)
            if (
                info is None
                or info.findtext("a:Prestador/a:CpfCnpj/a:Cnpj", namespaces=ns) != issuer_cnpj.value
            ):
                raise FiscalValidationError("ABRASF RPS issuer mismatch")
            targets.append((rps, info))
            facts.append(AbrasfServiceFacts(
                competence=info.findtext("a:Competencia", "", ns),
                service_code=info.findtext("a:Servico/a:ItemListaServico", "", ns),
                municipal_tax_code=info.findtext("a:Servico/a:CodigoTributacaoMunicipio", None, ns),
                service_municipality=info.findtext("a:Servico/a:CodigoMunicipio", "", ns),
                incidence_municipality=info.findtext("a:Servico/a:MunicipioIncidencia", None, ns),
                iss_rate=info.findtext("a:Servico/a:Valores/a:Aliquota", None, ns),
                iss_withheld=info.findtext("a:Servico/a:IssRetido", "", ns),
            ))
        if batch is not None:
            targets.append((root, batch))
        ids = [node.get("Id") for node in root.iter() if node.get("Id") is not None]
        if len(ids) != len(set(ids)) or any(not node.get("Id") for _, node in targets):
            raise FiscalValidationError("ABRASF signature Id missing or duplicated")
        preaudit(tuple(facts))
        material = resolve_certificate(scope, issuer_cnpj.value)
        validate_a1_for_issuer(
            material.pkcs12_bytes, material.password, issuer_cnpj=issuer_cnpj, at=datetime.now(UTC),
        )
        key, cert, _ = pkcs12.load_key_and_certificates(material.pkcs12_bytes, material.password)
        if not isinstance(key, rsa.RSAPrivateKey) or cert is None:
            raise FiscalValidationError("ABRASF signature requires an RSA A1")
        for parent, target in targets:
            append_nfse_signature(parent, target, key, cert, legacy_abrasf=True)

    data = etree.tostring(root, encoding="utf-8")
    validator.validate_document(data)
    header = etree.Element(
        f"{{{_ABRASF}}}cabecalho", nsmap={"a": _ABRASF}, versao=schema_version,
    )
    etree.SubElement(header, f"{{{_ABRASF}}}versaoDados").text = schema_version
    header_xml = etree.tostring(header, encoding="utf-8")
    validator.validate_document(header_xml)
    envelope = etree.Element(f"{{{_SOAP11}}}Envelope", nsmap={"soap": _SOAP11})
    body = etree.SubElement(envelope, f"{{{_SOAP11}}}Body")
    wrapper = etree.SubElement(body, f"{{{_WSDL}}}{method}Request", nsmap={"ws": _WSDL})
    etree.SubElement(wrapper, "nfseCabecMsg").text = header_xml.decode("utf-8")
    etree.SubElement(wrapper, "nfseDadosMsg").text = data.decode("utf-8")
    return Abrasf203Envelope(
        etree.tostring(envelope, encoding="utf-8", xml_declaration=True),
        f'"{_WSDL}/{method}"',
        schema_version=schema_version,
        schema_package_sha256=validation.schema_package_sha256,
    )
