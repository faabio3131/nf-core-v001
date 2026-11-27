"""T20 sandbox dossier CLI, using the existing session and MFA authorities."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date
from pathlib import Path

from kordena_fiscal.application.accounting_dossier import AccountingDossierService
from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.security.human_identity import (
    HumanIdentityError,
    HumanIdentityService,
    ScryptPasswordHasher,
)
from kordena_fiscal.security.human_mfa import HumanMfaService


def _write_new(path: Path, raw: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--candidates", action="store_true")
    mode.add_argument("--output", type=Path)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--competence", required=True)
    parser.add_argument("--finding")
    parser.add_argument("--source-version", type=int)
    parser.add_argument("--source-digest")
    args = parser.parse_args()
    if (
        os.environ.get("NFCORE_ENVIRONMENT") not in {"development", "test", "staging"}
        or os.environ.get("NFCORE_ECONOMY_ENABLED") != "true"
        or os.environ.get("NFCORE_T20_DOSSIER_ENABLED") != "true"
    ):
        parser.error("T20 sandbox unavailable")
    try:
        token = os.environ["NFCORE_T20_SESSION_TOKEN"]
        csrf = os.environ["NFCORE_T20_CSRF_TOKEN"]
        period = date.fromisoformat(args.competence)
        if period.day != 1 or period.isoformat() != args.competence:
            raise ValueError("invalid competence")
        if args.output is not None and (
            not args.finding or args.source_version is None or not args.source_digest
            or os.path.lexists(args.output) or not args.output.parent.is_dir()
        ):
            raise ValueError("invalid selection or existing output")
        db = PostgresFiscalDatabase(os.environ["DATABASE_URL"])
    except (KeyError, ValueError, OSError):
        parser.error("invalid sandbox configuration")
    try:
        identity = HumanIdentityService(
            accounts=db.human_accounts(), sessions=db.web_sessions(),
            password_hasher=ScryptPasswordHasher(),
        )
        mfa = HumanMfaService.from_environ(db.human_mfa)
        if mfa is None:
            parser.error("canonical MFA unavailable")
        service = AccountingDossierService(db, identity, mfa.has_recent_step_up)
        if args.candidates:
            print(json.dumps(service.candidates(token, csrf, args.unit, period)))
        else:
            raw = service.export(
                token, csrf, args.unit, period, args.finding, args.source_version,
                args.source_digest,
            )
            _write_new(args.output, raw)
            print("Dossier exported; human review and signature pending.")
    except (HumanIdentityError, FiscalValidationError, ValueError, KeyError, TypeError, OSError):
        parser.error("dossier evidence, authority or destination invalid")
    finally:
        db.close()


if __name__ == "__main__":
    main()
