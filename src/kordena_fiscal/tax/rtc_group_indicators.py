"""Classification-level group indicators of the official RTC table.

Source: table CLASSIFICACAO_TRIBUTARIA of the calculator database V0073 (Flyway
from the pinned regime-regular commit), columns CLTR_IND_GCREDPRESOPER,
CLTR_IND_GMONO*, CLTR_IND_GESTORNOCRED, and SITUACAO_TRIBUTARIA.SITR_IND_GIBSCBS.

NFCore emits only CST + cClassTrib (CST 400/410) or the gIBSCBS group with an
optional gRed (CST 000/200). A classification whose indicator demands another
group (presumed credit, monophasic, credit reversal) cannot be represented and
is refused before XML is built, instead of producing an incomplete NF-e.
"""
from __future__ import annotations

from kordena_fiscal.domain.errors import FiscalValidationError

RTC_INDICATOR_SOURCE = "RFB calculadora V0073 CLASSIFICACAO_TRIBUTARIA"

# CSTs NFCore can emit, and whether SITUACAO_TRIBUTARIA requires gIBSCBS.
SUPPORTED_RTC_CST_GROUPS: dict[str, bool] = {
    "000": True,
    "200": True,
    "400": False,
    "410": False,
}

# Every classification under the supported CSTs whose own indicator requires a
# group NFCore does not emit (exhaustive for V0073; re-derived by the test when
# the database is available).
CLASSIFICATIONS_REQUIRING_UNSUPPORTED_GROUPS: dict[str, str] = {
    "000003": "gCredPresOper",
    "000004": "gCredPresOper",
    "200054": "gEstornoCred",
    "410016": "gCredPresOper",
    "410026": "gEstornoCred",
    "410030": "gEstornoCred",
}


def rtc_cst_requires_gibscbs(cst: str) -> bool:
    try:
        return SUPPORTED_RTC_CST_GROUPS[cst]
    except KeyError:
        raise FiscalValidationError("RTC XML requires supported approved CST") from None


def require_representable_classification(classification: str) -> None:
    group = CLASSIFICATIONS_REQUIRING_UNSUPPORTED_GROUPS.get(classification)
    if group is not None:
        raise FiscalValidationError(
            f"cClassTrib {classification} requires group {group}, not emitted by NFCore"
        )
