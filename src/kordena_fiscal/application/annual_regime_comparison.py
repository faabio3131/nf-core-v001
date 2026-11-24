"""Immutable T12 reviewed input, under the same scoped T01 transaction."""
from datetime import date

from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.tax.annual_regime_comparison import AnnualComparison, compare
from kordena_fiscal.tax.quarterly_simulation import SCHEMA as QUARTER_SCHEMA

PERIOD = date(2026, 1, 1)


def verify_baseline_links(store: EconomyStore, issuer: Cnpj, facts: AnnualComparison) -> None:
    for index, (link, quarter) in enumerate(
        zip(facts.baseline_quarter_links, facts.baseline.quarters, strict=True)
    ):
        period = date(PERIOD.year, 1 + 3 * index, 1)
        if quarter.period_start != period.isoformat():
            raise FiscalValidationError("invalid linked quarterly competence")
        record_id = f"quarter-{issuer.value}-{period.isoformat()}"
        row = store.unique_monthly_snapshot(issuer.value, period, QUARTER_SCHEMA)
        if (row is None or link.record_id != record_id or row["record_id"] != record_id
                or row["version"] != link.version or row["digest"] != link.digest
                or row["content"] != quarter.model_dump()):
            raise FiscalValidationError(
                "annual baseline does not match current scoped T11 snapshot",
            )


def import_annual(
    store: EconomyStore, issuer: Cnpj, version: int, facts: AnnualComparison,
) -> str:
    compare(facts)
    verify_baseline_links(store, issuer, facts)
    record_id = f"annual-regime-{issuer.value}-{PERIOD.year}"
    if type(version) is not int or not 1 <= version <= 2147483647:
        raise FiscalValidationError("invalid version")
    store.lock_state_review_import(record_id, record_id)
    content = facts.model_dump()
    existing = store.record("fm_economy_snapshots", record_id)
    if existing is not None and existing["version"] == version and existing["content"] == content:
        return str(existing["digest"])
    if version != (existing["version"] + 1 if existing else 1):
        raise FiscalValidationError("expected next immutable annual snapshot version")
    return store.append_snapshot(record_id=record_id, version=version, competence=PERIOD,
                                 issuer=issuer, content=content)
