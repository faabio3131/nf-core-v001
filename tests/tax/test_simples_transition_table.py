"""LC 214/227 future table data, not a future PGDAS assessment."""
from datetime import date

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.simples_nacional import (
    TRANSITION_TABLE_DIGEST,
    Annex,
    transition_band,
)


@pytest.mark.parametrize("annex,sixth", [
    (Annex.ANNEX_I, 1890), (Annex.ANNEX_II, 2990),
    (Annex.ANNEX_III, 3290), (Annex.ANNEX_IV, 3290), (Annex.ANNEX_V, 3040),
])
@pytest.mark.parametrize("year", [2027, 2028])
def test_transition_tables(annex, sixth, year):
    for band in range(1, 7):
        nominal, deduction, shares = transition_band(date(year, 1, 1), annex, band)
        assert nominal > 0 and deduction >= 0
        assert sum(shares.values()) == 10_000
        assert "pis" not in shares and "cofins" not in shares
        assert shares["cbs"] > 0
        if band == 6:
            assert nominal == sixth
            assert shares["ibs"] == shares["icms"] == shares["iss"] == 0
        else:
            assert shares["ibs"] > 0
    assert len(TRANSITION_TABLE_DIGEST) == 64


def test_transition_annex_iii_lc227_correction():
    _, _, shares = transition_band(date(2027, 1, 1), Annex.ANNEX_III, 3)
    assert shares["cbs"] == 1641
    assert shares["ibs"] == 19


@pytest.mark.parametrize("year", [2026, 2029, 2033])
def test_transition_rejects_outside_statutory_validity(year):
    with pytest.raises(FiscalValidationError, match="only valid"):
        transition_band(date(year, 1, 1), Annex.ANNEX_I, 1)
