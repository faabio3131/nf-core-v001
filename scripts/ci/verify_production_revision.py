"""Read-only production promotion gate: exact protected HEAD and full CI success.

The approval token is necessary but insufficient. Promotion may only target the
current protected production branch revision after its own push-triggered
comprehensive CI has finished successfully. No guess from prior PR runs.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_MAX_JSON_BYTES = 1_048_576
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


class ProductionRevisionNotCertified(RuntimeError):
    """Source branch/current CI mismatch; no deploy is permitted."""


def _github_read(endpoint: str, token: str) -> dict[str, Any]:
    """Official HTTPS GitHub API only; no user-defined host/redirect or secret logging."""
    if not endpoint.startswith("/repos/") or "?" in endpoint.split("/repos/", 1)[0]:
        raise ProductionRevisionNotCertified("Invalid GitHub evidence endpoint")
    if not token or len(token) > 4096:
        raise ProductionRevisionNotCertified("GitHub Actions evidence token unavailable")
    request = Request(
        "https://api.github.com" + endpoint,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nfcore-release-verifier",
        },
    )
    try:
        with urlopen(request, timeout=12) as response:
            content = response.read(_MAX_JSON_BYTES + 1)
        if len(content) > _MAX_JSON_BYTES:
            raise ValueError("evidence too large")
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("invalid evidence response")
        return data
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, UnicodeError):
        raise ProductionRevisionNotCertified(
            "GitHub production revision or CI evidence unavailable"
        ) from None


def verify_production_revision(
    *,
    revision: str,
    repository: str,
    read_json: Callable[[str], dict[str, Any]],
) -> None:
    """No CI result from a PR, other branch, or previous SHA can authorize deploy."""
    if (
        not isinstance(revision, str)
        or not _SHA40.fullmatch(revision)
        or not isinstance(repository, str)
        or not _REPOSITORY.fullmatch(repository)
    ):
        raise ProductionRevisionNotCertified("Invalid release source SHA or repository")
    base = "/repos/" + repository
    production = read_json(base + "/branches/production")
    if (
        not production.get("protected")
        or not isinstance(production.get("commit"), dict)
        or production["commit"].get("sha") != revision
    ):
        raise ProductionRevisionNotCertified(
            "Release revision differs from current protected production HEAD"
        )
    evidence = read_json(
        base + "/actions/runs?head_sha=" + revision
        + "&branch=production&event=push&per_page=100"
    )
    runs = evidence.get("workflow_runs")
    if not isinstance(runs, list):
        raise ProductionRevisionNotCertified("Production full CI evidence is invalid")
    certified = any(
        isinstance(run, dict)
        and run.get("head_sha") == revision
        and run.get("head_branch") == "production"
        and run.get("event") == "push"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and isinstance(run.get("path"), str)
        and run["path"].split("@", 1)[0] == ".github/workflows/ci.yml"
        for run in runs
    )
    if not certified:
        raise ProductionRevisionNotCertified(
            "Full production-push CI has not passed on exact release SHA"
        )


def main() -> int:
    token = os.environ.get("GH_TOKEN", "")
    revision = os.environ.get("NFCORE_SOURCE_REVISION", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    try:
        verify_production_revision(
            revision=revision,
            repository=repository,
            read_json=lambda endpoint: _github_read(endpoint, token),
        )
    except ProductionRevisionNotCertified as exc:
        print("Production promotion blocked: " + str(exc), file=sys.stderr)
        return 42
    print("Production revision gate: PASS exact protected SHA and full CI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
