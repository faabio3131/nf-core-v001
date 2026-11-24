"""Fail-closed logical fiscal routing for the SP accountant pilot.

No credentials, endpoint selection, authorization or provider I/O occurs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
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
_NFSE_CUTOVER = date(2026, 11, 1)


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
        competence_date >= _NFSE_CUTOVER
        and tax_regime in (
            TaxRegimeCode.SIMPLES_NACIONAL,
            TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
            TaxRegimeCode.MEI,
        )
    ):
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
    # Since 2026-11-01 SP no longer REQUIRES inutilization, but the official
    # SEFAZ-SP service remains operational during the transition through
    # March 2027. Do not reject a valid request based only on the date.
    # Positive authorization still depends on the configured provider,
    # fiscal identity and its official response; this function grants none.


def require_sp_pilot_operation_policy(
    *,
    route: SpPilotRoute,
    operation: ProviderOperation,
    requested_at: datetime,
) -> None:
    """Negative gate only: never grants provider or fiscal execution authority.

    In SP inutilization of models 55/65 is not mandatory after Nov 2026,
    but municipal date rules cannot deny the SEFAZ service while its official
    transitional endpoint remains available. Provider operation authority
    is governed independently.
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
