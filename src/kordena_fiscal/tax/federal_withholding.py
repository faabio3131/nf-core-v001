"""Federal withholdings on services (IRRF, PIS, COFINS, CSLL) for the NFS-e tribFed group.

STATUS: implemented from the legislation, PENDING ACCOUNTANT REVIEW (Fábio's
decision of 20/11/2026). A computed result is only a proposal: it reaches the
DPS only as a ``FederalWithholding`` carrying a non-empty ``review_reference``
(the accountant's approval), never automatically.

Rules encoded (RULESET_ID below), all for a legal-entity (PJ) service taker:
- IRRF 1.5%: professional services (RIR/2018 art. 714; Lei 7.450/1985 art. 52).
- IRRF 1.0%: cleaning, conservation, security, surveillance and labor supply
  (RIR/2018 art. 716).
- PIS 0.65% + COFINS 3.0% + CSLL 1.0% = 4.65% (Lei 10.833/2003 art. 30) on the
  services listed there (both categories above).
- Each retention of R$ 10.00 or less is dispensed (Lei 9.430/1996 art. 67 for
  IRRF; Lei 10.833/2003 art. 31 par. 3, as amended by Lei 13.137/2015, for PCC).
- Issuer in the Simples Nacional: no PCC withholding (IN SRF 459/2004 art. 3)
  and no IRRF on these services (IN RFB 765/2007) -> nothing withheld.
Out of scope (blocked, needs the accountant): INSS/CP 11% (cessão de mão de
obra), public-entity takers (IN RFB 1.234/2012), municipal particularities.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from kordena_fiscal.domain import FiscalValidationError

RULESET_ID = "federal-withholding-services-v1"
RULESET_STATUS = "pending_accountant_review"
_CENT = Decimal("0.01")
_DISPENSE = Decimal("10.00")
_PIS, _COFINS, _CSLL = Decimal("0.65"), Decimal("3.00"), Decimal("1.00")
_RET_TYPES = frozenset("0123456789")


class WithholdingCategory(StrEnum):
    PROFESSIONAL = "professional"            # IRRF 1.5% + PCC
    CLEANING_SECURITY_LABOR = "cleaning_security_labor"  # IRRF 1.0% + PCC
    NONE = "none"                            # service not subject to these retentions


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class FederalWithholding:
    """Reviewed values for TCTribFederal. ``review_reference`` is mandatory."""

    base: Decimal
    pis_rate: Decimal
    cofins_rate: Decimal
    pis: Decimal
    cofins: Decimal
    irrf: Decimal
    csll: Decimal
    retention_type: str  # tpRetPisCofins (XSD 1.01)
    review_reference: str
    cst: str = "01"
    ruleset_id: str = RULESET_ID

    def __post_init__(self) -> None:
        for name in ("base", "pis_rate", "cofins_rate", "pis", "cofins", "irrf", "csll"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or value < 0 or value != _money(value):
                raise FiscalValidationError(f"{name} must be a non-negative amount in cents")
        if self.retention_type not in _RET_TYPES:
            raise FiscalValidationError("retention_type must be a tpRetPisCofins code 0-9")
        if not (isinstance(self.cst, str) and len(self.cst) == 2 and self.cst.isdigit()):
            raise FiscalValidationError("cst must have two digits")
        if not isinstance(self.review_reference, str) or not self.review_reference.strip():
            raise FiscalValidationError(
                "federal withholding requires the accountant's review reference"
            )

    @property
    def total(self) -> Decimal:
        return self.pis + self.cofins + self.irrf + self.csll

    def as_payload(self) -> dict[str, str]:
        return {
            "base": str(self.base), "pis_rate": str(self.pis_rate),
            "cofins_rate": str(self.cofins_rate), "pis": str(self.pis),
            "cofins": str(self.cofins), "irrf": str(self.irrf), "csll": str(self.csll),
            "retention_type": self.retention_type, "cst": self.cst,
            "review_reference": self.review_reference, "ruleset_id": self.ruleset_id,
        }


@dataclass(frozen=True, slots=True)
class WithholdingProposal:
    """Unreviewed computation; cannot be put on a DPS as is."""

    base: Decimal
    irrf: Decimal
    pis: Decimal
    cofins: Decimal
    csll: Decimal
    retention_type: str
    reasons: tuple[str, ...]
    ruleset_id: str = RULESET_ID
    status: str = RULESET_STATUS

    def approve(self, review_reference: str) -> FederalWithholding:
        return FederalWithholding(
            base=self.base, pis_rate=_PIS if self.pis else Decimal("0.00"),
            cofins_rate=_COFINS if self.cofins else Decimal("0.00"),
            pis=self.pis, cofins=self.cofins, irrf=self.irrf, csll=self.csll,
            retention_type=self.retention_type, review_reference=review_reference,
        )


def propose_federal_withholding(
    *,
    gross_amount: Decimal,
    taker_is_legal_entity: bool,
    issuer_in_simples_nacional: bool,
    category: WithholdingCategory,
) -> WithholdingProposal:
    if not isinstance(gross_amount, Decimal) or gross_amount <= 0:
        raise FiscalValidationError("gross_amount must be a positive Decimal")
    base = _money(gross_amount)
    zero = Decimal("0.00")
    if not taker_is_legal_entity:
        return WithholdingProposal(base, zero, zero, zero, zero, "0",
                                   ("tomador pessoa física: sem retenção federal",))
    if issuer_in_simples_nacional:
        return WithholdingProposal(base, zero, zero, zero, zero, "0",
                                   ("prestador do Simples Nacional: sem retenção",))
    if category is WithholdingCategory.NONE:
        return WithholdingProposal(base, zero, zero, zero, zero, "0",
                                   ("serviço fora das listas de retenção",))
    reasons: list[str] = []
    irrf_rate = Decimal("1.5") if category is WithholdingCategory.PROFESSIONAL else Decimal("1.0")
    irrf = _money(base * irrf_rate / 100)
    if irrf <= _DISPENSE:
        reasons.append("IRRF de até R$ 10,00 dispensado")
        irrf = zero
    pis, cofins, csll = (_money(base * rate / 100) for rate in (_PIS, _COFINS, _CSLL))
    if pis + cofins + csll <= _DISPENSE:
        reasons.append("PIS/COFINS/CSLL de até R$ 10,00 dispensados")
        pis = cofins = csll = zero
    retention_type = "3" if pis else "0"
    return WithholdingProposal(base, irrf, pis, cofins, csll, retention_type, tuple(reasons))
