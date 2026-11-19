"""Governed one-off script: raise the National DPS counter floor of one issuer.

Run inside the nfcore-api container, where DATABASE_URL is already present in
the process environment. Never prints the DSN or any credential.

Use it when the issuer already sent DPS numbers through another system (for
example the public Emissor Nacional) or after a database restore, so the next
NFCore reservation starts AFTER the last number really used. It only raises the
counter, never lowers it, and records approver + reference in the existing
configuration ledger and fiscal archive. Without --apply it only validates the
arguments and prints what would be done.

Example (homologation, CNPJ 09107283000140, Cajamar 3509205, series 1):
  python scripts/admin/raise_dps_counter_floor.py --tenant <tenant> --unit <unit> \
    --environment homologation --cnpj 09107283000140 --ibge 3509205 --series 1 \
    --last-used 57 --approved-by "Nome do responsável" --reference "chamado-123"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime

from kordena_fiscal.application.dps_counter_floor import raise_dps_counter_floor
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.persistence.sqlite_dps import validate_dps_floor_key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument(
        "--environment", required=True, choices=[e.value for e in FiscalEnvironment],
    )
    parser.add_argument("--cnpj", required=True)
    parser.add_argument("--ibge", required=True)
    parser.add_argument("--series", required=True, type=int)
    parser.add_argument("--last-used", required=True, type=int)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--host-namespace", default="fm-nfcore")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    scope = ExecutionScope(
        args.tenant, args.unit, FiscalEnvironment(args.environment),
        "dps-counter-floor-cli", args.host_namespace,
    )
    validate_dps_floor_key(scope, args.cnpj, args.ibge, args.series, args.last_used)
    plan = {
        "tenant": args.tenant, "unit": args.unit, "environment": args.environment,
        "cnpj": args.cnpj, "ibge": args.ibge, "series": args.series,
        "last_used": args.last_used, "next_reservation_at_least": args.last_used + 1,
    }
    if not args.apply:
        print(json.dumps({"dry_run": True, **plan}, sort_keys=True))
        return 0
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set in this process", file=sys.stderr)
        return 2
    database = PostgresFiscalDatabase(dsn)
    try:
        # Refuse to write against an unexpected schema; this script never migrates.
        database.require_current_schema()
        result = raise_dps_counter_floor(
            database, scope=scope, issuer_cnpj=args.cnpj, municipality_ibge=args.ibge,
            series=args.series, last_used_number=args.last_used,
            approved_by=args.approved_by, approval_reference=args.reference,
            occurred_at=datetime.now(UTC),
        )
    finally:
        database.close()
    print(json.dumps({**plan, **dict(result)}, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
