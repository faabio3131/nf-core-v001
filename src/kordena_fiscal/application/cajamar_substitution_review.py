"""Cajamar NFS-e substitution eligibility, not a fabricated GeisWeb SOAP action.

Cajamar Decree 7.311/2024, articles 15-B and 15-C (municipal official
gazette 01/10/2024), requires taxpayer substitution via the municipal
electronic system and excludes changes to competence, taker and service value.
No native GeisWeb SubstituirNfse method has been evidenced.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from kordena_fiscal.compliance.cajamar_municipal_legal import cajamar_regular_deadline
from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest

CAJAMAR_SUBSTITUTION_DECREE = (
    "https://cajamar.sp.gov.br/diariooficial/wp-content/uploads/sites/3/1292-1.pdf"
)
CAJAMAR_MUNICIPAL_PORTAL = "https://cajamar.sp.gov.br/fazenda/servicos-online/"
_CAJA_IBGE = "3509205"
_SAO_PAULO = ZoneInfo("America/Sao_Paulo")


@dataclass(frozen=True, slots=True)
class CajamarSubstitutionReview:
    """No fiscal status changes: only the mandatory external portal remains."""

    original_id: str
    replacement_id: str
    deadline: date
    municipal_action: str = "MUNICIPAL_PORTAL_SUBSTITUTION_REQUIRED"
    official_fiscal_confirmation: bool = False
    decree_url: str = CAJAMAR_SUBSTITUTION_DECREE
    portal_url: str = CAJAMAR_MUNICIPAL_PORTAL


def review_cajamar_substitution(
    *, original: NfseAuthorizationRequest,
    replacement: NfseAuthorizationRequest,
    reviewed_at: datetime,
) -> CajamarSubstitutionReview:
    """Validate immutable taxpayer, taker, period and gross amount before review.

    A positive review is NOT a municipal substitution. The official municipal
    system, when available, and separately verified evidence remain authoritative.
    """
    if not (
        isinstance(original, NfseAuthorizationRequest)
        and isinstance(replacement, NfseAuthorizationRequest)
        and isinstance(reviewed_at, datetime)
        and reviewed_at.tzinfo is not None
    ):
        raise FiscalValidationError("Cajamar substitution requires two scoped documents")
    old, new = original.document, replacement.document
    if old.document_id == new.document_id:
        raise FiscalValidationError("Cajamar substitution requires two distinct fiscal documents")
    if (
        old.scope.identity_partition_key != new.scope.identity_partition_key
        or old.issuer.cnpj != new.issuer.cnpj
        or old.issuer.address.jurisdiction.municipality_ibge_code != _CAJA_IBGE
        or old.service_jurisdiction != new.service_jurisdiction
        or old.service_jurisdiction.municipality_ibge_code != _CAJA_IBGE
    ):
        raise FiscalValidationError("Cajamar replacement must preserve tenant, unit and issuer")
    if (
        old.competence_date != new.competence_date
        or old.service_taker != new.service_taker
        or old.service_taker_reference != new.service_taker_reference
        or old.totals.gross_amount != new.totals.gross_amount
        or len(old.services) != 1 or len(new.services) != 1
        or old.services[0].gross_amount != new.services[0].gross_amount
    ):
        raise FiscalValidationError(
            "Cajamar municipal substitution cannot change competence, taker or gross value"
        )
    deadline = cajamar_regular_deadline(old.competence_date)
    if reviewed_at.astimezone(_SAO_PAULO).date() > deadline:
        raise FiscalValidationError(
            "Cajamar substitution period expired; municipal administrative review required"
        )
    return CajamarSubstitutionReview(
        original_id=old.document_id, replacement_id=new.document_id, deadline=deadline,
    )
