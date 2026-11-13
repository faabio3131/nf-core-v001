"""City-specific reviewed preparation factories for existing SP4 driver ports.

No second fiscal engine is introduced: the canonical motor owns service
tax calculation, issue XML, durable source identifiers and policy; these
factories implement the municipality's read-only recovery envelopes using
the same original persisted document. Issuance builders are injected ports.
"""
from __future__ import annotations

from collections.abc import Callable

from kordena_fiscal.domain import ExecutionScope
from kordena_fiscal.gateway.barueri_pmb004_homologation import BarueriRpsBatch
from kordena_fiscal.gateway.barueri_pmb004_record_builder import (
    BarueriPmb004IssueFields,
    build_barueri_reviewed_issue_batch,
)
from kordena_fiscal.gateway.cajamar_geisweb_homologation import CajamarPreparedNfse
from kordena_fiscal.gateway.cajamar_geisweb_issue_builder import (
    CajamarGeiswebIssueData,
    prepare_cajamar_signed_issue,
)
from kordena_fiscal.gateway.cajamar_geisweb_request_builder import (
    prepare_cajamar_original_lot_query,
)
from kordena_fiscal.gateway.jundiai_giss_homologation import JundiaiSignedOperation
from kordena_fiscal.gateway.jundiai_giss_issue_builder import (
    JundiaiGissTaxFields,
    prepare_jundiai_giss_signed_issue,
)
from kordena_fiscal.gateway.jundiai_giss_request_builder import (
    prepare_jundiai_original_rps_query,
)
from kordena_fiscal.gateway.osasco_rtc_homologation import OsascoPreparedOperation
from kordena_fiscal.gateway.osasco_rtc_issue_builder import (
    OsascoRtcTaxFields,
    prepare_osasco_rtc_issue,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest


def build_barueri_pmb004_issue_remittance_factory(
    *,
    resolve_issue_fields: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps], BarueriPmb004IssueFields
    ],
    resolve_municipal_registration: Callable[[ExecutionScope, str], str],
) -> Callable[[NfseAuthorizationRequest, Sp4OriginalRps], BarueriRpsBatch]:
    """Wire verified PMB004 Type 2/4 records into the existing batch driver.

    The trusted original RPS loader determines batch number and identity.
    The fiscal core, not this factory, reviews rates, retention and RTC codes.
    """
    if not callable(resolve_issue_fields) or not callable(resolve_municipal_registration):
        raise Sp4CanonicalMunicipalError("Barueri remittance issuer ports unavailable")

    def prepare(
        request: NfseAuthorizationRequest, source: Sp4OriginalRps,
    ) -> BarueriRpsBatch:
        return build_barueri_reviewed_issue_batch(
            request=request, original=source,
            fields=resolve_issue_fields(request, source),
            municipal_registration=resolve_municipal_registration(
                source.scope, source.issuer_cnpj.value,
            ),
        )

    return prepare

def build_cajamar_reviewed_request_factory(
    *,
    build_signed_issue: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps], CajamarPreparedNfse
    ],
    sign_lot_query: Callable[[bytes], bytes],
    validate_signed_query: Callable[[bytes], None],
) -> Callable[
    [NfseAuthorizationRequest, Sp4OriginalRps, str], CajamarPreparedNfse
]:
    """Compose original-lot recovery and taxpayer-specific emission builder."""
    if not all(callable(x) for x in (
        build_signed_issue, sign_lot_query, validate_signed_query,
    )):
        raise Sp4CanonicalMunicipalError("Cajamar builder ports unavailable")

    def prepare(
        request: NfseAuthorizationRequest, source: Sp4OriginalRps, method: str,
    ) -> CajamarPreparedNfse:
        if method == "EnviaLoteRps":
            return build_signed_issue(request, source)
        if method != "ConsultaLoteRps":
            raise Sp4CanonicalMunicipalError("Unsupported Cajamar issuance/recovery method")
        return prepare_cajamar_original_lot_query(
            source=source, tax_regime=request.document.issuer.tax_regime,
            sign_document=sign_lot_query,
            validate_signed_request=validate_signed_query,
        )

    return prepare



def build_cajamar_geisweb_issue_request_factory(
    *,
    resolve_issue_fields: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps], CajamarGeiswebIssueData
    ],
    sign_issue: Callable[[bytes], bytes],
    validate_signed_issue: Callable[[bytes], None],
    sign_lot_query: Callable[[bytes], bytes],
    validate_signed_query: Callable[[bytes], None],
) -> Callable[
    [NfseAuthorizationRequest, Sp4OriginalRps, str], CajamarPreparedNfse
]:
    """Concrete GeisWeb issue + recovery factory using existing fiscal ports.

    Fiscal policy owns the city-specific issue fields. The builder never
    substitutes a new RPS number, taxpayer, tax amount or signature engine.
    """
    if not all(callable(x) for x in (
        resolve_issue_fields, sign_issue, validate_signed_issue,
        sign_lot_query, validate_signed_query,
    )):
        raise Sp4CanonicalMunicipalError("Cajamar fiscal issue ports unavailable")

    def issue(
        request: NfseAuthorizationRequest, source: Sp4OriginalRps,
    ) -> CajamarPreparedNfse:
        return prepare_cajamar_signed_issue(
            request=request, original=source,
            fields=resolve_issue_fields(request, source),
            sign_document=sign_issue,
            validate_signed_request=validate_signed_issue,
        )

    return build_cajamar_reviewed_request_factory(
        build_signed_issue=issue, sign_lot_query=sign_lot_query,
        validate_signed_query=validate_signed_query,
    )


def build_osasco_rtc_issue_request_factory(
    *,
    resolve_rtc_fields: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps], OsascoRtcTaxFields
    ],
    validate_official_request: Callable[[bytes], None],
) -> Callable[
    [NfseAuthorizationRequest, Sp4OriginalRps, str], OsascoPreparedOperation
]:
    """Prepare Osasco's reviewed 2026 WCF RTC method for the canonical bridge.

    Read-only ConsultarNotaCompleta is separately assembled by the existing
    bridge from the original receipt, with the scoped key injected at transport.
    """
    if not callable(resolve_rtc_fields) or not callable(validate_official_request):
        raise Sp4CanonicalMunicipalError("Osasco RTC issue/schema ports unavailable")

    def prepare(
        request: NfseAuthorizationRequest, source: Sp4OriginalRps, method: str,
    ) -> OsascoPreparedOperation:
        if method != "RTC_EmitirNFE":
            raise Sp4CanonicalMunicipalError("Unsupported Osasco issue method")
        return prepare_osasco_rtc_issue(
            request=request, original=source,
            fields=resolve_rtc_fields(request, source),
            validate_request=validate_official_request,
        )

    return prepare


def build_jundiai_giss_issue_request_factory(
    *,
    resolve_issue_fields: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps], JundiaiGissTaxFields
    ],
    resolve_municipal_registration: Callable[[ExecutionScope, str], str],
    sign_issue: Callable[[bytes], bytes],
    validate_signed_issue: Callable[[bytes], None],
    sign_rps_query: Callable[[bytes], bytes],
    validate_signed_query: Callable[[bytes], None],
) -> Callable[
    [NfseAuthorizationRequest, Sp4OriginalRps, str], JundiaiSignedOperation
]:
    """Compose Giss 2.04 batch emission and nonmutating original-RPS recovery.

    Separate reviewed signer/XSD ports preserve the canonical fiscal engine's
    authority over two-node XMLDSig and the fiscal taxpayer classification.
    """
    if not all(callable(x) for x in (
        resolve_issue_fields, resolve_municipal_registration, sign_issue,
        validate_signed_issue, sign_rps_query, validate_signed_query,
    )):
        raise Sp4CanonicalMunicipalError("Jundiai fiscal issue ports unavailable")

    def issue(
        request: NfseAuthorizationRequest, source: Sp4OriginalRps,
    ) -> JundiaiSignedOperation:
        return prepare_jundiai_giss_signed_issue(
            request=request, original=source,
            fields=resolve_issue_fields(request, source),
            sign_xml=sign_issue, validate_signed_xml=validate_signed_issue,
        )

    return build_jundiai_reviewed_request_factory(
        build_signed_issue=issue,
        resolve_municipal_registration=resolve_municipal_registration,
        sign_rps_query=sign_rps_query,
        validate_signed_query=validate_signed_query,
    )

def build_jundiai_reviewed_request_factory(
    *,
    build_signed_issue: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps], JundiaiSignedOperation
    ],
    resolve_municipal_registration: Callable[[ExecutionScope, str], str],
    sign_rps_query: Callable[[bytes], bytes],
    validate_signed_query: Callable[[bytes], None],
) -> Callable[
    [NfseAuthorizationRequest, Sp4OriginalRps, str], JundiaiSignedOperation
]:
    """Compose Giss 2.04 issuer-scoped RPS query and existing issue builder."""
    if not all(callable(x) for x in (
        build_signed_issue, resolve_municipal_registration,
        sign_rps_query, validate_signed_query,
    )):
        raise Sp4CanonicalMunicipalError("Jundiai builder ports unavailable")

    def prepare(
        request: NfseAuthorizationRequest, source: Sp4OriginalRps, method: str,
    ) -> JundiaiSignedOperation:
        if method == "RecepcionarLoteRps":
            return build_signed_issue(request, source)
        if method != "ConsultarNfsePorRps":
            raise Sp4CanonicalMunicipalError("Unsupported Jundiai issuance/recovery method")
        municipal_registration = resolve_municipal_registration(
            source.scope, source.issuer_cnpj.value,
        )
        return prepare_jundiai_original_rps_query(
            original=source, regime=request.document.issuer.tax_regime,
            municipal_registration=municipal_registration,
            sign_document=sign_rps_query,
            validate_signed_request=validate_signed_query,
        )

    return prepare
