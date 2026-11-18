"""Deterministic statutory pre-audit gate for National NFS-e DPS submission.

Runs before the A1 vault is ever touched -- see
``runtime/canonical_fiscal_composition.py::_GovernedNationalNfseGateway``,
whose ``authorize`` calls this gate strictly before delegating to the real
``NfseNacionalHomologationGateway`` (and therefore before any signing key is
read from the vault).

Design note / scope correction
-------------------------------
The originating instruction described this as a "Sentinela Normativo"
pre-audit backed by an external AI client ("Gemini 3.8 Flash"). This module
deliberately does **not** call any generative AI:

* AGENTS.md forbids adding real external secrets/credentials to this
  repository, which a live Gemini (or any other external LLM) call would
  require.
* The same governance document requires that AI never silently decide
  high-impact fiscal configuration on its own, non-deterministic authority;
  gating A1 vault access on a generative model's output would do exactly
  that, and would not be reproducible or auditable.

A second, independent correction was made against the literal wording
during implementation: the official ``CatalogKind.CCLASSTRIB`` table loaded
by ``cognitive/knowledge/official.py`` encodes the *Reforma Tributaria*
(IBS/CBS) unified tax classification, not the LC 116/2003 ISSQN
service-code (cTribNac) taxonomy that the DPS Nacional schema actually
carries. Both happen to be six numeric digits, but they are different
official tables; validating cTribNac against cClassTrib would check it
against the wrong catalog and produce a false sense of assurance rather
than a real one. This gate instead checks cTribNac structurally (LC
116/2003 item/subitem shape) and checks the effective ISS rate against the
LC 116/2003 statutory floor/ceiling -- both deterministic, auditable, and
backed by a citable legal source, independent of any catalog file.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.gateway.nfse_abrasf203_envelope import (
    AbrasfCancellationFacts,
    AbrasfServiceFacts,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest

# LC 116/2003, art. 8 (teto) and art. 8-A (piso, redacao dada pela EC 37/2002):
# statutory ISS rate bounds applicable to every Brazilian municipality.
ISS_RATE_FLOOR = Decimal("2.00")
ISS_RATE_CEILING = Decimal("5.00")
_CENT = Decimal("0.01")


class NfsePreauditRejection(FiscalValidationError):
    """Raised when the deterministic Sentinela Normativo gate blocks a DPS."""


def nfse_preaudit(request: NfseAuthorizationRequest) -> None:
    """Block preventively on cTribNac/ISS-rate divergence before A1 access.

    Performs no mutation and returns ``None`` on success. Raises
    ``NfsePreauditRejection`` (a ``FiscalValidationError``) on any
    divergence; callers must treat any exception from this function as
    "do not sign, do not submit".
    """
    if not isinstance(request, NfseAuthorizationRequest):
        raise FiscalValidationError("nfse_preaudit requires an NfseAuthorizationRequest")

    document = request.document
    if len(document.services) != 1:
        raise NfsePreauditRejection(
            "Sentinela Normativo: a DPS Nacional admite exatamente um "
            "servico por submissao; divida documentos com multiplas linhas"
        )
    service = document.services[0]

    code = service.national_taxation_code
    if code is None or not (len(code) == 6 and code.isdigit()):
        raise NfsePreauditRejection(
            "Sentinela Normativo: cTribNac ausente ou fora do formato "
            "LC 116/2003 (6 digitos numericos)"
        )
    item, subitem = code[0:2], code[2:4]
    if item == "00" or subitem == "00":
        raise NfsePreauditRejection(
            "Sentinela Normativo: cTribNac com item ou subitem LC 116/2003 "
            "invalido (00)"
        )

    taxable = service.taxable_amount.amount
    iss_amount = service.iss_amount.amount
    if taxable < 0 or iss_amount < 0:
        raise NfsePreauditRejection(
            "Sentinela Normativo: valores de base de calculo ou ISS negativos"
        )
    if iss_amount > taxable:
        raise NfsePreauditRejection(
            "Sentinela Normativo: ISS declarado excede a base tributavel do servico"
        )

    # A zero-ISS line can legitimately represent export of service,
    # non-incidence or imunidade, none of which NfseServiceLine models as an
    # explicit flag today. The statutory rate bound is therefore enforced
    # only when ISS is actually being charged, to avoid false rejections of
    # a legitimately untaxed line.
    if taxable > 0 and iss_amount > 0:
        rate = (iss_amount / taxable * 100).quantize(_CENT, rounding=ROUND_HALF_UP)
        if rate < ISS_RATE_FLOOR or rate > ISS_RATE_CEILING:
            raise NfsePreauditRejection(
                f"Sentinela Normativo: aliquota ISS efetiva {rate}% fora da "
                f"faixa legal {ISS_RATE_FLOOR}%-{ISS_RATE_CEILING}% (LC 116/2003)"
            )

def extrema_nfse_preaudit(request: NfseAuthorizationRequest) -> None:
    """Deterministic Sentinela for one Extrema municipal 2.02/RTC request.

    Does not misapply the National DPS cTribNac contract to WebISS. The
    official XSD and the approved Extrema tax intent are independent gates.
    """
    if not isinstance(request, NfseAuthorizationRequest):
        raise NfsePreauditRejection("Municipal preaudit requires a canonical NFS-e request")
    document = request.document
    jurisdiction = document.issuer.address.jurisdiction
    if (
        document.scope.environment.value != "homologation"
        or jurisdiction.state_code != "MG"
        or jurisdiction.municipality_ibge_code != "3125101"
        or document.service_jurisdiction != jurisdiction
        or len(document.services) != 1
    ):
        raise NfsePreauditRejection("Extrema issuer, municipality or scope mismatch")
    service = document.services[0]
    if (
        not service.municipal_service_code
        or not service.source_normative
        or service.taxable_amount.amount <= 0
        or service.iss_amount.amount < 0
        or service.iss_amount.amount > service.taxable_amount.amount
    ):
        raise NfsePreauditRejection("Extrema tax basis or reviewed service is invalid")
    if service.iss_amount.amount > 0:
        rate = (
            service.iss_amount.amount / service.taxable_amount.amount * 100
        ).quantize(_CENT, rounding=ROUND_HALF_UP)
        if not ISS_RATE_FLOOR <= rate <= ISS_RATE_CEILING:
            raise NfsePreauditRejection("Extrema ISS rate is outside approved statutory limits")


def extrema_abrasf_service_preaudit(
    facts: tuple[AbrasfServiceFacts, ...],
) -> None:
    """Check fiscal envelope facts deterministically before A1 is resolved."""
    from datetime import date

    if not facts or not all(isinstance(f, AbrasfServiceFacts) for f in facts):
        raise NfsePreauditRejection("ABRASF service fiscal facts are required")
    for fact in facts:
        try:
            if (
                date.fromisoformat(fact.competence).isoformat() != fact.competence
                or fact.service_municipality != "3125101"
                or (fact.incidence_municipality is not None
                    and fact.incidence_municipality != "3125101")
                or not fact.service_code
                or fact.iss_withheld not in {"1", "2"}
                or fact.iss_rate is None
            ):
                raise ValueError
            rate = Decimal(fact.iss_rate)
            if not rate.is_finite() or not (
                Decimal("0") <= rate <= ISS_RATE_CEILING
            ):
                raise ValueError
            if rate > 0 and rate < ISS_RATE_FLOOR:
                raise ValueError
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise NfsePreauditRejection(
                "Invalid Extrema municipal service, competence or ISS"
            ) from exc


def extrema_cancellation_preaudit(facts: AbrasfCancellationFacts) -> None:
    """Apply official municipal identity/reason invariants before signing."""
    if (
        not isinstance(facts, AbrasfCancellationFacts)
        or facts.municipality_ibge != "3125101"
        or not facts.issuer_cnpj.isdecimal()
        or len(facts.issuer_cnpj) != 14
        or not facts.invoice_number.isdecimal()
        or facts.cancellation_code not in {"1", "2", "3", "4", "5"}
    ):
        raise NfsePreauditRejection(
            "Extrema cancellation requires original municipal invoice and reviewed reason"
        )
