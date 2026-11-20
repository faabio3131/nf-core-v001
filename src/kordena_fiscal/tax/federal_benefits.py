"""T08 federal-benefit coverage and deterministic, conservative candidate screening.

This is not a second tax engine. No inferred tax rate, tax credit, authorisation,
legal eligibility or automatic fiscal configuration is produced here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime

RULE_SCHEMA = "nfcore.federal-benefit-rule/v1"
FACTS_SCHEMA = "nfcore.federal-benefit-facts/v1"
ENGINE_VERSION = "nfcore.federal-benefits/2026-v1"
_CNAE = re.compile(r"[0-9]{7}\Z")
_NCM = re.compile(r"[0-9]{8}\Z")
_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:@+-]{2,127}\Z")


@dataclass(frozen=True, slots=True)
class FederalProgram:
    code: str
    tax_code: str
    legal_act: str
    official_url: str
    operation: str
    minimum_evidence: tuple[str, ...]
    earliest_competence: date


# A source registry is an index to official material, NOT a reviewed rule.
# A named program alone does not establish its current validity or eligibility.
PROGRAMS: dict[str, FederalProgram] = {
    "LEI_DO_BEM": FederalProgram(
        "LEI_DO_BEM", "IRPJ_CSLL", "Lei 11.196/2005, cap. III",
        "https://www.gov.br/mcti/pt-br/acompanhe-o-mcti/lei-do-bem/paginas/legislacao",
        "rd_innovation",
        ("reviewed_rd_project", "reviewed_eligible_expenditure",
         "fiscal_regular_status", "profitability_review"),
        date(2006, 1, 1),
    ),
    "REIDI": FederalProgram(
        "REIDI", "PIS_COFINS", "Lei 11.488/2007",
        "https://www.gov.br/pt-br/servicos/habilitar-empresa-no-regime-especial-de-"
        "incentivos-para-o-desenvolvimento-da-infraestrutura-reidi",
        "infrastructure_project",
        ("approved_infrastructure_project", "reidi_habilitation",
         "reviewed_acquisition_link"),
        date(2007, 6, 15),
    ),
    "IBS_CBS_RURAL": FederalProgram(
        "IBS_CBS_RURAL", "IBS_CBS", "LC 214/2025, arts. 164 e 168",
        "https://www2.camara.leg.br/legin/fed/leicom/2025/"
        "leicomplementar-214-16-janeiro-2025-796905-normaatualizada-pl.html",
        "rural_purchase",
        ("supplier_non_contributor_status", "regular_ibs_cbs_status",
         "reviewed_purchase", "current_rate_source"),
        date(2027, 1, 1),
    ),
    "IBS_CBS_RECICLAGEM": FederalProgram(
        "IBS_CBS_RECICLAGEM", "IBS_CBS", "LC 214/2025, art. 170",
        "https://www2.camara.leg.br/legin/fed/leicom/2025/"
        "leicomplementar-214-16-janeiro-2025-796905-normaatualizada-pl.html",
        "recycling_purchase",
        ("eligible_material_classification", "eligible_supplier_status",
         "regular_ibs_cbs_status", "reviewed_purchase", "current_rate_source"),
        date(2027, 1, 1),
    ),
}


@dataclass(frozen=True, slots=True)
class ReviewedFederalIssuer:
    """Provided by the existing issuer profile and federal-regime authority."""

    cnpj: str
    cnae: str
    regime: FederalIncomeTaxRegime
    scope_identity: tuple[str, ...]


def _reference(value: object) -> bool:
    return isinstance(value, str) and _REFERENCE.fullmatch(value) is not None


def _codes(value: object, pattern: re.Pattern[str], *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 1000 or (
        not allow_empty and not value
    ):
        raise FiscalValidationError("invalid reviewed federal classification list")
    if not all(isinstance(v, str) and pattern.fullmatch(v) for v in value):
        raise FiscalValidationError("invalid reviewed federal classification code")
    if len(set(value)) != len(value):
        raise FiscalValidationError("duplicate federal classification code")
    return tuple(value)


def assess_federal_program(
    *, program: FederalProgram, competence: date, issuer: ReviewedFederalIssuer,
    activity_cnae: str, operation_ncm: str | None, operation: str,
    allowed_regimes: tuple[str, ...], cnae_scope: str, allowed_cnaes: tuple[str, ...],
    ncm_scope: str, allowed_ncms: tuple[str, ...],
    required_evidence: tuple[str, ...], evidence: dict[str, str],
) -> dict[str, Any]:
    """Advisory triage of a reviewed rule; never determines legal entitlement.

    Every program's minimum evidence is mandatory even if the reviewed policy
    happens to omit it. An empty allowlist cannot silently mean 'all'.
    """
    if competence < program.earliest_competence:
        return _outcome("not_applicable", ("program_not_effective",))
    if issuer.regime.value not in allowed_regimes:
        return _outcome("not_applicable", ("federal_regime_excluded",))
    if program.code == "LEI_DO_BEM" and (
        issuer.regime is not FederalIncomeTaxRegime.LUCRO_REAL
    ):
        return _outcome("not_applicable", ("lei_do_bem_lucro_real_required",))
    if operation != program.operation:
        return _outcome("not_applicable", ("operation_excluded",))
    if cnae_scope == "allowlist" and activity_cnae not in allowed_cnaes:
        return _outcome("not_applicable", ("cnae_not_covered",))
    if ncm_scope == "allowlist":
        if operation_ncm is None:
            return _outcome("insufficient_basis", ("ncm_not_reviewed",))
        if operation_ncm not in allowed_ncms:
            return _outcome("not_applicable", ("ncm_not_covered",))
    required = (*program.minimum_evidence, *required_evidence)
    missing = sorted({key for key in required if key not in evidence})
    if missing:
        return _outcome("insufficient_basis", tuple("missing:" + key for key in missing))
    return _outcome("potential", ("accountant_review_required",))


def _outcome(status: str, reasons: tuple[str, ...]) -> dict[str, Any]:
    return {
        "status": status, "reason_codes": list(reasons), "engine_version": ENGINE_VERSION,
        "advisory_only": True, "requires_human_approval": True,
        "issuance_authorized": False, "eligibility_certified": False,
        "approved_cents": None, "realized_cents": None,
        "estimated_cents": None, "dirbi_review_required": status == "potential",
    }


def decode_policy(payload: object) -> tuple[
    FederalProgram, tuple[str, ...], str, tuple[str, ...],
    str, tuple[str, ...], tuple[str, ...],
]:
    if not isinstance(payload, dict) or payload.get("schema_version") != RULE_SCHEMA:
        raise FiscalValidationError("unsupported federal benefit policy")
    if payload.get("review_status") != "reviewed" or not _reference(
        payload.get("review_reference")
    ):
        raise FiscalValidationError("reviewed federal benefit policy required")
    code = payload.get("program_code")
    if not isinstance(code, str):
        raise FiscalValidationError("invalid federal benefit program code")
    program = PROGRAMS.get(code)
    if program is None:
        raise FiscalValidationError("unknown federal benefit program")
    allowed = payload.get("allowed_regimes")
    if not isinstance(allowed, list) or not allowed or not all(
        isinstance(value, str) for value in allowed
    ):
        raise FiscalValidationError("explicit federal regimes required")
    if len(set(allowed)) != len(allowed) or any(
        value not in {item.value for item in FederalIncomeTaxRegime}
        for value in allowed
    ):
        raise FiscalValidationError("invalid reviewed federal regime")
    # Never allow rule metadata to weaken program-specific legal conditions.
    if program.code == "LEI_DO_BEM" and allowed != ["lucro_real"]:
        raise FiscalValidationError("Lei do Bem requires Lucro Real")
    cnae_scope = payload.get("cnae_scope")
    ncm_scope = payload.get("ncm_scope")
    if cnae_scope not in {"reviewed_any", "allowlist"} or ncm_scope not in {
        "reviewed_any", "allowlist"
    }:
        raise FiscalValidationError("explicit CNAE/NCM coverage required")
    cnaes = _codes(payload.get("allowed_cnaes"), _CNAE, allow_empty=cnae_scope != "allowlist")
    ncms = _codes(payload.get("allowed_ncms"), _NCM, allow_empty=ncm_scope != "allowlist")
    if cnae_scope == "reviewed_any" and cnaes or ncm_scope == "reviewed_any" and ncms:
        raise FiscalValidationError("conflicting reviewed classification coverage")
    required = payload.get("required_evidence")
    if not isinstance(required, list) or len(required) > 32 or not all(
        _reference(item) for item in required
    ) or len(set(required)) != len(required):
        raise FiscalValidationError("invalid mandatory federal evidence")
    if payload.get("operation") != program.operation:
        raise FiscalValidationError("federal benefit operation mismatches official registry")
    return program, tuple(allowed), cnae_scope, cnaes, ncm_scope, ncms, tuple(required)


def decode_facts(payload: object) -> tuple[str, str | None, str, dict[str, str]]:
    if not isinstance(payload, dict) or payload.get("schema_version") != FACTS_SCHEMA:
        raise FiscalValidationError("unsupported federal benefit facts")
    if payload.get("review_status") != "reviewed" or not _reference(
        payload.get("review_reference")
    ):
        raise FiscalValidationError("reviewed federal facts required")
    cnae = payload.get("activity_cnae")
    ncm = payload.get("operation_ncm")
    operation = payload.get("operation")
    if not isinstance(cnae, str) or _CNAE.fullmatch(cnae) is None:
        raise FiscalValidationError("invalid federal activity CNAE")
    if ncm is not None and (not isinstance(ncm, str) or _NCM.fullmatch(ncm) is None):
        raise FiscalValidationError("invalid federal operation NCM")
    if not isinstance(operation, str) or operation not in {
        program.operation for program in PROGRAMS.values()
    }:
        raise FiscalValidationError("unsupported federal operation")
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict) or not 1 <= len(evidence) <= 32 or not all(
        _reference(k) and _reference(v) for k, v in evidence.items()
    ):
        raise FiscalValidationError("reviewed federal evidence references required")
    return cnae, ncm, operation, evidence
