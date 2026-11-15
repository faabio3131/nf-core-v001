"""Opt-in GissOnline V2 startup with on-host reviewed WSDL, XSD and tax policy.

No hardcoded taxpayer, certificate or municipal SOAPAction. All references are
SHA-256 checked before a port can be attached to the canonical fiscal runtime.
The municipal contract is NOT activated merely because a city appears in a list.
"""
from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
from lxml import etree

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalAddress, FiscalValidationError
from kordena_fiscal.gateway.jundiai_giss_cancellation_builder import prepare_jundiai_cancel
from kordena_fiscal.gateway.jundiai_giss_cancellation_result import (
    JundiaiGissCancellationDecision,
    verify_jundiai_cancel_query,
    verify_jundiai_cancel_reply,
)
from kordena_fiscal.gateway.jundiai_giss_homologation import (
    JundiaiGissWsdlContract,
    JundiaiSignedOperation,
)
from kordena_fiscal.gateway.jundiai_giss_issue_builder import (
    JundiaiGissRecipient,
    JundiaiGissTaxFields,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.signing.nfse_xmldsig import append_nfse_signature
from kordena_fiscal.vault.a1_preflight import validate_a1_for_issuer
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault
from kordena_fiscal.xml.schema import SchemaResource, SchemaSet, XmlSchemaValidator

from .config import RuntimeConfigurationError
from .jundiai_operational_composition import (
    JundiaiTrustedRuntimePorts,
    build_jundiai_trusted_transport,
)
from .sp4_municipal_request_factories import build_jundiai_giss_issue_request_factory

_ENV = "NFCORE_JUNDIAI_GISS_CONFIG_PATH"
_LIMIT = 2_097_152
_DS = "{http://www.w3.org/2000/09/xmldsig#}"
_C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
_METHODS = frozenset({
    "RecepcionarLoteRps", "ConsultarLoteRps",
    "ConsultarNfsePorRps", "CancelarNfse",
})
_ROOTS = frozenset({
    *_METHODS, "ConsultarNfseRpsResposta", "CancelarNfseResposta",
})
_WSDL = "{http://schemas.xmlsoap.org/wsdl/}"
_SOAP = "{http://schemas.xmlsoap.org/wsdl/soap/}"


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        no_network=True, resolve_entities=False, load_dtd=False,
        huge_tree=False, remove_comments=False,
    )


def _object(value: object, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise RuntimeConfigurationError("Invalid reviewed Jundiai " + label)
    return value


def _pinned_file(folder: Path, name: object, digest: object) -> bytes:
    if (
        not isinstance(name, str) or not name or Path(name).name != name
        or name.startswith(".") or not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise RuntimeConfigurationError("Unsafe Jundiai official contract reference")
    file = folder / name
    if file.is_symlink() or not file.is_file() or not 0 < file.stat().st_size <= _LIMIT:
        raise RuntimeConfigurationError("Jundiai official contract file unavailable")
    contents = file.read_bytes()
    if hashlib.sha256(contents).hexdigest() != digest:
        raise RuntimeConfigurationError("Jundiai official contract SHA mismatch")
    return contents


def _verify_signature(
    raw: bytes, *, certificate: x509.Certificate, count: int,
) -> None:
    """Verify signed Id targets, algorithms, digests and cryptographic signatures."""
    try:
        root = etree.fromstring(raw, parser=_parser())
    except etree.XMLSyntaxError:
        raise FiscalValidationError("Malformed signed Jundiai XML") from None
    signatures = root.findall(".//" + _DS + "Signature")
    if len(signatures) != count:
        raise FiscalValidationError("Jundiai XMLDSig signature count differs")
    pub = certificate.public_key()
    if not isinstance(pub, rsa.RSAPublicKey):
        raise FiscalValidationError("Jundiai XMLDSig requires RSA certificate")
    for signature in signatures:
        signed_info = signature.find(_DS + "SignedInfo")
        reference = (
            signed_info.find(_DS + "Reference") if signed_info is not None else None
        )
        value = signature.findtext(_DS + "SignatureValue")
        embedded_cert = signature.findtext(
            _DS + "KeyInfo/" + _DS + "X509Data/" + _DS + "X509Certificate"
        )
        if signed_info is None or reference is None or not value or (
            embedded_cert != base64.b64encode(
                certificate.public_bytes(Encoding.DER)
            ).decode("ascii")
        ):
            raise FiscalValidationError("Untrusted Jundiai XMLDSig identity")
        uri = reference.get("URI")
        if uri is None or not uri.startswith("#") or len(uri) < 2:
            raise FiscalValidationError("Jundiai XMLDSig requires Id-bound reference")
        targets = [n for n in root.iter() if n.get("Id") == uri[1:]]
        if len(targets) != 1:
            raise FiscalValidationError("Jundiai XMLDSig target missing or duplicated")
        transforms = reference.find(_DS + "Transforms")
        canonical_method = signed_info.find(_DS + "CanonicalizationMethod")
        signature_method = signed_info.find(_DS + "SignatureMethod")
        digest_method = reference.find(_DS + "DigestMethod")
        if (
            canonical_method is None or canonical_method.get("Algorithm") != _C14N
            or signature_method is None
            or signature_method.get("Algorithm")
            != "http://www.w3.org/2000/09/xmldsig#rsa-sha1"
            or transforms is None
            or [x.get("Algorithm") for x in transforms] != [
                "http://www.w3.org/2000/09/xmldsig#enveloped-signature",
                _C14N,
            ]
            or digest_method is None
            or digest_method.get("Algorithm")
            != "http://www.w3.org/2000/09/xmldsig#sha1"
        ):
            raise FiscalValidationError("Unapproved GissOnline 2.04 XMLDSig algorithm")
        # A signature outside the signed node does not alter its digest.
        target = deepcopy(targets[0])
        for nested in target.findall(".//" + _DS + "Signature"):
            parent = nested.getparent()
            if parent is not None and nested.findtext(_DS + "SignatureValue") == value:
                parent.remove(nested)
        digest = base64.b64encode(hashlib.sha1(
            etree.tostring(target, method="c14n", exclusive=False),
        ).digest()).decode("ascii")
        if digest != reference.findtext(_DS + "DigestValue"):
            raise FiscalValidationError("Jundiai XMLDSig digest does not match fiscal XML")
        try:
            pub.verify(
                base64.b64decode(value, validate=True),
                etree.tostring(signed_info, method="c14n", exclusive=False),
                padding.PKCS1v15(), hashes.SHA1(),
            )
        except (InvalidSignature, ValueError, TypeError):
            raise FiscalValidationError("Jundiai XMLDSig cryptographic validation failed") from None


@dataclass(frozen=True, slots=True)
class _Issuer:
    tenant_id: str
    unit_id: str
    issuer_cnpj: str
    profile_id: str
    profile_version: int
    tax_regime: int
    municipal_registration: str
    canonical_service_code: str
    item_lista_servico: str
    municipal_taxation_code: str
    iss_exigibility: str
    incidence_ibge: str
    iss_rate: str
    issuer_special_regime: str
    optante_simples: str
    fiscal_incentive: str
    national_service_code: str | None
    # Explicit, source-reviewed classification or null where legally not applicable.
    rtc: dict[str, str] | None

    @classmethod
    def parse(cls, obj: object) -> _Issuer:
        row = _object(obj, set(cls.__dataclass_fields__), "taxpayer policy")
        try:
            if not all(
                isinstance(row[name], str) and 0 < len(row[name].strip()) <= 128
                for name in (
                    "tenant_id", "unit_id", "issuer_cnpj", "profile_id",
                    "municipal_registration", "canonical_service_code",
                    "item_lista_servico", "municipal_taxation_code",
                    "iss_exigibility", "incidence_ibge", "iss_rate",
                    "issuer_special_regime", "optante_simples", "fiscal_incentive",
                )
            ):
                raise ValueError
            Cnpj(row["issuer_cnpj"])
            Decimal(row["iss_rate"])
            if (
                type(row["profile_version"]) is not int or row["profile_version"] < 1
                or type(row["tax_regime"]) is not int
                or row["tax_regime"] not in (1, 2, 3, 4)
                or row["incidence_ibge"] != "3525904"
                or row["national_service_code"] is not None
                and not isinstance(row["national_service_code"], str)
                or row["rtc"] is not None and not isinstance(row["rtc"], dict)
            ):
                raise ValueError
            if row["rtc"] is not None and set(row["rtc"]) != {
                "operation_indicator", "cst", "classification", "fin_nfse",
                "ind_dest", "incidence_ibge", "taxable_base", "ind_final",
                "government_reduction_percent",
            }:
                raise ValueError
        except (TypeError, ValueError, InvalidOperation, FiscalValidationError):
            raise RuntimeConfigurationError("Invalid Jundiai issuer fiscal policy") from None
        return cls(**row)

    def applies(self, request: NfseAuthorizationRequest) -> bool:
        d = request.document
        return (
            d.scope.tenant_id == self.tenant_id
            and d.scope.unit_id == self.unit_id
            and d.issuer.cnpj.value == self.issuer_cnpj
            and d.issuer.profile_id == self.profile_id
            and d.issuer.version == self.profile_version
            and d.issuer.tax_regime.value == self.tax_regime
            and d.issuer.address.jurisdiction.municipality_ibge_code == "3525904"
        )


@dataclass(frozen=True, slots=True)
class JundiaiReviewedStartup:
    wsdl_sha256: str
    xsd_package_sha256: str
    contracts: Mapping[str, JundiaiGissWsdlContract]
    validators: Mapping[str, XmlSchemaValidator]
    municipal_signer: x509.Certificate
    issuers: tuple[_Issuer, ...]

    @classmethod
    def load(cls, manifest_path: str) -> JundiaiReviewedStartup:
        file = Path(manifest_path)
        if not file.is_absolute() or not file.is_file() or file.stat().st_size > 131_072:
            raise RuntimeConfigurationError("Jundiai requires absolute reviewed manifest")
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            raise RuntimeConfigurationError("Invalid Jundiai operator manifest") from None
        spec = _object(data, {
            "mode", "wsdl_file", "wsdl_sha256", "xsd_resources",
            "xsd_package_sha256", "xsd_roots", "service_namespace",
            "method_actions", "municipal_signer_pem",
            "municipal_signer_sha256", "signature_profile", "issuers",
        }, "manifest")
        if (
            spec["mode"] != "reviewed-homologation"
            or spec["signature_profile"] != "rsa-sha1-abrasf-2.04"
            or not isinstance(spec["service_namespace"], str)
            or not spec["service_namespace"].startswith("http")
        ):
            raise RuntimeConfigurationError("Jundiai reviewed Giss contract mode mismatch")
        wsdl = _pinned_file(file.parent, spec["wsdl_file"], spec["wsdl_sha256"])
        try:
            root = etree.fromstring(wsdl, parser=_parser())
            if root.tag != _WSDL + "definitions" or (
                root.get("targetNamespace") != spec["service_namespace"]
            ):
                raise ValueError
            soap_actions = {
                op.get("name"): child.get("soapAction")
                for binding in root.findall(_WSDL + "binding")
                for op in binding.findall(_WSDL + "operation")
                for child in op.findall(_SOAP + "operation")
            }
            actions = _object(spec["method_actions"], set(_METHODS), "SOAP actions")
            if not all(
                isinstance(action, str) and action.startswith("http")
                and soap_actions.get(method) == action
                for method, action in actions.items()
            ):
                raise ValueError
        except (etree.XMLSyntaxError, TypeError, ValueError):
            raise RuntimeConfigurationError("Jundiai WSDL SOAP actions not pinned") from None
        resources = spec["xsd_resources"]
        if not isinstance(resources, dict) or not resources:
            raise RuntimeConfigurationError("Jundiai reviewed XSD package missing")
        package = tuple(
            SchemaResource(
                name=name,
                content=_pinned_file(file.parent, name, digest),
                sha256=digest,
            ) for name, digest in resources.items()
        )
        roots = _object(spec["xsd_roots"], set(_ROOTS), "XSD roots")
        validators: dict[str, XmlSchemaValidator] = {}
        for name, schema_name in roots.items():
            if schema_name not in resources:
                raise RuntimeConfigurationError("Jundiai missing official XSD entrypoint")
            schema = SchemaSet(
                version="giss-abrasf2.04-reviewed",
                root_schema=schema_name,
                resources=package,
                source_uri="https://v2-ws-homologacao.giss.com.br/service-ws/nf/nfse-ws",
            )
            if schema.package_sha256 != spec["xsd_package_sha256"]:
                raise RuntimeConfigurationError("Jundiai reviewed XSD package SHA differs")
            validators[name] = XmlSchemaValidator(schema)
        signer = _pinned_file(
            file.parent, spec["municipal_signer_pem"], spec["municipal_signer_sha256"],
        )
        try:
            certificate = x509.load_pem_x509_certificate(signer)
        except ValueError:
            raise RuntimeConfigurationError("Untrusted Jundiai municipality signer") from None
        issuers_spec = spec["issuers"]
        if not isinstance(issuers_spec, list) or not issuers_spec:
            raise RuntimeConfigurationError("Jundiai requires fiscal issuer review")
        issuers = tuple(_Issuer.parse(entry) for entry in issuers_spec)
        if len({
            (r.tenant_id, r.unit_id, r.issuer_cnpj) for r in issuers
        }) != len(issuers):
            raise RuntimeConfigurationError("Duplicate Jundiai taxpayer policy")
        return cls(
            wsdl_sha256=spec["wsdl_sha256"],
            xsd_package_sha256=spec["xsd_package_sha256"],
            contracts={
                name: JundiaiGissWsdlContract(
                    method=name, action=actions[name],
                    service_namespace=spec["service_namespace"],
                    xsd_package_sha256=spec["xsd_package_sha256"],
                    wsdl_sha256=spec["wsdl_sha256"],
                ) for name in _METHODS
            },
            validators=validators, municipal_signer=certificate, issuers=issuers,
        )

    def build_ports(
        self, application: FiscalApplicationService, vault: EncryptedA1Vault,
    ) -> JundiaiTrustedRuntimePorts:
        def review(request: NfseAuthorizationRequest) -> _Issuer:
            matches = [r for r in self.issuers if r.applies(request)]
            if len(matches) != 1:
                raise FiscalValidationError("Jundiai requires exactly one reviewed taxpayer policy")
            return matches[0]

        def validate_xml(raw: bytes, method: str) -> None:
            if not isinstance(raw, bytes) or not 0 < len(raw) <= _LIMIT:
                raise FiscalValidationError("Jundiai official XML unavailable")
            self.validators[method].validate_document(raw)

        def material(scope: ExecutionScope, issuer: Cnpj) -> tuple[
            rsa.RSAPrivateKey, x509.Certificate,
        ]:
            snapshot = vault.resolve(scope=scope, issuer_cnpj=issuer.value)
            validate_a1_for_issuer(
                snapshot.pkcs12_bytes, snapshot.password,
                issuer_cnpj=issuer, at=datetime.now(UTC),
            )
            key, certificate, _ = pkcs12.load_key_and_certificates(
                snapshot.pkcs12_bytes, snapshot.password,
            )
            if not isinstance(key, rsa.RSAPrivateKey) or certificate is None:
                raise FiscalValidationError("Jundiai requires issuer-scoped A1 RSA")
            return key, certificate

        def sign(scope: ExecutionScope, issuer: Cnpj, raw: bytes, method: str) -> bytes:
            root = etree.fromstring(raw, parser=_parser())
            if root.find(".//" + _DS + "Signature") is not None:
                raise FiscalValidationError("Jundiai XML was already signed")
            key, cert = material(scope, issuer)
            if method == "RecepcionarLoteRps":
                candidates = [
                    n for n in root.iter()
                    if etree.QName(n).localname == "InfDeclaracaoPrestacaoServico"
                ]
                lots = [n for n in root if etree.QName(n).localname == "LoteRps"]
                if len(candidates) != 1 or len(lots) != 1:
                    raise FiscalValidationError("Jundiai original RPS/lot shape incomplete")
                info = candidates[0]
                parent = info.getparent()
                if parent is None:
                    raise FiscalValidationError("Jundiai original RPS parent missing")
                append_nfse_signature(parent, info, key, cert, legacy_abrasf=True)
                append_nfse_signature(root, lots[0], key, cert, legacy_abrasf=True)
            elif method == "ConsultarNfsePorRps":
                # An explicit Id is required for the typed query's signed request.
                root.set("Id", "GissRpsQuery")
                append_nfse_signature(root, root, key, cert, legacy_abrasf=True)
            elif method == "CancelarNfse":
                info = [
                    n for n in root.iter()
                    if etree.QName(n).localname == "InfPedidoCancelamento"
                ]
                if len(info) != 1 or info[0].getparent() is None:
                    raise FiscalValidationError("Jundiai cancellation signature target missing")
                append_nfse_signature(
                    info[0].getparent(), info[0], key, cert, legacy_abrasf=True,
                )
            else:
                raise FiscalValidationError("Unsupported reviewed Giss signature method")
            return etree.tostring(root, encoding="utf-8", xml_declaration=True)

        def verify(scope: ExecutionScope, issuer: Cnpj, raw: bytes, method: str) -> None:
            validate_xml(raw, method)
            _, cert = material(scope, issuer)
            _verify_signature(
                raw, certificate=cert, count=2 if method == "RecepcionarLoteRps" else 1,
            )

        def fields(
            req: NfseAuthorizationRequest, source: Sp4OriginalRps,
        ) -> JundiaiGissTaxFields:
            policy = review(req)
            doc = req.document
            taker = doc.service_taker
            if (
                source.issuer_ibge != "3525904"
                or source.issuer_cnpj != doc.issuer.cnpj
                or len(doc.services) != 1
                or doc.services[0].municipal_service_code != policy.canonical_service_code
                or taker is None or taker.tax_id is None
                or not isinstance(taker.address, FiscalAddress)
            ):
                raise FiscalValidationError("Jundiai reviewed fiscal source or taker missing")
            addr = taker.address
            rtc = policy.rtc
            return JundiaiGissTaxFields(
                municipal_registration=policy.municipal_registration,
                item_lista_servico=policy.item_lista_servico,
                municipal_taxation_code=policy.municipal_taxation_code,
                iss_exigibility=policy.iss_exigibility,
                incidence_ibge=policy.incidence_ibge,
                iss_rate=Decimal(policy.iss_rate),
                issuer_special_regime=policy.issuer_special_regime,
                optante_simples=policy.optante_simples,
                fiscal_incentive=policy.fiscal_incentive,
                recipient=JundiaiGissRecipient(
                    tax_id=taker.tax_id.value, name=taker.legal_name,
                    street=addr.street, street_number=addr.number,
                    district=addr.district,
                    city_ibge=addr.jurisdiction.municipality_ibge_code or "",
                    state=addr.jurisdiction.state_code, postal_code=addr.postal_code,
                    municipal_registration=taker.municipal_registration,
                ),
                national_service_code=policy.national_service_code,
                operation_indicator=rtc["operation_indicator"] if rtc else None,
                rtc_cst=rtc["cst"] if rtc else None,
                rtc_classification=rtc["classification"] if rtc else None,
                rtc_fin_nfse=rtc["fin_nfse"] if rtc else None,
                rtc_ind_dest=rtc["ind_dest"] if rtc else None,
                rtc_incidence_ibge=rtc["incidence_ibge"] if rtc else None,
                rtc_taxable_base=Decimal(rtc["taxable_base"]) if rtc else None,
                rtc_ind_final=rtc["ind_final"] if rtc else None,
                rtc_government_reduction_percent=(
                    Decimal(rtc["government_reduction_percent"]) if rtc else None
                ),
            )

        def build_operation(
            req: NfseAuthorizationRequest, source: Sp4OriginalRps, method: str,
        ) -> JundiaiSignedOperation:
            issuer = source.issuer_cnpj
            scope = source.scope
            factory = build_jundiai_giss_issue_request_factory(
                resolve_issue_fields=fields,
                resolve_municipal_registration=lambda _scope, _cnpj: (
                    review(req).municipal_registration
                ),
                sign_issue=lambda raw: sign(scope, issuer, raw, "RecepcionarLoteRps"),
                validate_signed_issue=lambda raw: verify(
                    scope, issuer, raw, "RecepcionarLoteRps",
                ),
                sign_rps_query=lambda raw: sign(scope, issuer, raw, "ConsultarNfsePorRps"),
                validate_signed_query=lambda raw: verify(
                    scope, issuer, raw, "ConsultarNfsePorRps",
                ),
            )
            return factory(req, source, method)

        def source_check(source: Sp4OriginalRps) -> None:
            if (
                source.issuer_ibge != "3525904"
                or not source.municipal_batch_id
                or not source.rps_series
            ):
                raise FiscalValidationError("Jundiai original reserved RPS unavailable")

        def invoice_check(invoice: Sp4VerifiedInvoice) -> None:
            if invoice.issuer_ibge != "3525904":
                raise FiscalValidationError("Jundiai official invoice city differs")
            validate_xml(invoice.authorized_xml, "ConsultarNfseRpsResposta")
            # The official XMLDSig must be verified against the separately
            # pinned municipal signing certificate, never the issuer's A1.
            root = etree.fromstring(invoice.authorized_xml, parser=_parser())
            signed_note = [
                n for n in root.iter() if etree.QName(n).localname == "CompNfse"
            ]
            if len(signed_note) != 1:
                raise FiscalValidationError("Jundiai official invoice wrapper invalid")
            _verify_signature(
                etree.tostring(signed_note[0], encoding="utf-8"),
                certificate=self.municipal_signer, count=1,
            )

        def validate_transport_xml(raw: bytes, xsd_sha: str, wsdl_sha: str) -> None:
            """Match the exact pinned official XML root and transport hashes."""
            if xsd_sha != self.xsd_package_sha256 or wsdl_sha != self.wsdl_sha256:
                raise FiscalValidationError("Unpinned Jundiai fiscal transport contract")
            try:
                root = etree.fromstring(raw, parser=_parser())
            except etree.XMLSyntaxError:
                raise FiscalValidationError("Malformed Jundiai transport XML") from None
            by_root = {
                "EnviarLoteRpsEnvio": "RecepcionarLoteRps",
                "ConsultarNfseRpsEnvio": "ConsultarNfsePorRps",
                "CancelarNfseEnvio": "CancelarNfse",
            }
            operation = by_root.get(etree.QName(root).localname)
            if operation is None:
                raise FiscalValidationError("Unexpected Jundiai fiscal XML operation")
            validate_xml(raw, operation)

        def source_identity(source: Sp4OriginalRps, raw: bytes) -> None:
            try:
                root = etree.fromstring(raw, parser=_parser())
            except etree.XMLSyntaxError:
                raise FiscalValidationError("Malformed Jundiai signed RPS XML") from None
            method = {
                "EnviarLoteRpsEnvio": "RecepcionarLoteRps",
                "ConsultarNfseRpsEnvio": "ConsultarNfsePorRps",
            }.get(etree.QName(root).localname)
            if method is None:
                raise FiscalValidationError("Unrecognized Jundiai RPS method")
            verify(source.scope, source.issuer_cnpj, raw, method)

        transport = build_jundiai_trusted_transport(
            application=application, vault=vault,
            contract_for_method=lambda method: self.contracts[method],
            validate_signed_xml=validate_transport_xml,
        )
        def fiscal_policy(request: NfseAuthorizationRequest) -> None:
            review(request)

        def validate_official_cancel(raw: bytes) -> None:
            validate_xml(raw, "CancelarNfseResposta")
            root = etree.fromstring(raw, parser=_parser())
            verified = [
                n for n in root.iter()
                if isinstance(n.tag, str)
                and etree.QName(n).localname == "NfseCancelamento"
            ]
            if len(verified) > 1:
                raise FiscalValidationError("Ambiguous Giss municipal cancellation proof")
            if verified:
                _verify_signature(
                    etree.tostring(verified[0], encoding="utf-8"),
                    certificate=self.municipal_signer, count=1,
                )

        def verified_cancel(
            request: NfseAuthorizationRequest, source: Sp4OriginalRps,
            invoice: Sp4VerifiedInvoice, reason_code: str,
        ) -> JundiaiGissCancellationDecision:
            if (
                source.issuer_cnpj != request.document.issuer.cnpj
                or source.issuer_ibge != "3525904"
                or invoice.issuer_cnpj != source.issuer_cnpj
                or invoice.invoice_number != invoice.invoice_reference
                or source.scope.identity_partition_key
                != request.document.scope.identity_partition_key
            ):
                raise FiscalValidationError("Invalid original Jundiai approved cancellation")
            policy = review(request)
            scope, issuer = source.scope, source.issuer_cnpj
            payload = prepare_jundiai_cancel(
                source=source, issued=invoice,
                regime=request.document.issuer.tax_regime,
                cancel_code=reason_code,
                signature_reference_id="GissCancel" + invoice.invoice_number,
                municipal_registration=policy.municipal_registration,
                human_approved=True,
                sign_document=lambda raw: sign(scope, issuer, raw, "CancelarNfse"),
                validate_signed_request=lambda raw: verify(
                    scope, issuer, raw, "CancelarNfse",
                ),
            )
            result = transport.invoke(payload)
            return verify_jundiai_cancel_reply(
                receipt=result, source=source, issued=invoice,
                code=reason_code, validate_official_response=validate_official_cancel,
            )

        def query_verified_cancel(
            request: NfseAuthorizationRequest, source: Sp4OriginalRps,
            invoice: Sp4VerifiedInvoice,
        ) -> JundiaiGissCancellationDecision:
            if (
                request.document.issuer.cnpj != source.issuer_cnpj
                or invoice.issuer_cnpj != source.issuer_cnpj
                or invoice.issuer_ibge != "3525904"
            ):
                raise FiscalValidationError("Jundiai cancellation recovery scope differs")
            prepared = build_operation(request, source, "ConsultarNfsePorRps")
            result = transport.invoke(prepared)

            def check_query(raw: bytes) -> None:
                validate_xml(raw, "ConsultarNfseRpsResposta")

            def check_cancel_note(raw: bytes) -> None:
                _verify_signature(
                    raw, certificate=self.municipal_signer, count=1,
                )

            return verify_jundiai_cancel_query(
                receipt=result, source=source, issued=invoice,
                validate_official_query=check_query,
                verify_cancelled_note=check_cancel_note,
            )

        return JundiaiTrustedRuntimePorts(
            transport=transport, build_signed_operation=build_operation,
            verify_signed_rps_identity=source_identity,
            fiscal_issuer_policy=fiscal_policy,
            validate_prepared_rps=source_check,
            verify_official_invoice_xml=invoice_check,
            submit_verified_cancel=verified_cancel,
            query_verified_cancel=query_verified_cancel,
        )


def build_jundiai_port_builder_from_environ(
    environ: Mapping[str, str], *, vault: EncryptedA1Vault | None,
) -> Callable[[FiscalApplicationService], JundiaiTrustedRuntimePorts] | None:
    manifest = environ.get(_ENV, "").strip()
    if not manifest:
        return None
    if vault is None:
        raise RuntimeConfigurationError("Jundiai requested without canonical A1 vault")
    reviewed = JundiaiReviewedStartup.load(manifest)
    return lambda application: reviewed.build_ports(application, vault)
