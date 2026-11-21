"""Trusted, non-production T09 import of reviewed state ICMS facts and policy.

No external portal, fiscal approval, tax credit, DDL or issuance. The caller is
responsible for the reviewed legal documents and their real source hashes.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from kordena_fiscal.application.state_benefits_service import (
    import_reviewed_state_benefit,
)
from kordena_fiscal.cognitive.state_benefits_api import build_state_issuer_verifier
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--unit", required=True)
    args = parser.parse_args()
    if os.getenv("NFCORE_ENVIRONMENT") not in {"development", "test", "staging"}:
        parser.error("state ICMS benefit import requires a non-production environment")
    if os.getenv("NFCORE_ECONOMY_ENABLED") != "true":
        parser.error("canonical economy persistence must be enabled")
    if args.bundle.is_symlink() or not args.bundle.is_file():
        parser.error("only regular bundle files are accepted")
    if args.bundle.stat().st_size > 1_048_576:
        parser.error("reviewed state ICMS bundle exceeds size limit")
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    if not isinstance(bundle, dict) or set(bundle) != {
        "snapshot_id", "snapshot_version", "competence", "issuer_cnpj",
        "content", "benefit_id", "benefit_version", "benefit_content",
    }:
        parser.error("invalid state ICMS bundle shape")
    if not isinstance(bundle["content"], dict) or not isinstance(
        bundle["benefit_content"], dict
    ):
        parser.error("reviewed state ICMS bundle requires fact and policy objects")
    scope = ExecutionScope(
        tenant_id=args.tenant, unit_id=args.unit,
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="state-reviewed-import", host_namespace="fm-nfcore",
    )
    database = PostgresFiscalDatabase(os.environ["DATABASE_URL"])
    try:
        with database() as uow:
            unit = uow.control_plane.get_unit(scope.tenant_id, scope.unit_id)
        if unit is None or scope.environment not in unit.enabled_environments:
            parser.error("canonical unit/environment is not configured")
        with database.economy(scope) as store:
            result = import_reviewed_state_benefit(
                store, snapshot_id=bundle["snapshot_id"],
                snapshot_version=bundle["snapshot_version"],
                competence=date.fromisoformat(bundle["competence"]),
                issuer=Cnpj(bundle["issuer_cnpj"]), content=bundle["content"],
                benefit_id=bundle["benefit_id"],
                benefit_version=bundle["benefit_version"],
                benefit_content=bundle["benefit_content"],
                verify_issuer=build_state_issuer_verifier(database, scope),
            )
        print(json.dumps({
            "snapshot_id": result["snapshot_id"],
            "snapshot_digest": result["snapshot_digest"],
            "benefit_id": result["benefit_id"],
            "benefit_digest": result["benefit_digest"],
            "status": result["status"],
            "advisory_only": True,
        }, sort_keys=True))
    finally:
        database.close()


if __name__ == "__main__":
    main()
