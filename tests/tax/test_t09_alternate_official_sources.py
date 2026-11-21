"""Alternative legal source trial cannot promote an unverified draft."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from runpy import run_path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = run_path(str(ROOT / "scripts/nfcore_t09_capture_alternatives.py"))
verify_workset = HELPER["verify_workset"]


def _inputs():
    catalog = json.loads(
        (ROOT / "docs/NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json")
        .read_text(encoding="utf-8"),
    )
    alternatives = json.loads(
        (ROOT / "docs/NFCORE_T09_OFFICIAL_ALTERNATIVE_SOURCE_TRIAL_V1.json")
        .read_text(encoding="utf-8"),
    )
    return catalog, alternatives


def test_trial_has_eight_uf_and_never_authorizes_tax():
    catalog, proposed = _inputs()
    sources = verify_workset(catalog, proposed)
    assert len(sources) == 18
    assert {x["uf"] for x in sources} == {
        "AC", "AL", "AP", "PA", "PI", "RJ", "RN", "SE",
    }
    assert all(x["eligible_for_tax_calculation"] is False for x in sources)
    assert all(x["review_status"] == "unreviewed" for x in sources)


@pytest.mark.parametrize("field", [
    "authorized_for_import", "legal_validity_certified",
    "independent_approval_received",
])
def test_trial_cannot_forge_approval(field):
    catalog, proposed = _inputs()
    changed = copy.deepcopy(proposed)
    changed[field] = True
    with pytest.raises(ValueError, match="cannot"):
        verify_workset(catalog, changed)


def test_trial_rejects_non_official_domain():
    catalog, proposed = _inputs()
    changed = copy.deepcopy(proposed)
    changed["entries"][0]["source_url"] = "https://gov.br.attacker.invalid/lei"
    with pytest.raises(ValueError, match="unauthorized"):
        verify_workset(catalog, changed)


def test_trial_rejects_mismatched_canonical_candidate():
    catalog, proposed = _inputs()
    changed = copy.deepcopy(proposed)
    changed["entries"][0]["candidate_id"] = "OTHER-UF-SPOOF"
    with pytest.raises(ValueError, match="unauthorized"):
        verify_workset(catalog, changed)


def test_trial_rejects_candidate_promoted_without_review():
    catalog, proposed = _inputs()
    changed = copy.deepcopy(catalog)
    changed["candidates"][0]["import_authorized"] = True
    with pytest.raises(ValueError, match="non-authorized"):
        verify_workset(changed, proposed)


def test_related_ap_decree_is_not_the_art_415_target():
    _, proposed = _inputs()
    ap = [x for x in proposed["entries"] if x["uf"] == "AP"]
    nonmatching = next(x for x in ap if "36326/1785" in x["source_url"])
    assert nonmatching["source_kind"] == "related_nonmatching_act"
    assert nonmatching["eligible_for_tax_calculation"] is False
