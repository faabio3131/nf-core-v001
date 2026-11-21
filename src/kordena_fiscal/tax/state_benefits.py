"""T09 state ICMS candidate catalog for all 26 states and the Federal District.

27-UF registry is geographic coverage only, NOT 27 sets of verified tax rules.
Deterministic review triage cannot confer incentives, lower ICMS or issue NF-e.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from kordena_fiscal.domain import BrazilianJurisdiction, FiscalValidationError
from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime

RULE_SCHEMA = "nfcore.state-icms-benefit-rule/v1"
FACTS_SCHEMA = "nfcore.state-icms-benefit-facts/v1"
ENGINE_VERSION = "nfcore.state-icms-benefits/2026-v1"
_UF_CODES = {
    "AC": ("Acre", "12"), "AL": ("Alagoas", "27"),
    "AP": ("Amapá", "16"), "AM": ("Amazonas", "13"),
    "BA": ("Bahia", "29"), "CE": ("Ceará", "23"),
    "DF": ("Distrito Federal", "53"), "ES": ("Espírito Santo", "32"),
    "GO": ("Goiás", "52"), "MA": ("Maranhão", "21"),
    "MT": ("Mato Grosso", "51"), "MS": ("Mato Grosso do Sul", "50"),
    "MG": ("Minas Gerais", "31"), "PA": ("Pará", "15"),
    "PB": ("Paraíba", "25"), "PR": ("Paraná", "41"),
    "PE": ("Pernambuco", "26"), "PI": ("Piauí", "22"),
    "RJ": ("Rio de Janeiro", "33"), "RN": ("Rio Grande do Norte", "24"),
    "RS": ("Rio Grande do Sul", "43"), "RO": ("Rondônia", "11"),
    "RR": ("Roraima", "14"), "SC": ("Santa Catarina", "42"),
    "SP": ("São Paulo", "35"), "SE": ("Sergipe", "28"),
    "TO": ("Tocantins", "17"),
}
BENEFIT_KINDS = frozenset({
    "exemption", "base_reduction", "presumed_credit",
    "deferral", "rate_reduction", "special_regime",
})
LEGAL_PATHS = frozenset({
    "state_statute", "confaz_convention", "lc160_reinstituted",
})
_OPERATIONS = frozenset({
    "domestic_sale", "interstate_sale", "domestic_purchase",
    "interstate_purchase", "import", "transport_service",
    "asset_acquisition",
})
# CFOP leading digit encodes direction/destination. This is a necessary
# sanity check, not a complete semantic verification of the four-digit CFOP.
# Transport can be incoming or outgoing; no safe inference from operation alone.
_CFOP_PREFIXES_BY_OPERATION = {
    "domestic_sale": "5",
    "interstate_sale": "6",
    "domestic_purchase": "1",
    "interstate_purchase": "2",
    "import": "3",
    "asset_acquisition": "123",
}

_CNAE = re.compile(r"[0-9]{7}\Z")
_NCM = re.compile(r"[0-9]{8}\Z")
_CFOP = re.compile(r"[1-7][0-9]{3}\Z")
_REF = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._/+:@-]{2,127}\Z")
_NORM = re.compile(r"[^\s].{4,255}\Z")
_COMMON_EVIDENCE = (
    "state_normative_review", "operation_classification_review",
    "taxpayer_status_review", "competence_review",
)
_ROUTE_EVIDENCE = {
    "state_statute": ("state_act_review",),
    "confaz_convention": ("state_adoption_review", "confaz_convention_review"),
    "lc160_reinstituted": (
        "state_reinstitution_review", "confaz_registry_deposit_review",
        "confaz_certification_review",
    ),
}


@dataclass(frozen=True, slots=True)
class ReviewedStateIssuer:
    """Resolved exclusively by canonical FiscalProfile and federal regime authority."""

    cnpj: str
    uf: str
    primary_cnae: str
    regime: FederalIncomeTaxRegime
    state_registration_present: bool
    scope_identity: tuple[str, ...]


def state_index() -> dict[str, Any]:
    """A complete geographic index, with zero claims of 27 state homologations."""
    return {
        "schema_version": "nfcore.state-icms-index/v1",
        "advisory_only": True,
        "complete_geographic_index": True,
        "complete_state_benefit_coverage": False,
        "homologated_state_count": 0,
        "issuance_authorized": False,
        "national_context": (
            "LC 160/2017",
            "Convênio ICMS 190/2017",
        ),
        "uf": [
            {
                "uf": uf, "name": name, "ibge_uf_code": code,
                "state_acts_reviewed": False,
                "benefits_homologated": False,
                "requires_state_primary_legislation": True,
            }
            for uf, (name, code) in sorted(_UF_CODES.items())
        ],
    }


def _codes(value: object, pattern: re.Pattern[str], *, required: bool) -> tuple[str, ...]:
    if (
        not isinstance(value, list) or len(value) > 1000
        or (required and not value)
        or not all(isinstance(v, str) and pattern.fullmatch(v) for v in value)
        or len(set(value)) != len(value)
    ):
        raise FiscalValidationError("invalid reviewed state classification")
    return tuple(value)


def _evidence(value: object) -> dict[str, str]:
    if (
        not isinstance(value, dict) or not 1 <= len(value) <= 64
        or not all(
            isinstance(k, str) and _REF.fullmatch(k)
            and isinstance(v, str) and _REF.fullmatch(v)
            for k, v in value.items()
        )
    ):
        raise FiscalValidationError("state benefit evidence must be reviewed references")
    return value


def decode_rule(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != RULE_SCHEMA:
        raise FiscalValidationError("unsupported state ICMS policy schema")
    if payload.get("review_status") != "reviewed":
        raise FiscalValidationError("state benefit policy not human reviewed")
    ref = payload.get("review_reference")
    if not isinstance(ref, str) or not _REF.fullmatch(ref):
        raise FiscalValidationError("state policy requires review reference")
    uf = payload.get("uf")
    if not isinstance(uf, str) or uf not in _UF_CODES:
        raise FiscalValidationError("invalid state benefit UF")
    # Also rely on the existing fiscal jurisdiction authority, never a parallel UF.
    if BrazilianJurisdiction(uf).state_code != uf:
        raise FiscalValidationError("state benefit UF inconsistent with fiscal domain")
    kind = payload.get("benefit_kind")
    path = payload.get("legal_path")
    if (not isinstance(kind, str) or kind not in BENEFIT_KINDS
            or not isinstance(path, str) or path not in LEGAL_PATHS):
        raise FiscalValidationError("unknown state benefit kind or legal route")
    norm = payload.get("state_normative_reference")
    if not isinstance(norm, str) or not _NORM.fullmatch(norm):
        raise FiscalValidationError("state enactment identifier must be explicit")
    start = payload.get("valid_from")
    end = payload.get("valid_until")
    if not isinstance(start, str) or (end is not None and not isinstance(end, str)):
        raise FiscalValidationError("reviewed state benefit dates must be ISO strings")
    try:
        valid_from = date.fromisoformat(start)
        valid_until = date.fromisoformat(end) if end is not None else None
    except (TypeError, ValueError) as exc:
        raise FiscalValidationError("invalid reviewed state benefit validity") from exc
    if valid_until is not None and valid_until <= valid_from:
        raise FiscalValidationError("invalid state benefit validity interval")
    regime_raw = payload.get("allowed_regimes")
    if (
        not isinstance(regime_raw, list) or not regime_raw
        or not all(isinstance(x, str) for x in regime_raw)
        or len(set(regime_raw)) != len(regime_raw)
        or any(x not in {r.value for r in FederalIncomeTaxRegime} for x in regime_raw)
    ):
        raise FiscalValidationError("reviewed state income-tax regimes required")
    cnae_scope = payload.get("cnae_scope")
    ncm_scope = payload.get("ncm_scope")
    if cnae_scope not in ("allowlist", "reviewed_any") or ncm_scope not in (
        "allowlist", "reviewed_any"
    ):
        raise FiscalValidationError("explicit state CNAE and NCM classification required")
    cnaes = _codes(
        payload.get("allowed_cnaes"), _CNAE, required=cnae_scope == "allowlist",
    )
    ncms = _codes(
        payload.get("allowed_ncms"), _NCM, required=ncm_scope == "allowlist",
    )
    if (cnae_scope == "reviewed_any" and cnaes) or (
        ncm_scope == "reviewed_any" and ncms
    ):
        raise FiscalValidationError("contradictory state classification coverage")
    cfops = _codes(payload.get("allowed_cfops"), _CFOP, required=True)
    operations = payload.get("allowed_operations")
    if (
        not isinstance(operations, list) or not operations
        or len(operations) > len(_OPERATIONS)
        or not all(isinstance(v, str) and v in _OPERATIONS for v in operations)
        or len(set(operations)) != len(operations)
    ):
        raise FiscalValidationError("state benefit must restrict operations")
    evidence = payload.get("required_evidence")
    if (
        not isinstance(evidence, list) or len(evidence) > 32
        or not all(isinstance(v, str) and _REF.fullmatch(v) for v in evidence)
        or len(set(evidence)) != len(evidence)
    ):
        raise FiscalValidationError("invalid reviewed state evidence checklist")
    if path != "state_statute" and not isinstance(
        payload.get("confaz_normative_reference"), str
    ):
        raise FiscalValidationError("CONFAZ legal basis required for selected route")
    if path != "state_statute" and not _NORM.fullmatch(
        payload["confaz_normative_reference"]
    ):
        raise FiscalValidationError("invalid CONFAZ legal identifier")
    return {
        **payload, "allowed_regimes": tuple(regime_raw),
        "allowed_cnaes": cnaes, "allowed_ncms": ncms,
        "allowed_cfops": cfops, "allowed_operations": tuple(operations),
        "required_evidence": tuple(evidence),
        "valid_from_date": valid_from, "valid_until_date": valid_until,
    }


def decode_facts(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != FACTS_SCHEMA:
        raise FiscalValidationError("unsupported state ICMS facts schema")
    if payload.get("review_status") != "reviewed":
        raise FiscalValidationError("state facts not human reviewed")
    ref = payload.get("review_reference")
    if not isinstance(ref, str) or not _REF.fullmatch(ref):
        raise FiscalValidationError("reviewed state facts reference required")
    uf = payload.get("uf")
    if not isinstance(uf, str) or uf not in _UF_CODES:
        raise FiscalValidationError("invalid state facts UF")
    cnae = payload.get("activity_cnae")
    if not isinstance(cnae, str) or not _CNAE.fullmatch(cnae):
        raise FiscalValidationError("invalid state facts activity CNAE")
    ncm = payload.get("operation_ncm")
    if ncm is not None and (not isinstance(ncm, str) or not _NCM.fullmatch(ncm)):
        raise FiscalValidationError("invalid state facts NCM")
    cfop = payload.get("operation_cfop")
    if not isinstance(cfop, str) or not _CFOP.fullmatch(cfop):
        raise FiscalValidationError("invalid reviewed operation CFOP")
    operation = payload.get("operation")
    if not isinstance(operation, str) or operation not in _OPERATIONS:
        raise FiscalValidationError("invalid reviewed state operation")
    return {
        "uf": uf, "activity_cnae": cnae, "operation_ncm": ncm,
        "operation_cfop": cfop, "operation": operation,
        "evidence": _evidence(payload.get("evidence")),
        "review_reference": ref,
    }


def _result(status: str, reasons: tuple[str, ...]) -> dict[str, Any]:
    return {
        "status": status, "reason_codes": list(reasons), "engine_version": ENGINE_VERSION,
        "advisory_only": True, "human_review_required": True,
        "eligibility_certified": False, "issuance_authorized": False,
        "tax_calculation_authorized": False, "approved_cents": None,
        "estimated_cents": None, "realized_cents": None,
        "complete_state_benefit_coverage": False,
    }


def assess_state_rule(
    rule: dict[str, Any], facts: dict[str, Any],
    issuer: ReviewedStateIssuer, competence: date,
) -> dict[str, Any]:
    """Conservative state tax triage; never authorizes a fiscal adjustment."""
    if rule["uf"] != facts["uf"] or rule["uf"] != issuer.uf:
        return _result("not_applicable", ("state_jurisdiction_mismatch",))
    if not issuer.state_registration_present:
        return _result("insufficient_basis", ("state_registration_unverified",))
    if issuer.primary_cnae != facts["activity_cnae"]:
        return _result("insufficient_basis", ("canonical_cnae_mismatch",))
    if competence < rule["valid_from_date"] or (
        rule["valid_until_date"] is not None
        and rule["valid_until_date"] < _next_month(competence)
    ):
        return _result("not_applicable", ("state_rule_not_effective_entire_month",))
    if issuer.regime.value not in rule["allowed_regimes"]:
        return _result("not_applicable", ("income_tax_regime_excluded",))
    if facts["operation"] not in rule["allowed_operations"]:
        return _result("not_applicable", ("operation_excluded",))
    if facts["operation_cfop"] not in rule["allowed_cfops"]:
        return _result("not_applicable", ("cfop_excluded",))
    prefixes = _CFOP_PREFIXES_BY_OPERATION.get(facts["operation"])
    if prefixes is not None and facts["operation_cfop"][0] not in prefixes:
        return _result("insufficient_basis", ("cfop_operation_mismatch",))
    if rule["cnae_scope"] == "allowlist" and (
        facts["activity_cnae"] not in rule["allowed_cnaes"]
    ):
        return _result("not_applicable", ("cnae_excluded",))
    if rule["ncm_scope"] == "allowlist":
        if facts["operation_ncm"] is None:
            return _result("insufficient_basis", ("ncm_missing",))
        if facts["operation_ncm"] not in rule["allowed_ncms"]:
            return _result("not_applicable", ("ncm_excluded",))
    mandatory = (
        *_COMMON_EVIDENCE,
        *_ROUTE_EVIDENCE[rule["legal_path"]],
        *rule["required_evidence"],
    )
    missing = sorted({k for k in mandatory if k not in facts["evidence"]})
    if missing:
        return _result("insufficient_basis", tuple(f"missing:{key}" for key in missing))
    return _result("potential", ("state_tax_expert_approval_required",))


def _next_month(month: date) -> date:
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)
