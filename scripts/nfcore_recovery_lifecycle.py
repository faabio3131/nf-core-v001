"""T19 local sandbox command line, using canonical session and MFA authorities."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from kordena_fiscal.application.recovery_lifecycle import RecoveryCaseService, ReviewedEvent
from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.security.human_identity import (
    HumanIdentityError,
    HumanIdentityService,
    ScryptPasswordHasher,
)
from kordena_fiscal.security.human_mfa import HumanMfaService
from kordena_fiscal.tax.unused_credits import _unique_fields


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--post", type=Path)
    mode.add_argument("--report", action="store_true")
    parser.add_argument("--unit", required=True)
    parser.add_argument("--competence")
    args = parser.parse_args()
    if os.environ.get("NFCORE_ENVIRONMENT") not in {"development", "test", "staging"}:
        parser.error("T19 requires a non-production environment")
    if os.environ.get("NFCORE_ECONOMY_ENABLED") != "true":
        parser.error("economy lifecycle unavailable")
    try:
        token = os.environ["NFCORE_T19_SESSION_TOKEN"]
        csrf = os.environ["NFCORE_T19_CSRF_TOKEN"]
        if args.post:
            with args.post.open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError("case input exceeds 64 KiB")
            reviewed = ReviewedEvent.model_validate(
                json.loads(raw, object_pairs_hook=_unique_fields)
            )
            if args.competence and args.competence != reviewed.event.terms.competence:
                raise ValueError("case competence mismatch")
            period = date.fromisoformat(reviewed.event.terms.competence)
        else:
            reviewed = None
            period = date.fromisoformat(args.competence or "")
            if period.day != 1:
                raise ValueError("report requires historical month")
        db = PostgresFiscalDatabase(os.environ["DATABASE_URL"])
    except (KeyError, ValueError, OSError, FiscalValidationError):
        parser.error("invalid sandbox input or missing session configuration")
    try:
        identity = HumanIdentityService(
            accounts=db.human_accounts(), sessions=db.web_sessions(),
            password_hasher=ScryptPasswordHasher(),
        )
        mfa = HumanMfaService.from_environ(db.human_mfa)
        if mfa is None:
            parser.error("canonical MFA unavailable")
        service = RecoveryCaseService(db, identity, mfa.has_recent_step_up)
        result = (
            service.read(token, csrf, args.unit, period)
            if reviewed is None
            else service.execute(token, csrf, args.unit, reviewed)
        )
        print(json.dumps(result, ensure_ascii=False))
    except (HumanIdentityError, FiscalValidationError, ValueError, KeyError, TypeError):
        parser.error("case evidence, authority or state invalid")
    finally:
        db.close()


if __name__ == "__main__":
    main()
