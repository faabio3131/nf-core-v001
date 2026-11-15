"""Santana Simpliss event 101101: reviewed, signed, correlated municipal POST.

This bridge does not generate a fiscal event from a browser request. The
canonical fiscal application must authorize/claim the original cancellation
durably, obtain the signed official-event document, and supply XSD/XMLDSig
validation. A timeout leaves the event unresolved: never resend automatically.
"""
from __future__ import annotations

import base64
import gzip
import json
import ssl
from collections.abc import Callable
from datetime import UTC, datetime

from kordena_fiscal.domain import FiscalDocumentKind, FiscalValidationError
from kordena_fiscal.gateway.fiscal_tls import build_fiscal_tls_context
from kordena_fiscal.gateway.nfse_nacional_event_homologation import (
    NationalNfseCancellationIntent,
    NationalNfseCancellationReceipt,
    _validated_response,
)
from kordena_fiscal.gateway.provider import ProviderSelectionResolver
from kordena_fiscal.gateway.santana_simpliss_homologation import (
    SANTANA_IBGE,
    SANTANA_PROVIDER_ID,
    SantanaSimplissEndpoint,
    SantanaSimplissError,
    _https_exchange,
)
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.a1_preflight import validate_a1_for_issuer


class SantanaSimplissEventTransport:
    """Adapt published Simpliss cancel/event route without claiming a national binding."""

    def __init__(
        self, *, endpoint: SantanaSimplissEndpoint,
        provider_resolver: ProviderSelectionResolver,
        resolve_certificate: Callable[..., EphemeralCertificateMaterial],
        approve_cancellation: Callable[[NationalNfseCancellationIntent], None],
        validate_signed_event: Callable[[bytes], None],
        validate_official_event: Callable[[bytes], None],
        exchange: Callable[
            [str, str, bytes | None, ssl.SSLContext, float], bytes
        ] | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        if (
            not isinstance(endpoint, SantanaSimplissEndpoint)
            or not callable(getattr(provider_resolver, "resolve_provider_id", None))
            or not callable(resolve_certificate)
            or not callable(approve_cancellation)
            or not callable(validate_signed_event)
            or not callable(validate_official_event)
            or not 0 < timeout_seconds <= 30.0
        ):
            raise SantanaSimplissError("Santana event requires complete reviewed authority")
        self._endpoint = endpoint
        self._resolver = provider_resolver
        self._certificate = resolve_certificate
        self._approve = approve_cancellation
        self._validate_signed_event = validate_signed_event
        self._validate_official_event = validate_official_event
        self._exchange = exchange or _https_exchange
        self._timeout = timeout_seconds

    def cancel(
        self, intent: NationalNfseCancellationIntent,
    ) -> NationalNfseCancellationReceipt:
        if not isinstance(intent, NationalNfseCancellationIntent):
            raise SantanaSimplissError("Santana cancellation needs signed canonical intent")
        city = intent.issuer_jurisdiction
        if (
            city.state_code != "SP" or city.municipality_ibge_code != SANTANA_IBGE
            or not intent.scope.host_namespace
        ):
            raise SantanaSimplissError("Santana event has different fiscal municipality")
        provider = self._resolver.resolve_provider_id(
            scope=intent.scope,
            document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=city,
            operation="cancel",
        )
        if provider != SANTANA_PROVIDER_ID:
            raise SantanaSimplissError("Santana event provider binding mismatch")
        self._approve(intent)
        # Caller must validate official event XSD and cryptographic signature.
        self._validate_signed_event(intent.signed_event_xml)
        material = self._certificate(intent.scope, intent.issuer.value)
        validate_a1_for_issuer(
            material.pkcs12_bytes, material.password,
            issuer_cnpj=intent.issuer, at=datetime.now(UTC),
        )
        body = json.dumps({
            "pedidoRegistroEventoXmlGZipB64": base64.b64encode(
                gzip.compress(intent.signed_event_xml, mtime=0),
            ).decode("ascii"),
        }, separators=(",", ":")).encode("ascii")
        response = self._exchange(
            "POST", self._endpoint.events_url(intent.invoice_reference), body,
            build_fiscal_tls_context(material), self._timeout,
        )
        try:
            official = _validated_response(response, intent)
            self._validate_official_event(official)
        except FiscalValidationError:
            raise SantanaSimplissError(
                "Santana event receipt was not officially validated"
            ) from None
        return NationalNfseCancellationReceipt(
            invoice_reference=intent.invoice_reference,
            event_xml=official,
        )
