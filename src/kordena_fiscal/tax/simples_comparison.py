"""Compare reviewed PGDAS-D reference totals without promoting fiscal authority."""
from typing import Any

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.simples_nacional import TAXES, TRANSITION_TAXES
from kordena_fiscal.tax.simples_segregation import _amount, _ref


def compare_assessment(
    result: dict[str, Any], reference: dict[str, Any],
    *, segregation_digest: str, competence: str,
) -> dict[str, Any]:
    _ref(reference["evidence_reference"])
    _ref(reference["review_reference"])
    # A revenue digest alone does not identify the rate, company history,
    # partition or recognition basis used in an assessment.
    assessment_digest = result.get("digest")
    if (not isinstance(assessment_digest, str) or not assessment_digest
            or result.get("competence") != competence
            or result.get("segregation_digest") != segregation_digest
            or reference["competence"] != competence
            or reference["segregation_digest"] != segregation_digest
            or reference.get("assessment_digest") != assessment_digest
            or reference["review_status"] != "reviewed"):
        raise FiscalValidationError("PGDAS reference does not match scoped evidence")
    taxes = TRANSITION_TAXES if competence.startswith("2027-") else TAXES
    expected = reference["tax_cents"]
    if not isinstance(expected, dict) or set(expected) != set(taxes):
        raise FiscalValidationError("complete PGDAS tax reference required")
    for value in expected.values():
        _amount(value)
    _amount(reference["total_cents"])
    if sum(expected.values()) != reference["total_cents"]:
        raise FiscalValidationError("PGDAS reference totals do not reconcile")
    actual = result.get("tax_cents")
    if result.get("status") != "estimated" or not isinstance(actual, dict):
        return {"status": "blocked", "reference": reference["evidence_reference"]}
    differences = {tax: actual[tax] - expected[tax] for tax in taxes}
    return {
        "status": "match" if not any(differences.values()) else "divergent",
        "assessment_digest": assessment_digest,
        "differences_cents": differences,
        "reference": reference["evidence_reference"],
        "review_reference": reference["review_reference"],
        "official_certification": False,
    }
