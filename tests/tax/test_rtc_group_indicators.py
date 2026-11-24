"""Indicators of the official RTC table that NFCore must honour before the XML."""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.rtc_group_indicators import (
    CLASSIFICATIONS_REQUIRING_UNSUPPORTED_GROUPS,
    SUPPORTED_RTC_CST_GROUPS,
    require_representable_classification,
    rtc_cst_requires_gibscbs,
)


def test_unsupported_groups_are_refused_and_plain_codes_pass() -> None:
    for code, group in CLASSIFICATIONS_REQUIRING_UNSUPPORTED_GROUPS.items():
        with pytest.raises(FiscalValidationError, match=group):
            require_representable_classification(code)
    for code in ("000001", "200003", "200047", "400003", "410008"):
        require_representable_classification(code)
    assert rtc_cst_requires_gibscbs("000") and rtc_cst_requires_gibscbs("200")
    assert not rtc_cst_requires_gibscbs("400") and not rtc_cst_requires_gibscbs("410")
    for unsupported in ("510", "550", "620", "800", "011", "222"):
        with pytest.raises(FiscalValidationError, match="supported approved CST"):
            rtc_cst_requires_gibscbs(unsupported)


_DB = os.environ.get("NFCORE_RFB_CALCULATOR_DB")


def test_tables_match_the_official_database() -> None:
    if not _DB or not Path(_DB).is_file():
        if os.environ.get("NFCORE_RFB_CALCULATOR_DB_REQUIRED") == "true":
            pytest.fail("required official V0073 database not mounted")
        pytest.skip("V0073 database not mounted")
    with closing(sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)) as con:
        version = con.execute(
            "select VRBD_VERSAO_BASE_DADO from VERSAO_BASE_DADO "
            "order by VRBD_ID desc limit 1"
        ).fetchone()
        assert version == ("V0073",)
        assert con.execute(
            "select count(*) from flyway_schema_history where success = 0"
        ).fetchone() == (0,)
        groups = dict(con.execute(
            "select SITR_CD, SITR_IND_GIBSCBS from SITUACAO_TRIBUTARIA "
            "where SITR_INICIO_VIGENCIA = '2026-01-01'"
        ).fetchall())
        for cst, needs in SUPPORTED_RTC_CST_GROUPS.items():
            assert bool(groups[cst]) is needs
        rows = con.execute(
            "select t.CLTR_CD, t.CLTR_IND_GCREDPRESOPER, t.CLTR_IND_GMONOPADRAO, "
            "t.CLTR_IND_GMONORETEN, t.CLTR_IND_GMONORET, t.CLTR_IND_GMONODIF, "
            "t.CLTR_IND_GESTORNOCRED from CLASSIFICACAO_TRIBUTARIA t join SITUACAO_TRIBUTARIA s "
            "on s.SITR_ID = t.CLTR_SITR_ID where s.SITR_INICIO_VIGENCIA = '2026-01-01' "
            "and s.SITR_CD in ('000', '200', '400', '410')"
        ).fetchall()
        names = ("gCredPresOper", "gMonoPadrao", "gMonoReten", "gMonoRet", "gMonoDif",
                 "gEstornoCred")
        derived = {
            code: next(n for n, flag in zip(names, flags, strict=True) if flag)
            for code, *flags in rows if any(flags)
        }
        assert derived == CLASSIFICATIONS_REQUIRING_UNSUPPORTED_GROUPS
