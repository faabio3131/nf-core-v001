"""Load reviewed T12 annual scenarios into an existing homologation scope only."""
import argparse
import json
import os
from pathlib import Path

from kordena_fiscal.application.annual_regime_comparison import import_annual
from kordena_fiscal.cognitive.annual_regime_comparison_api import annual_issuer_context
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.tax.annual_regime_comparison import AnnualComparison, compare


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--unit", required=True)
    args = parser.parse_args()
    if os.environ.get("NFCORE_ENVIRONMENT") not in {"development", "test", "staging"}:
        parser.error("homologation import requires a non-production environment")
    if args.bundle.stat().st_size > 1048576:
        parser.error("bundle exceeds T01 limit")
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    if set(bundle) != {"tenant", "unit", "issuer_cnpj", "version", "facts"} or (
        bundle["tenant"], bundle["unit"]
    ) != (args.tenant, args.unit):
        parser.error("invalid bundle scope")
    issuer = Cnpj(bundle["issuer_cnpj"])
    facts = AnnualComparison.model_validate(bundle["facts"])
    compare(facts)
    scope = ExecutionScope(args.tenant, args.unit, FiscalEnvironment.HOMOLOGATION,
                           "annual-regime-reviewed-import", "fm-nfcore")
    db = PostgresFiscalDatabase(os.environ["DATABASE_URL"])
    try:
        with db() as uow:
            unit = uow.control_plane.get_unit(scope.tenant_id, scope.unit_id)
        if unit is None or scope.environment not in unit.enabled_environments:
            parser.error("unit not enabled in homologation")
        annual_issuer_context(db, scope, issuer.value, facts.baseline.uf)
        with db.economy(scope) as store:
            digest = import_annual(store, issuer, bundle["version"], facts)
        print(json.dumps({"snapshot_digest": digest, "version": bundle["version"]}))
    finally:
        db.close()


if __name__ == "__main__":
    main()
