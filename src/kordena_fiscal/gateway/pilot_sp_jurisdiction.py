"""Fail-closed logical fiscal routing for the SP accountant pilot.

No credentials, endpoint selection, authorization or provider I/O occurs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    FiscalDocumentKind,
    FiscalValidationError,
)
from kordena_fiscal.domain.profile import TaxRegimeCode

if TYPE_CHECKING:
    from .provider import ProviderOperation

PilotDocument = Literal["nfe", "nfce", "nfse"]
PilotChannel = Literal["sefaz-sp-nfe", "sefaz-sp-nfce", "nfse-national"]
_SP_IBGE = frozenset({"3509205", "3548708", "3550308"})
# MEI service invoices have used the national emitter since CGSN 169/2022.
_NFSE_MEI_CUTOVER = date(2023, 9, 1)
# For ME/EPP optantes Simples, CGSN 191/2026 revoked the Sept/2026 date.
_NFSE_SIMPLES_CUTOVER = date(2026, 11, 1)
_SP_INUTILIZATION_END = date(2026, 11, 1)
_SP_FIXED_OFFSET_2026 = timezone(timedelta(hours=-3))


@dataclass(frozen=True, slots=True)
class SpPilotRoute:
    """Routing intent, NEVER proof of authorization to emit."""

    municipality_ibge_code: str
    document: PilotDocument
    channel: PilotChannel
    requires_external_homologation: bool = True


def resolve_sp_pilot_route(
    *,
    jurisdiction: BrazilianJurisdiction,
    document: PilotDocument,
    tax_regime: TaxRegimeCode,
    competence_date: date,
) -> SpPilotRoute:
    """Classify SP pilot documents; deny unknown regimes/historical NFS-e."""
    if (
        not isinstance(jurisdiction, BrazilianJurisdiction)
        or jurisdiction.state_code != "SP"
        or jurisdiction.municipality_ibge_code not in _SP_IBGE
        or type(tax_regime) is not TaxRegimeCode
        or type(competence_date) is not date
        or document not in ("nfe", "nfce", "nfse")
    ):
        raise FiscalValidationError("unsupported SP pilot fiscal context")
    if document == "nfe":
        channel: PilotChannel = "sefaz-sp-nfe"
    elif document == "nfce":
        channel = "sefaz-sp-nfce"
    elif (
        (tax_regime is TaxRegimeCode.MEI and competence_date >= _NFSE_MEI_CUTOVER)
        or (
            tax_regime in (
                TaxRegimeCode.SIMPLES_NACIONAL,
                TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
            )
            and competence_date >= _NFSE_SIMPLES_CUTOVER
        )
    ):
        # Logical channel only. Provider registration, fiscal review, A1 and
        # municipality-aware transport are still mandatory and independent.
        channel = "nfse-national"
    else:
        raise FiscalValidationError(
            "NFS-e municipality and competence need explicit official eligibility"
        )
    return SpPilotRoute(
        municipality_ibge_code=jurisdiction.municipality_ibge_code,
        document=document,
        channel=channel,
    )



def require_sp_jurisdiction_operation_policy(
    *,
    jurisdiction: BrazilianJurisdiction,
    document_kind: FiscalDocumentKind,
    operation: ProviderOperation,
    requested_at: datetime,
) -> None:
    """Enforce state-level SP fiscal operation policy before provider I/O.

    This negative-only gate applies to every SP municipality and cannot grant
    provider capability, production authority, or fiscal homologation.
    """
    from .provider import ProviderOperation

    if (
        not isinstance(jurisdiction, BrazilianJurisdiction)
        or not isinstance(document_kind, FiscalDocumentKind)
        or type(operation) is not ProviderOperation
        or not isinstance(requested_at, datetime)
        or requested_at.tzinfo is None
        or requested_at.utcoffset() is None
    ):
        raise FiscalValidationError("invalid SP provider operation context")
    if (
        jurisdiction.state_code == "SP"
        and document_kind in (FiscalDocumentKind.NFE, FiscalDocumentKind.NFCE)
        and operation is ProviderOperation.INUTILIZE
        and requested_at.astimezone(_SP_FIXED_OFFSET_2026).date() >= _SP_INUTILIZATION_END
    ):
        raise FiscalValidationError(
            "SP NF-e/NFC-e inutilization no longer applies from 2026-11-01"
        )


def require_sp_pilot_operation_policy(
    *,
    route: SpPilotRoute,
    operation: ProviderOperation,
    requested_at: datetime,
) -> None:
    """Negative gate only: never grants provider or fiscal execution authority.

    The Nov-2026 São Paulo rule stops inutilization of models 55/65. Using an
    aware timestamp (rather than NFS-e competence) prevents historical-competence
    documents from bypassing the current execution policy.
    """
    from .provider import ProviderOperation

    if (
        type(route) is not SpPilotRoute
        or route.municipality_ibge_code not in _SP_IBGE
        or route.document not in ("nfe", "nfce", "nfse")
        or route.channel != {
            "nfe": "sefaz-sp-nfe",
            "nfce": "sefaz-sp-nfce",
            "nfse": "nfse-national",
        }[route.document]
        or type(operation) is not ProviderOperation
        or not isinstance(requested_at, datetime)
        or requested_at.tzinfo is None
        or requested_at.utcoffset() is None
    ):
        raise FiscalValidationError("invalid SP pilot operation context")
    if operation is ProviderOperation.INUTILIZE and route.document == "nfse":
        raise FiscalValidationError("NFS-e inutilization is not a supported operation")
    require_sp_jurisdiction_operation_policy(
        jurisdiction=BrazilianJurisdiction("SP", route.municipality_ibge_code),
        document_kind=FiscalDocumentKind(route.document),
        operation=operation,
        requested_at=requested_at,
    )
