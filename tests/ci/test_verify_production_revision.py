"""Fail-closed production release revision/CI checks with synthetic GitHub evidence."""
from __future__ import annotations

from collections.abc import Callable
from importlib import util
from pathlib import Path
from typing import Any

import pytest

# scripts/ is deliberately not an installed Python package in NFCore. Load
# the exact production verifier source rather than importing a shadow module.
_LOCATION = Path(__file__).resolve().parents[2] / "scripts/ci/verify_production_revision.py"
_SPEC = util.spec_from_file_location("nfcore_production_revision", _LOCATION)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
ProductionRevisionNotCertified = _MODULE.ProductionRevisionNotCertified
verify_production_revision = _MODULE.verify_production_revision

_SHA = "a" * 40
_REPO = "faabio3131/nf-core-v001"


def _read(
    *, sha: str = _SHA, protected: bool = True, result: str = "success",
    branch: str = "production", event: str = "push",
    workflow_path: str = ".github/workflows/ci.yml", status: str = "completed",
) -> Callable[[str], dict[str, Any]]:
    def read_json(endpoint: str) -> dict[str, Any]:
        if endpoint == f"/repos/{_REPO}/branches/production":
            return {"protected": protected, "commit": {"sha": sha}}
        if endpoint.startswith(f"/repos/{_REPO}/actions/runs?"):
            return {"workflow_runs": [{
                "head_sha": _SHA,
                "head_branch": branch,
                "event": event,
                "status": status,
                "conclusion": result,
                "path": workflow_path,
            }]}
        raise AssertionError("unexpected GitHub path")
    return read_json


def test_verified_protected_head_and_push_ci_pass() -> None:
    verify_production_revision(revision=_SHA, repository=_REPO, read_json=_read())


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"sha": "b" * 40}, "differs"),
        ({"protected": False}, "differs"),
        ({"result": "failure"}, "has not passed"),
        ({"result": "cancelled"}, "has not passed"),
        ({"branch": "main"}, "has not passed"),
        ({"event": "pull_request"}, "has not passed"),
        ({"workflow_path": ".github/workflows/other.yml"}, "has not passed"),
        ({"status": "in_progress"}, "has not passed"),
    ],
)
def test_rejects_stale_ci_or_unprotected_release(
    kw: dict[str, Any], message: str,
) -> None:
    with pytest.raises(ProductionRevisionNotCertified, match=message):
        verify_production_revision(
            revision=_SHA, repository=_REPO, read_json=_read(**kw)
        )


@pytest.mark.parametrize("bad", ["", "main", "g" * 40, "a" * 39, "a" * 41])
def test_rejects_nonimmutable_sha(bad: str) -> None:
    with pytest.raises(ProductionRevisionNotCertified, match="Invalid"):
        verify_production_revision(revision=bad, repository=_REPO, read_json=_read())


def test_rejects_noncanonical_repository_and_missing_evidence() -> None:
    with pytest.raises(ProductionRevisionNotCertified, match="Invalid"):
        verify_production_revision(
            revision=_SHA, repository="../other/repo", read_json=_read()
        )
    with pytest.raises(ProductionRevisionNotCertified, match="invalid"):
        verify_production_revision(
            revision=_SHA, repository=_REPO,
            read_json=lambda endpoint: (
                {"protected": True, "commit": {"sha": _SHA}}
                if endpoint.endswith("/branches/production")
                else {"workflow_runs": "not-a-list"}
            ),
        )


def test_gate_never_uses_prior_pr_ci_or_other_sha() -> None:
    def stale(endpoint: str) -> dict[str, Any]:
        if endpoint.endswith("/branches/production"):
            return {"protected": True, "commit": {"sha": _SHA}}
        return {"workflow_runs": [{
            "head_sha": "b" * 40,
            "head_branch": "production", "event": "push",
            "conclusion": "success", "status": "completed",
            "path": ".github/workflows/ci.yml",
        }]}
    with pytest.raises(ProductionRevisionNotCertified, match="has not passed"):
        verify_production_revision(
            revision=_SHA, repository=_REPO, read_json=stale
        )
