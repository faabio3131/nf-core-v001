"""Compose Osasco WCF from a pinned WSDL, fiscal policy and existing Vault.

Every dependent callback is independently reviewed; no implicit municipal
activation, guessed RTC tax field, direct browser credential or second fiscal
application is created. This is the operator-facing composition contract.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from lxml import etree

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.gateway.osasco_rtc_tax_policy import (
    OsascoReviewedRtcPolicy,
    build_osasco_reviewed_tax_resolver,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.persistence.ports import FiscalUnitOfWorkFactory
from kordena_fiscal.vault.contracts import SecretResolutionService

from .osasco_operational_composition import (
    OsascoTrustedRuntimePorts,
    build_osasco_trusted_transport,
)
from .osasco_wsdl_contract import OsascoPinnedWcfWsdl
from .sp4_municipal_request_factories import build_osasco_rtc_issue_request_factory

_WCF = "http://tempuri.org/"
_MAX = 2_097_152


@dataclass(frozen=True, slots=True)
class OsascoReviewedSchemaPorts:
    """Official, hash-pinned WCF/XSD validation and document proof adapters."""

    validate_issuance: Callable[[bytes], None]
    validate_query: Callable[[bytes], None]
    validate_cancellation: Callable[[bytes], None]
    verify_full_invoice: Callable[[Sp4VerifiedInvoice], None]
    verify_cancellation: Callable[
        [bytes, Sp4OriginalRps, Sp4VerifiedInvoice], bool | None
    ] | None = None

    def __post_init__(self) -> None:
        if (
            not all(callable(port) for port in (
                self.validate_issuance, self.validate_query,
                self.validate_cancellation, self.verify_full_invoice,
            ))
            or (
                self.verify_cancellation is not None
                and not callable(self.verify_cancellation)
            )
        ):
            raise ValueError("Osasco requires complete official XSD/proof callbacks")


def build_osasco_pinned_operational_ports(
    *,
    application: FiscalApplicationService,
    unit_of_work_factory: FiscalUnitOfWorkFactory,
    secrets: SecretResolutionService,
    workload_id: str,
    wsdl: OsascoPinnedWcfWsdl,
    schema: OsascoReviewedSchemaPorts,
    resolve_policy: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps], OsascoReviewedRtcPolicy
    ],
    fiscal_issuer_policy: Callable[[NfseAuthorizationRequest], None],
) -> OsascoTrustedRuntimePorts:
    """Prepare a single eligible municipal provider; no transport I/O at startup."""
    if (
        not isinstance(application, FiscalApplicationService)
        or not isinstance(wsdl, OsascoPinnedWcfWsdl)
        or not isinstance(schema, OsascoReviewedSchemaPorts)
        or not callable(resolve_policy)
        or not callable(fiscal_issuer_policy)
    ):
        raise ValueError("Reviewed Osasco official municipal dependencies required")
    validators = {
        "RTC_EmitirNFE": schema.validate_issuance,
        "ConsultarNotaCompleta": schema.validate_query,
        "Cancelar": schema.validate_cancellation,
    }

    def validate(raw: bytes, wsdl_sha256: str) -> None:
        if (
            wsdl_sha256 != wsdl.sha256
            or not isinstance(raw, bytes)
            or not 0 < len(raw) <= _MAX
        ):
            raise FiscalValidationError("Osasco municipal request does not match pinned WSDL")
        try:
            root = etree.fromstring(
                raw,
                parser=etree.XMLParser(
                    resolve_entities=False, load_dtd=False, no_network=True,
                ),
            )
        except etree.XMLSyntaxError:
            raise FiscalValidationError("Invalid Osasco reviewed WCF operation XML") from None
        if (
            bool(getattr(root.getroottree().docinfo, "doctype", ""))
            or not isinstance(root.tag, str)
            or not root.tag.startswith("{" + _WCF + "}")
        ):
            raise FiscalValidationError("Unreviewed Osasco WCF XML root")
        name = etree.QName(root).localname
        validator = validators.get(name)
        if validator is None:
            raise FiscalValidationError("Unsupported Osasco municipal fiscal operation")
        validator(raw)

    transport = build_osasco_trusted_transport(
        application=application,
        unit_of_work_factory=unit_of_work_factory,
        secrets=secrets, workload_id=workload_id,
        validate_official_request=validate,
        contract_for_method=wsdl.contract_for_method,
    )
    build_issue = build_osasco_rtc_issue_request_factory(
        resolve_rtc_fields=build_osasco_reviewed_tax_resolver(resolve_policy),
        validate_official_request=lambda raw: validate(raw, wsdl.sha256),
    )

    def valid_rps(original: Sp4OriginalRps) -> None:
        if (
            not isinstance(original, Sp4OriginalRps)
            or original.issuer_ibge != "3534401"
            or original.municipal_batch_id is not None
            or not original.rps_number.isascii()
            or not original.rps_number.isdecimal()
            or not 1 <= len(original.rps_number) <= 15
            or int(original.rps_number) < 1
        ):
            raise FiscalValidationError("Osasco municipal original RPS must be durable")

    def verify_rps_identity(original: Sp4OriginalRps, raw: bytes) -> None:
        valid_rps(original)
        validate(raw, wsdl.sha256)

    return OsascoTrustedRuntimePorts(
        transport=transport,
        build_wcf_operation=build_issue,
        verify_wcf_rps_identity=verify_rps_identity,
        fiscal_issuer_policy=fiscal_issuer_policy,
        validate_prepared_rps=valid_rps,
        verify_official_invoice_xml=schema.verify_full_invoice,
        verify_official_cancel=schema.verify_cancellation,
    )
