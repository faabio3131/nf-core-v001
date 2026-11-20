"""Operator-provisioned GeisWeb startup: one fiscal runtime, zero inferred credentials.

The executable API reads an explicitly reviewed, on-host manifest ONLY when
NFCORE_CAJAMAR_GEISWEB_CONFIG_PATH is configured. The manifest contains no
secrets. It pins local WSDL/XSD artefacts by SHA-256, approved per-issuer
provider-only fiscal classifications and the exact XMLDSig profile.

A1 always comes from NFCore's existing scoped Vault; the canonical
application/provider binding remains the authority for tenant and unit.
No customer or city is activated by default, and no requests go out at boot.
"""
from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.compliance.nfse_preaudit import (
    ISS_RATE_CEILING,
    ISS_RATE_FLOOR,
)
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalAddress, FiscalValidationError
from kordena_fiscal.gateway.cajamar_geisweb_homologation import (
    CajamarGeiswebWsdl,
    CajamarPreparedNfse,
)
from kordena_fiscal.gateway.cajamar_geisweb_issue_builder import CajamarGeiswebIssueData
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps, Sp4VerifiedInvoice
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.runtime.config import RuntimeConfigurationError
from kordena_fiscal.signing.nfse_xmldsig import append_nfse_signature
from kordena_fiscal.vault.a1_preflight import validate_a1_for_issuer
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault
from kordena_fiscal.xml.schema import SchemaResource, SchemaSet, XmlSchemaValidator

from .cajamar_operational_composition import (
    CajamarTrustedRuntimePorts,
    build_cajamar_trusted_transport,
)

_DS = "http://www.w3.org/2000/09/xmldsig#"
_C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
_ENV = "NFCORE_CAJAMAR_GEISWEB_CONFIG_PATH"
_LIMIT = 2_097_152
_ROOTS = frozenset({
    "EnviaLoteRps", "ConsultaLoteRps", "CancelaNfse",
    "ConsultaLoteRpsResposta", "CancelaNfseResposta",
})


def _object(value: object, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise RuntimeConfigurationError("Invalid reviewed Cajamar " + label)
    return value


def _local_file(directory: Path, name: object) -> bytes:
    if (
        not isinstance(name, str) or not name
        or name.startswith(("/", "\\"))
        or ".." in Path(name).parts
        or Path(name).is_absolute()
    ):
        raise RuntimeConfigurationError("Unsafe Cajamar schema/WSDL resource name")
    base = directory.resolve()
    target = (base / name).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise RuntimeConfigurationError("Cajamar reviewed contract file unavailable")
    if target.stat().st_size > _LIMIT:
        raise RuntimeConfigurationError("Oversized Cajamar reviewed contract file")
    return target.read_bytes()


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True,
        huge_tree=False, remove_comments=False,
    )


@dataclass(frozen=True, slots=True)
class _IssuerPolicy:
    tenant_id: str
    unit_id: str
    issuer_cnpj: str
    fiscal_profile_id: str
    fiscal_profile_version: int
    tax_regime: int
    launch_type: str
    geisweb_regime: str
    service_city: str

    @classmethod
    def parse(cls, obj: object) -> _IssuerPolicy:
        row = _object(obj, set(cls.__dataclass_fields__), "issuer policy")
        if (
            not all(isinstance(row[x], str) and row[x].strip()
                    for x in ("tenant_id", "unit_id", "issuer_cnpj",
                              "fiscal_profile_id", "launch_type", "geisweb_regime",
                              "service_city"))
            or type(row["fiscal_profile_version"]) is not int
            or row["fiscal_profile_version"] < 1
            or type(row["tax_regime"]) is not int
            or row["tax_regime"] not in (1, 2, 3, 4)
            or row["launch_type"] not in ("N", "T", "P", "R")
            or row["geisweb_regime"] not in ("1", "2", "4", "6")
            or Cnpj(row["issuer_cnpj"]).value != row["issuer_cnpj"]
        ):
            raise RuntimeConfigurationError("Invalid reviewed Cajamar issuer policy")
        return cls(**row)

    def matches(self, request: NfseAuthorizationRequest) -> bool:
        doc = request.document
        return (
            self.tenant_id == doc.scope.tenant_id
            and self.unit_id == doc.scope.unit_id
            and self.issuer_cnpj == doc.issuer.cnpj.value
            and self.fiscal_profile_id == doc.issuer.profile_id
            and self.fiscal_profile_version == doc.issuer.version
            and self.tax_regime == doc.issuer.tax_regime.value
        )


@dataclass(frozen=True, slots=True)
class CajamarReviewedStartup:
    """Immutable operator contract; supplied file and hashes are never inferred."""

    contract: CajamarGeiswebWsdl
    validators: Mapping[str, XmlSchemaValidator]
    policies: tuple[_IssuerPolicy, ...]
    legacy_rsa_sha1: bool

    @classmethod
    def load(cls, manifest_path: str) -> CajamarReviewedStartup:
        path = Path(manifest_path)
        if not path.is_absolute() or not path.is_file() or path.stat().st_size > 131_072:
            raise RuntimeConfigurationError("Cajamar manifest must be an existing absolute file")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            raise RuntimeConfigurationError("Invalid Cajamar operator manifest") from None
        data = _object(document, {
            "mode", "endpoint", "namespace", "wsdl_file", "wsdl_sha256",
            "xsd_package_sha256", "method_actions", "xsd_resources",
            "xsd_roots", "signature_profile", "issuers",
        }, "operator manifest")
        if data["mode"] != "reviewed-homologation":
            raise RuntimeConfigurationError("Cajamar requires reviewed homologation mode")
        actions = _object(data["method_actions"], {
            "EnviaLoteRps", "ConsultaLoteRps", "ConsultaNfse", "CancelaNfse",
        }, "SOAP actions")
        if not all(isinstance(v, str) for v in actions.values()):
            raise RuntimeConfigurationError("Invalid Cajamar SOAP actions")
        contract = CajamarGeiswebWsdl(
            endpoint=data["endpoint"], namespace=data["namespace"],
            wsdl_sha256=data["wsdl_sha256"],
            xsd_package_sha256=data["xsd_package_sha256"],
            method_actions=dict(actions),
        )
        wsdl = _local_file(path.parent, data["wsdl_file"])
        if hashlib.sha256(wsdl).hexdigest() != contract.wsdl_sha256:
            raise RuntimeConfigurationError("Cajamar WSDL digest differs from reviewed version")
        # Official schema resources are pinned before compilation. References
        # cannot resolve network URLs or path traversal through SchemaSet.
        raw_resources = data["xsd_resources"]
        if not isinstance(raw_resources, dict) or not raw_resources:
            raise RuntimeConfigurationError("Cajamar requires pinned XSD resources")
        resources = tuple(
            SchemaResource(
                name=name,
                content=_local_file(path.parent, name),
                sha256=digest,
            ) for name, digest in raw_resources.items()
        )
        roots = _object(data["xsd_roots"], set(_ROOTS), "XSD entrypoints")
        if not all(isinstance(root, str) and root in raw_resources
                   for root in roots.values()):
            raise RuntimeConfigurationError("Cajamar XSD entrypoint is missing")
        validators: dict[str, XmlSchemaValidator] = {}
        for operation, root in roots.items():
            schema = SchemaSet(
                version="geisweb-reviewed", root_schema=root,
                resources=resources, source_uri=contract.endpoint,
            )
            if schema.package_sha256 != contract.xsd_package_sha256:
                raise RuntimeConfigurationError("Cajamar XSD package digest mismatch")
            validators[operation] = XmlSchemaValidator(schema)
        signature = data["signature_profile"]
        if signature not in ("rsa-sha256-enveloped-document", "rsa-sha1-enveloped-document"):
            raise RuntimeConfigurationError("Cajamar XMLDSig profile must be reviewed")
        rows = data["issuers"]
        if not isinstance(rows, list) or not rows:
            raise RuntimeConfigurationError("Cajamar needs explicit issuer-specific fiscal policy")
        policies = tuple(_IssuerPolicy.parse(row) for row in rows)
        identities = {(p.tenant_id, p.unit_id, p.issuer_cnpj) for p in policies}
        if len(identities) != len(policies):
            raise RuntimeConfigurationError("Duplicate Cajamar operator issuer policy")
        return cls(
            contract=contract, validators=validators, policies=policies,
            legacy_rsa_sha1=signature == "rsa-sha1-enveloped-document",
        )

    def _policy(self, request: NfseAuthorizationRequest) -> _IssuerPolicy:
        matches = [p for p in self.policies if p.matches(request)]
        if len(matches) != 1:
            raise FiscalValidationError("Missing exactly scoped reviewed Cajamar fiscal policy")
        return matches[0]

    def build_ports(
        self, application: FiscalApplicationService, vault: EncryptedA1Vault,
    ) -> CajamarTrustedRuntimePorts:
        """Attach one official adapter using the existing application UoW and Vault."""
        from cryptography.hazmat.primitives.serialization import Encoding

        def material(scope: ExecutionScope, issuer: Cnpj) -> tuple[
            rsa.RSAPrivateKey, x509.Certificate,
        ]:
            snapshot = vault.resolve(scope=scope, issuer_cnpj=issuer.value)
            validate_a1_for_issuer(
                snapshot.pkcs12_bytes, snapshot.password, issuer_cnpj=issuer,
                at=datetime.now(UTC),
            )
            key, certificate, _ = pkcs12.load_key_and_certificates(
                snapshot.pkcs12_bytes, snapshot.password,
            )
            if not isinstance(key, rsa.RSAPrivateKey) or certificate is None:
                raise FiscalValidationError("Cajamar requires issuer-bound A1 RSA")
            return key, certificate

        def sign(scope: ExecutionScope, issuer: Cnpj, raw: bytes) -> bytes:
            if not isinstance(raw, bytes) or not 0 < len(raw) <= _LIMIT:
                raise FiscalValidationError("Invalid Cajamar fiscal XML for signing")
            root = etree.fromstring(raw, parser=_parser())
            if root.find(f".//{{{_DS}}}Signature") is not None:
                raise FiscalValidationError("Municipal XML was already signed")
            key, certificate = material(scope, issuer)
            append_nfse_signature(
                root, root, key, certificate,
                legacy_abrasf=self.legacy_rsa_sha1, whole_document=True,
            )
            return etree.tostring(root, encoding="utf-8", xml_declaration=True)

        def validate_xml(raw: bytes, digest: str) -> None:
            if digest != self.contract.xsd_package_sha256:
                raise FiscalValidationError("Cajamar unpinned signed schema")
            if not isinstance(raw, bytes) or not 0 < len(raw) <= _LIMIT:
                raise FiscalValidationError("Missing Cajamar XML evidence")
            node = etree.fromstring(raw, parser=_parser())
            key = etree.QName(node).localname
            schema = self.validators.get(key)
            if schema is None:
                raise FiscalValidationError("Unrecognized Cajamar XML contract root")
            schema.validate_document(raw)

        def verify(scope: ExecutionScope, issuer: Cnpj, raw: bytes) -> None:
            validate_xml(raw, self.contract.xsd_package_sha256)
            document = etree.fromstring(raw, parser=_parser())
            signatures = document.findall(f"{{{_DS}}}Signature")
            if len(signatures) != 1 or len(document.findall(f".//{{{_DS}}}Signature")) != 1:
                raise FiscalValidationError("Cajamar requires one original XMLDSig")
            signature = signatures[0]
            info = signature.find(f"{{{_DS}}}SignedInfo")
            reference = info.find(f"{{{_DS}}}Reference") if info is not None else None
            if (
                info is None or reference is None or reference.get("URI") != ""
                or reference.findtext(f"{{{_DS}}}DigestValue") is None
                or signature.findtext(f"{{{_DS}}}SignatureValue") is None
            ):
                raise FiscalValidationError("Cajamar XMLDSig reference is invalid")
            algorithm = hashes.SHA1() if self.legacy_rsa_sha1 else hashes.SHA256()
            method = f"{{{_DS}}}SignatureMethod"
            digest_method = f"{{{_DS}}}DigestMethod"
            methods = info.findall(method)
            digests = reference.findall(digest_method)
            if (
                len(methods) != 1 or len(digests) != 1
                or methods[0].get("Algorithm") != (
                    _DS + "rsa-sha1" if self.legacy_rsa_sha1
                    else "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
                )
                or digests[0].get("Algorithm") != (
                    _DS + "sha1" if self.legacy_rsa_sha1
                    else "http://www.w3.org/2001/04/xmlenc#sha256"
                )
            ):
                raise FiscalValidationError("Unapproved Cajamar XMLDSig algorithm")
            canonicalization = info.findall(f"{{{_DS}}}CanonicalizationMethod")
            transforms = reference.find(f"{{{_DS}}}Transforms")
            expected = [
                _DS + "enveloped-signature", _C14N,
            ]
            if (
                len(canonicalization) != 1
                or canonicalization[0].get("Algorithm") != _C14N
                or transforms is None
                or [t.get("Algorithm") for t in transforms] != expected
            ):
                raise FiscalValidationError("Cajamar XMLDSig transforms differ")
            cloned = deepcopy(document)
            cloned.remove(cloned.findall(f"{{{_DS}}}Signature")[0])
            content = etree.tostring(cloned, method="c14n", exclusive=False)
            hash_value = hashes.Hash(algorithm)
            hash_value.update(content)
            if base64.b64encode(hash_value.finalize()).decode() != reference.findtext(
                f"{{{_DS}}}DigestValue"
            ):
                raise FiscalValidationError("Cajamar signed XML was modified")
            _, certificate = material(scope, issuer)
            raw_certificate = signature.findtext(
                f"{{{_DS}}}KeyInfo/{{{_DS}}}X509Data/{{{_DS}}}X509Certificate"
            )
            if raw_certificate != base64.b64encode(
                certificate.public_bytes(Encoding.DER),
            ).decode("ascii"):
                raise FiscalValidationError("Cajamar signature is from another taxpayer")
            signed = etree.tostring(info, method="c14n", exclusive=False)
            value = signature.findtext(f"{{{_DS}}}SignatureValue")
            public_key = certificate.public_key()
            if not isinstance(value, str) or not isinstance(public_key, rsa.RSAPublicKey):
                raise FiscalValidationError("Cajamar XMLDSig requires issuer A1 RSA")
            try:
                public_key.verify(
                    base64.b64decode(value, validate=True),
                    signed, padding.PKCS1v15(), algorithm,
                )
            except (InvalidSignature, ValueError, TypeError) as exc:
                raise FiscalValidationError("Invalid original Cajamar XMLDSig") from exc

        def check_request(request: NfseAuthorizationRequest) -> None:
            # Keep municipal review distinct from the National DPS cTribNac
            # format: this GeisWeb service uses the municipal service code.
            self._policy(request)
            doc = request.document
            if (
                doc.scope.environment.value != "homologation"
                or doc.issuer.address.jurisdiction.state_code != "SP"
                or doc.issuer.address.jurisdiction.municipality_ibge_code != "3509205"
                or doc.service_jurisdiction != doc.issuer.address.jurisdiction
                or len(doc.services) != 1
            ):
                raise FiscalValidationError("Cajamar scope/issuer/service mismatch")
            service = doc.services[0]
            if (
                not service.municipal_service_code
                or not service.source_normative
                or service.taxable_amount.amount <= 0
                or service.iss_amount.amount < 0
                or service.iss_amount.amount > service.taxable_amount.amount
            ):
                raise FiscalValidationError("Cajamar source tax basis is unavailable")
            if service.iss_amount.amount > 0:
                rate = service.iss_amount.amount * Decimal("100")
                rate /= service.taxable_amount.amount
                if not ISS_RATE_FLOOR <= rate <= ISS_RATE_CEILING:
                    raise FiscalValidationError("Cajamar ISS rate outside reviewed statutory range")

        def issue_fields(
            request: NfseAuthorizationRequest, original: Sp4OriginalRps,
        ) -> CajamarGeiswebIssueData:
            doc = request.document
            policy = self._policy(request)
            taker = doc.service_taker
            if (
                original.issuer_ibge != "3509205"
                or doc.issuer.municipal_registration is None
                or taker is None or taker.tax_id is None
                or not isinstance(taker.address, FiscalAddress)
                or doc.service_jurisdiction != doc.issuer.address.jurisdiction
                or len(doc.services) != 1
            ):
                raise FiscalValidationError("Incomplete reviewed Cajamar issuer/taker")
            line = doc.services[0]
            if line.taxable_amount.amount <= 0:
                raise FiscalValidationError("Cajamar ISS base is required")
            rate = line.iss_amount.amount * Decimal("100") / line.taxable_amount.amount
            exponent = rate.as_tuple().exponent
            if not isinstance(exponent, int) or exponent < -5:
                raise FiscalValidationError("Cajamar ISS rate has unsupported precision")
            return CajamarGeiswebIssueData(
                municipal_registration=doc.issuer.municipal_registration.number,
                service_code=line.municipal_service_code,
                launch_type=policy.launch_type, issuer_regime=policy.geisweb_regime,
                iss_rate=rate, service_city=policy.service_city,
                recipient_tax_id=taker.tax_id.value, recipient_name=taker.legal_name,
                recipient_street=taker.address.street,
                recipient_number=taker.address.number,
                recipient_neighborhood=taker.address.district,
                recipient_city=taker.address.municipality_name,
                recipient_state=taker.address.jurisdiction.state_code,
                recipient_postal_code=taker.address.postal_code,
            )

        def verified_rps(original: Sp4OriginalRps) -> None:
            if (
                not isinstance(original, Sp4OriginalRps)
                or original.issuer_ibge != "3509205"
                or not original.municipal_batch_id
            ):
                raise FiscalValidationError("Original Cajamar fiscal RPS is unavailable")

        def verified_invoice(invoice: Sp4VerifiedInvoice) -> None:
            if invoice.issuer_ibge != "3509205":
                raise FiscalValidationError("Cajamar invoice proof must be municipally scoped")
            validate_xml(invoice.authorized_xml, self.contract.xsd_package_sha256)

        # The request-specific closure is necessary for A1 scope authority.
        def reviewed_operation(
            request: NfseAuthorizationRequest, source: Sp4OriginalRps, method: str,
        ) -> CajamarPreparedNfse:
            from kordena_fiscal.gateway.cajamar_geisweb_issue_builder import (
                prepare_cajamar_signed_issue,
            )
            from kordena_fiscal.gateway.cajamar_geisweb_request_builder import (
                prepare_cajamar_original_lot_query,
            )

            issuer, scope = source.issuer_cnpj, source.scope

            def sign_scoped(raw: bytes) -> bytes:
                return sign(scope, issuer, raw)

            def validate_scoped(raw: bytes) -> None:
                verify(scope, issuer, raw)
            if method == "EnviaLoteRps":
                return prepare_cajamar_signed_issue(
                    request=request, original=source,
                    fields=issue_fields(request, source),
                    sign_document=sign_scoped,
                    validate_signed_request=validate_scoped,
                )
            if method == "ConsultaLoteRps":
                return prepare_cajamar_original_lot_query(
                    source=source, tax_regime=request.document.issuer.tax_regime,
                    sign_document=sign_scoped,
                    validate_signed_request=validate_scoped,
                )
            raise FiscalValidationError("Unknown Cajamar municipal fiscal method")

        transport = build_cajamar_trusted_transport(
            application=application,
            vault=vault,
            pinned_contract=self.contract,
            validate_signed_xml=validate_xml,
        )
        return CajamarTrustedRuntimePorts(
            transport=transport, build_signed_operation=reviewed_operation,
            verify_signed_rps_identity=lambda source, raw: verify(
                source.scope, source.issuer_cnpj, raw,
            ),
            fiscal_issuer_policy=check_request,
            validate_prepared_rps=verified_rps,
            verify_official_invoice_xml=verified_invoice,
            sign_cancel=sign, validate_signed_cancel=verify,
            verify_official_cancel=lambda _scope, _cnpj, raw: validate_xml(
                raw, self.contract.xsd_package_sha256,
            ),
        )


def build_cajamar_port_builder_from_environ(
    environ: Mapping[str, str], *, vault: EncryptedA1Vault | None,
) -> Callable[[FiscalApplicationService], CajamarTrustedRuntimePorts] | None:
    """Read configuration only when explicitly enabled, never auto-discover city."""
    manifest = environ.get(_ENV, "").strip()
    if not manifest:
        return None
    if vault is None:
        raise RuntimeConfigurationError("Cajamar requested without canonical encrypted A1 vault")
    reviewed = CajamarReviewedStartup.load(manifest)
    return lambda application: reviewed.build_ports(application, vault)
