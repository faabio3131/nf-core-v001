"""Import a reviewed T05 or T06 bundle into an authorized, existing sandbox database.

Run inside the trusted operational environment, never from the public portal.
No migration, production promotion, fiscal issuance or legal review is performed.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from kordena_fiscal.application.simples_diagnostic_service import import_reviewed_inputs
from kordena_fiscal.application.simples_segregation_service import (
    SCHEMA,
    import_reviewed_segregation,
)
from kordena_fiscal.cognitive.simples_diagnostic_api import build_issuer_verifier
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--unit", required=True)
    args = parser.parse_args()
    if os.environ.get("NFCORE_ENVIRONMENT") not in {"development", "test", "staging"}:
        parser.error("reviewed import requires an authorized non-production environment")
    if args.bundle.stat().st_size > 1_048_576:
        parser.error("bundle too large")
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    if not isinstance(bundle, dict) or set(bundle) != {
        "snapshot_id", "snapshot_version", "competence", "issuer_cnpj",
        "content", "rule_id", "rule_version", "rule_content",
    } or not isinstance(bundle["content"], dict):
        parser.error("invalid reviewed bundle shape")
    from kordena_fiscal.application.simples_diagnostic_service import SNAPSHOT_SCHEMA

    schema = bundle["content"].get("schema_version")
    if schema not in {SCHEMA, SNAPSHOT_SCHEMA}:
        parser.error("unknown reviewed bundle schema")
    importer = import_reviewed_segregation if schema == SCHEMA else import_reviewed_inputs
    scope = ExecutionScope(
        tenant_id=args.tenant, unit_id=args.unit, environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="simples-reviewed-import", host_namespace="fm-nfcore",
    )
    database = PostgresFiscalDatabase(os.environ["DATABASE_URL"])
    try:
        with database() as uow:
            unit = uow.control_plane.get_unit(scope.tenant_id, scope.unit_id)
        if unit is None or scope.environment not in unit.enabled_environments:
            parser.error("canonical unit/environment not configured")
        with database.economy(scope) as store:
            result = importer(
                store, snapshot_id=bundle["snapshot_id"],
                snapshot_version=bundle["snapshot_version"],
                competence=date.fromisoformat(bundle["competence"]),
                issuer=Cnpj(bundle["issuer_cnpj"]), content=bundle["content"],
                rule_id=bundle["rule_id"], rule_version=bundle["rule_version"],
                rule_content=bundle["rule_content"],
                verify_issuer=build_issuer_verifier(database, scope),
            )
        receipt = {"snapshot_id": result["snapshot_id"]}
        if schema == SCHEMA:
            receipt.update({
                "snapshot_digest": result["snapshot_digest"], "rule_digest": result["rule_digest"],
                "classification_digest": result["digest"], "status": result["status"],
            })
        else:
            receipt["evaluation_ids"] = result["evaluation_ids"]
        print(json.dumps(receipt, sort_keys=True))
    finally:
        database.close()


if __name__ == "__main__":
    main()
