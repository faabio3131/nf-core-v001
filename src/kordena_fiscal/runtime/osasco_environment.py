"""Operator-reviewed Osasco runtime provisioning on the existing fiscal UoW.

The manifest is a non-secret on-host artifact. It pins local WSDL and XSD bytes,
explicit fiscal classifications and taxpayer scope. No implicit fallback,
download at boot, browser credential, or additional fiscal application.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from lxml import etree

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import FiscalValidationError, MunicipalRegistration, TaxRegimeCode
from kordena_fiscal.gateway.osasco_rtc_issue_builder import OsascoReviewedCartorioValues
from kordena_fiscal.gateway.osasco_rtc_tax_policy import OsascoReviewedRtcPolicy
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps, Sp4VerifiedInvoice
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.persistence.ports import FiscalUnitOfWorkFactory
from kordena_fiscal.vault.contracts import SecretResolutionService
from kordena_fiscal.xml.schema import XmlSchemaValidationError, XmlSchemaValidator

from .config import RuntimeConfigurationError
from .osasco_official_schema import compile_osasco_official_xsd
from .osasco_operational_composition import OsascoTrustedRuntimePorts
from .osasco_pinned_composition import (
    OsascoReviewedSchemaPorts,
    build_osasco_pinned_operational_ports,
)
from .osasco_wsdl_contract import OsascoPinnedWcfWsdl, load_osasco_pinned_wsdl

_ENV = "NFCORE_OSASCO_WCF_CONFIG_PATH"
_LIMIT = 2_097_152
_SCHEMA_NAMES = frozenset({
    "issue_request", "query_request", "cancel_request",
    "full_invoice_response", "cancel_response",
})
_POLICY_NUMBERS = frozenset({
    "iss_rate", "pis", "cofins", "csll", "income_tax", "inss", "other_taxes",
    "pis_own", "cofins_own",
})
_POLICY_DATES = frozenset({"effective_from", "effective_through"})


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeConfigurationError("Duplicate reviewed Osasco manifest field")
        result[key] = value
    return result


def _object(value: object, expected: set[str], kind: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise RuntimeConfigurationError("Invalid reviewed Osasco " + kind)
    return value


def _read_pinned(directory: Path, spec: object) -> bytes:
    obj = _object(spec, {"file", "sha256"}, "artifact")
    filename = obj["file"]
    digest = obj["sha256"]
    if (
        not isinstance(filename, str) or not filename
        or not isinstance(digest, str) or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)
        or Path(filename).is_absolute() or Path(filename).name != filename
    ):
        raise RuntimeConfigurationError("Unsafe Osasco reviewed artifact reference")
    path = directory / filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _LIMIT:
        raise RuntimeConfigurationError("Osasco pinned artifact is unavailable")
    content = path.read_bytes()
    if not content or hashlib.sha256(content).hexdigest() != digest:
        raise RuntimeConfigurationError("Osasco approved artifact digest mismatch")
    return content


def _schema(raw: bytes) -> etree.XMLSchema:
    try:
        root = etree.fromstring(
            raw, parser=etree.XMLParser(
                resolve_entities=False, load_dtd=False, no_network=True,
                huge_tree=False,
            ),
        )
        if bool(getattr(root.getroottree().docinfo, "doctype", "")):
            raise ValueError
        return etree.XMLSchema(root)
    except (etree.XMLSyntaxError, etree.XMLSchemaParseError, ValueError):
        raise RuntimeConfigurationError("Invalid pinned Osasco XSD") from None


def _policy(raw: object) -> OsascoReviewedRtcPolicy:
    names = {field.name for field in fields(OsascoReviewedRtcPolicy)}
    optional = {"pis_own", "cofins_own", "cartorio_values"}
    if not isinstance(raw, dict) or not (names - optional).issubset(raw) or (
        set(raw) - names
    ):
        raise RuntimeConfigurationError("Invalid reviewed Osasco tax policy")
    data = raw
    typed: dict[str, Any] = {}
    try:
        for key, value in data.items():
            if key in _POLICY_DATES:
                typed[key] = date.fromisoformat(value) if value is not None else None
            elif key == "cartorio_values":
                if value is None:
                    typed[key] = None
                else:
                    notary = _object(
                        value, set(OsascoReviewedCartorioValues.__dataclass_fields__),
                        "notary tax deductions",
                    )
                    if any(not isinstance(item, str) for item in notary.values()):
                        raise ValueError
                    amounts = {
                        name: Decimal(item) for name, item in notary.items()
                    }
                    if any(
                        not amount.is_finite() or amount < 0
                        or amount >= Decimal("1000000000000")
                        or amount * 100 != (amount * 100).to_integral_value()
                        for amount in amounts.values()
                    ):
                        raise ValueError
                    typed[key] = OsascoReviewedCartorioValues(**amounts)
            elif key in _POLICY_NUMBERS:
                if not isinstance(value, str):
                    raise ValueError
                typed[key] = Decimal(value)
            else:
                typed[key] = value
        return OsascoReviewedRtcPolicy(**typed)
    except (ValueError, TypeError, ArithmeticError, FiscalValidationError):
        raise RuntimeConfigurationError("Invalid reviewed Osasco tax classification") from None


@dataclass(frozen=True, slots=True)
class _ScopedPolicy:
    tenant_id: str
    unit_id: str
    issuer_cnpj: str
    municipal_registration: str
    policy: OsascoReviewedRtcPolicy

    @classmethod
    def parse(cls, item: object) -> _ScopedPolicy:
        row = _object(
            item, {"tenant_id", "unit_id", "issuer_cnpj", "municipal_registration", "policy"},
            "issuer policy",
        )
        identifiers = [row[key] for key in (
            "tenant_id", "unit_id", "issuer_cnpj", "municipal_registration",
        )]
        if (
            not all(isinstance(value, str) and 0 < len(value) <= 128 for value in identifiers)
            or any("*" in value or value.strip() != value for value in identifiers)
            or len(row["issuer_cnpj"]) != 14 or not row["issuer_cnpj"].isdigit()
        ):
            raise RuntimeConfigurationError("Invalid Osasco taxpayer policy scope")
        return cls(
            tenant_id=row["tenant_id"], unit_id=row["unit_id"],
            issuer_cnpj=row["issuer_cnpj"],
            municipal_registration=MunicipalRegistration(
                row["municipal_registration"]
            ).number,
            policy=_policy(row["policy"]),
        )

    def applies(self, request: NfseAuthorizationRequest) -> bool:
        issuer = request.document.issuer
        scope = request.document.scope
        return (
            scope.tenant_id == self.tenant_id
            and scope.unit_id == self.unit_id
            and issuer.cnpj.value == self.issuer_cnpj
            and issuer.municipal_registration is not None
            and issuer.municipal_registration.number == self.municipal_registration
            and issuer.tax_regime is TaxRegimeCode.NORMAL
            and issuer.address.jurisdiction.municipality_ibge_code == "3534401"
            and self.policy.effective_from <= request.document.competence_date
            and (
                self.policy.effective_through is None
                or request.document.competence_date <= self.policy.effective_through
            )
        )


@dataclass(frozen=True, slots=True)
class OsascoReviewedStartup:
    wsdl: OsascoPinnedWcfWsdl
    schemas: Mapping[str, etree.XMLSchema | XmlSchemaValidator]
    issuers: tuple[_ScopedPolicy, ...]

    @classmethod
    def load(cls, manifest_path: str) -> OsascoReviewedStartup:
        path = Path(manifest_path)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise RuntimeConfigurationError("Osasco reviewed manifest must be a local file")
        if not 0 < path.stat().st_size <= _LIMIT:
            raise RuntimeConfigurationError("Osasco reviewed manifest is invalid")
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique)
        except (UnicodeError, ValueError, OSError):
            raise RuntimeConfigurationError("Unreadable Osasco reviewed manifest") from None
        base_fields = {"wsdl", "binding_name", "issuers"}
        if not isinstance(manifest, dict) or set(manifest) not in (
            base_fields | {"schemas"},
            base_fields | {"official_xsd_package"},
        ):
            raise RuntimeConfigurationError("Incomplete Osasco official XSD/manifest")
        doc = manifest
        if not isinstance(doc["binding_name"], str):
            raise RuntimeConfigurationError("Missing reviewed Osasco WSDL binding")
        wsdl_spec = _object(doc["wsdl"], {"file", "sha256"}, "WSDL")
        wsdl = load_osasco_pinned_wsdl(
            document=_read_pinned(path.parent, wsdl_spec),
            expected_sha256=wsdl_spec["sha256"],
            binding_name=doc["binding_name"],
        )
        schemas: dict[str, etree.XMLSchema | XmlSchemaValidator]
        if "official_xsd_package" in doc:
            package = doc["official_xsd_package"]
            if not isinstance(package, dict) or set(package) != {
                f"inline-xsd-{index:03}.xsd" for index in range(6)
            }:
                raise RuntimeConfigurationError("Six original official Osasco XSDs required")
            try:
                official_validator = compile_osasco_official_xsd({
                    name: _read_pinned(path.parent, spec)
                    for name, spec in package.items()
                })
            except (FiscalValidationError, XmlSchemaValidationError) as exc:
                raise RuntimeConfigurationError(
                    "Official municipal XSD package cannot be compiled"
                ) from exc
            schemas = {name: official_validator for name in _SCHEMA_NAMES}
        else:
            if not isinstance(doc["schemas"], dict) or set(doc["schemas"]) != _SCHEMA_NAMES:
                raise RuntimeConfigurationError("Incomplete Osasco XSD review matrix")
            schemas = {
                name: _schema(_read_pinned(path.parent, spec))
                for name, spec in doc["schemas"].items()
            }
        if not isinstance(doc["issuers"], list) or not doc["issuers"]:
            raise RuntimeConfigurationError("Reviewed Osasco taxpayer scope required")
        issuers = tuple(_ScopedPolicy.parse(row) for row in doc["issuers"])
        scopes = [(x.tenant_id, x.unit_id, x.issuer_cnpj) for x in issuers]
        if len(scopes) != len(set(scopes)):
            raise RuntimeConfigurationError("Duplicate Osasco taxpayer fiscal policy")
        return cls(wsdl, schemas, issuers)

    def build_ports(
        self, application: FiscalApplicationService,
        unit_of_work_factory: FiscalUnitOfWorkFactory,
        secrets: SecretResolutionService,
    ) -> OsascoTrustedRuntimePorts:
        def validate_schema(name: str, raw: bytes) -> None:
            if not isinstance(raw, bytes) or not 0 < len(raw) <= _LIMIT:
                raise FiscalValidationError("Invalid Osasco bounded fiscal XML")
            try:
                root = etree.fromstring(
                    raw, parser=etree.XMLParser(
                        resolve_entities=False, load_dtd=False, no_network=True,
                        huge_tree=False,
                    ),
                )
                if bool(getattr(root.getroottree().docinfo, "doctype", "")):
                    raise ValueError
                selected = self.schemas[name]
                if isinstance(selected, XmlSchemaValidator):
                    if name in ("full_invoice_response", "cancel_response"):
                        soap = "{http://schemas.xmlsoap.org/soap/envelope/}"
                        expected = (
                            "ConsultarNotaCompletaResponse"
                            if name == "full_invoice_response" else "CancelarResponse"
                        )
                        bodies = root.findall(soap + "Body")
                        if (
                            root.tag != soap + "Envelope" or len(bodies) != 1
                            or len(bodies[0]) != 1
                            or bodies[0][0].tag != "{http://tempuri.org/}" + expected
                        ):
                            raise FiscalValidationError(
                                "Official Osasco SOAP method and result differ"
                            )
                        root = bodies[0][0]
                    else:
                        expected = {
                            "issue_request": "RTC_EmitirNFE",
                            "query_request": "ConsultarNotaCompleta",
                            "cancel_request": "Cancelar",
                        }[name]
                        if root.tag != "{http://tempuri.org/}" + expected:
                            raise FiscalValidationError("Wrong Osasco WCF request")
                    selected.validate_document(etree.tostring(root))
                else:
                    selected.assertValid(root)
            except (
                ValueError, etree.XMLSyntaxError, etree.DocumentInvalid,
                XmlSchemaValidationError,
            ):
                raise FiscalValidationError("Osasco XML differs from reviewed XSD") from None

        def policy_for(
            request: NfseAuthorizationRequest, original: Sp4OriginalRps | None = None,
        ) -> OsascoReviewedRtcPolicy:
            rows = [row for row in self.issuers if row.applies(request)]
            if len(rows) != 1:
                raise FiscalValidationError("No unique reviewed Osasco fiscal policy")
            if original is not None and (
                original.scope.identity_partition_key
                != request.document.scope.identity_partition_key
                or original.issuer_cnpj != request.document.issuer.cnpj
            ):
                raise FiscalValidationError("Osasco original RPS scope mismatch")
            return rows[0].policy

        def reviewed_issuer_policy(request: NfseAuthorizationRequest) -> None:
            policy_for(request)

        def verify_cancellation(
            raw: bytes, original: Sp4OriginalRps, invoice: Sp4VerifiedInvoice,
        ) -> bool | None:
            validate_schema("cancel_response", raw)
            if (
                original.issuer_ibge != "3534401"
                or original.issuer_cnpj != invoice.issuer_cnpj
                or original.rps_number != invoice.rps_number
                or original.rps_series != invoice.rps_series
                or original.gross_amount != invoice.gross_amount
                or original.competence_date != invoice.competence_date
            ):
                raise FiscalValidationError("Osasco cancellation source invoice differs")
            # Official v2.2 WCF schema: CancelarResult extends ResponseBase,
            # containing Erro (true=not cancelled; false=success).
            # A 200/empty/ambiguous SOAP response is NOT fiscal confirmation.
            root = etree.fromstring(raw, parser=etree.XMLParser(
                resolve_entities=False, load_dtd=False,
                no_network=True, huge_tree=False,
            ))
            ns = "{http://tempuri.org/}"
            dto = "{http://schemas.datacontract.org/2004/07/Eissnfe.Negocio.WebServices.Mensagem}"
            response = root.find(
                "{http://schemas.xmlsoap.org/soap/envelope/}Body/" + ns + "CancelarResponse"
            )
            if response is None or len(response) != 1:
                return None
            result = response.find(ns + "CancelarResult")
            if result is None:
                return None
            errors = result.findall(dto + "Erro")
            notes = result.findall(dto + "MensagemErro")
            if len(errors) != 1 or len(notes) > 1 or errors[0].text is None:
                return None
            status = errors[0].text.strip().lower()
            message = (notes[0].text or "").strip() if notes else ""
            if status in ("false", "0") and not message:
                return True
            if status in ("true", "1"):
                return False
            return None

        schema = OsascoReviewedSchemaPorts(
            validate_issuance=lambda xml: validate_schema("issue_request", xml),
            validate_query=lambda xml: validate_schema("query_request", xml),
            validate_cancellation=lambda xml: validate_schema("cancel_request", xml),
            verify_full_invoice=lambda invoice: validate_schema(
                "full_invoice_response", invoice.authorized_xml,
            ),
            # A valid response envelope is not enough to confirm a legal cancellation.
            # Only a municipality-reviewed semantic proof adapter can return True.
            verify_cancellation=verify_cancellation,
        )
        return build_osasco_pinned_operational_ports(
            application=application,
            unit_of_work_factory=unit_of_work_factory,
            secrets=secrets, workload_id="nfcore-api",
            wsdl=self.wsdl, schema=schema,
            resolve_policy=lambda request, original: policy_for(request, original),
            fiscal_issuer_policy=reviewed_issuer_policy,
        )


def build_osasco_port_builder_from_environ(
    environ: Mapping[str, str], *,
    secrets_factory: Callable[[FiscalApplicationService], SecretResolutionService] | None,
) -> Callable[[FiscalApplicationService], OsascoTrustedRuntimePorts] | None:
    """Explicit startup config, never a silently discarded municipal provider."""
    manifest = environ.get(_ENV, "").strip()
    if not manifest:
        return None
    if secrets_factory is None:
        raise RuntimeConfigurationError("Osasco requires canonical provider secret authority")
    config = OsascoReviewedStartup.load(manifest)

    def builder(application: FiscalApplicationService) -> OsascoTrustedRuntimePorts:
        return config.build_ports(
            application, application._uow_factory, secrets_factory(application),
        )

    return builder
