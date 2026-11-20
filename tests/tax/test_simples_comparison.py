from copy import deepcopy

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.simples_comparison import compare_assessment
from kordena_fiscal.tax.simples_nacional import TAXES


def test_reviewed_reference_match_and_divergence():
    taxes = dict.fromkeys(TAXES, 100)
    result = {"status": "estimated", "tax_cents": taxes}
    reference = {
        "competence": "2026-11-01", "segregation_digest": "digest",
        "review_status": "reviewed", "review_reference": "review",
        "evidence_reference": "synthetic-fixture", "tax_cents": deepcopy(taxes),
        "total_cents": 800,
    }
    kwargs = dict(segregation_digest="digest", competence="2026-11-01")
    assert compare_assessment(result, reference, **kwargs)["status"] == "match"
    reference["tax_cents"]["pis"] += 1
    reference["total_cents"] += 1
    comparison = compare_assessment(result, reference, **kwargs)
    assert comparison["status"] == "divergent"
    assert comparison["differences_cents"]["pis"] == -1
    assert comparison["official_certification"] is False
    reference["total_cents"] += 1
    with pytest.raises(FiscalValidationError, match="reconcile"):
        compare_assessment(result, reference, **kwargs)
    with pytest.raises(FiscalValidationError, match="scoped"):
        compare_assessment(result, reference, **{**kwargs, "segregation_digest": "other"})
