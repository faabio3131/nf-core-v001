"""Canonical DPS identity formatting; never allocates a fiscal number."""
from kordena_fiscal.domain import FiscalValidationError


def national_dps_id(municipality: str, cnpj: str, series: int, number: int) -> str:
    if (
        len(municipality) != 7 or not municipality.isascii() or not municipality.isdecimal()
        or len(cnpj) != 14 or not cnpj.isascii() or not cnpj.isdecimal()
        or type(series) is not int or not 1 <= series <= 99_999
        or type(number) is not int or not 1 <= number <= 999_999_999_999_999
    ):
        raise FiscalValidationError("DPS identity requires a legal reserved issuer serial")
    return f"DPS{municipality}1{cnpj}{series:05d}{number:015d}"
