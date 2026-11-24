"""Import immutable, reviewed quarterly simulation facts into T01."""
from datetime import date

from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.tax.quarterly_simulation import Quarter, simulate


def import_quarter(store: EconomyStore, issuer: Cnpj, version: int, facts: Quarter) -> str:
    month = date.fromisoformat(facts.period_start)
    simulate(month, facts)
    record_id = f"quarter-{issuer.value}-{month.isoformat()}"
    if type(version) is not int or not 1 <= version <= 2147483647:
        raise FiscalValidationError("invalid version")
    store.lock_state_review_import(record_id, record_id)
    content = facts.model_dump()
    existing = store.record("fm_economy_snapshots", record_id)
    if existing is not None and existing["version"] == version and existing["content"] == content:
        return str(existing["digest"])
    if version != (existing["version"] + 1 if existing else 1):
        raise FiscalValidationError("expected next immutable snapshot version")
    return store.append_snapshot(record_id=record_id, version=version, competence=month,
                                 issuer=issuer, content=content)
