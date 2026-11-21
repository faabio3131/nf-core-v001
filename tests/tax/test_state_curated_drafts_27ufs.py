"""T09 curatorial materials must remain exhaustive geographically, not fiscally."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.state_benefits import _UF_CODES, decode_rule

PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json"
)


def curated():
    return json.loads(PATH.read_text(encoding="utf-8"))


def test_representation_is_exactly_one_distinct_draft_per_uf():
    data = curated()
    assert data["curation_research_count"] == 27
    assert data["all_state_benefits_legally_consolidated"] is False
    assert data["accountant_signoff_received"] is False
    assert data["legal_source_bytes_archived"] is False
    assert data["approved_for_eligibility"] is False
    assert data["import_authorized"] is False
    rows = data["candidates"]
    assert len(rows) == 27
    assert {c["uf"] for c in rows} == set(_UF_CODES)
    assert len({c["candidate_id"] for c in rows}) == 27


@pytest.mark.parametrize("uf", sorted(_UF_CODES))
def test_every_curated_draft_has_legal_negative_and_blocks_activation(uf):
    row = next(x for x in curated()["candidates"] if x["uf"] == uf)
    assert row["candidate_version"] == 1
    assert row["tax_code"] == "ICMS"
    assert row["review_status"] == "draft"
    assert row["findings_verified_from_public_source"]
    assert row["eligibility_predicates_to_confirm"]
    assert row["negative_eligibility_scenario"]
    assert len(row["mandatory_missing"]) >= 5
    assert row["source_sha256"] is None
    assert row["legal_reviewer"] is None
    assert not row["approved_for_eligibility"]
    assert not row["import_authorized"]
    assert not row["eligibility_certified"]
    url = urlsplit(row["state_official_source_url"])
    assert url.scheme == "https"
    assert url.hostname is not None
    # Official legislative sources may be served on the .leg.br domain.
    # Match the full public-sector domain boundary, never an arbitrary host.
    assert url.hostname == "gov.br" or url.hostname.endswith(
        (".gov.br", ".leg.br"),
    )
    assert url.username is None and url.password is None
    with pytest.raises(FiscalValidationError, match="not human reviewed"):
        decode_rule(row)


def test_prevent_three_known_false_legal_positives():
    rows = {c["uf"]: c for c in curated()["candidates"]}
    assert "art. 52" in " ".join(
        rows["SP"]["findings_verified_from_public_source"]
    )
    assert "mês subsequente" in rows["RS"]["negative_eligibility_scenario"]
    assert "Decreto 6.434/2017" in rows["PR"]["negative_eligibility_scenario"]
    assert "revo" in rows["RO"]["negative_eligibility_scenario"].lower()
