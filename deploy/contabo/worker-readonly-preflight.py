#!/usr/bin/env python3
"""NFCore-only Contabo worker host inventory. Read-only, with redacted output.

Does not open .env, private JSON, token, certificate, or vault content. Does not
inspect IRON or any other SaaS. No sudo, Docker exec, network, DDL or host writes.
A healthy container is not evidence of fiscal authorization or delivery E2E.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

HOST = "vmi3692211"
ROOT = Path("/opt/fm/nfcore")
CONTAINERS = ("nfcore-db", "nfcore-api", "nfcore-portal", "nfcore-worker",
              "nfcore-bling-worker", "nfcore-ensaio-worker-1")
SHA_RE = re.compile(r"^[a-f0-9]{40}$")


def metadata(path: Path, *, directory: bool = False) -> str:
    """Check metadata, not bytes; symlinks and group/world access fail closed."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "ABSENT"
    except OSError:
        return "UNVERIFIED"
    if stat.S_ISLNK(info.st_mode):
        return "SYMLINK_DENIED"
    if directory and not stat.S_ISDIR(info.st_mode):
        return "WRONG_TYPE"
    if not directory and not stat.S_ISREG(info.st_mode):
        return "WRONG_TYPE"
    if stat.S_IMODE(info.st_mode) & 0o077:
        return "ACCESS_TOO_BROAD"
    return "RESTRICTED"


def approved_nfcore_secret_source(path: Path) -> bool:
    """Fail closed before inspecting any mount source from another SaaS."""
    if not path.is_absolute() or ".." in path.parts:
        return False
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    # Do not follow a symlink outside an approved NFCore-owned namespace.
    allowed = (ROOT, Path("/etc/nfcore"), Path("/run/nfcore"))
    return any(path.is_relative_to(base) and resolved.is_relative_to(base) for base in allowed)


def docker(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["docker", *args], check=False, capture_output=True,
            text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def container_state(info: dict[str, Any] | None) -> str:
    if info is None:
        return "INSPECT_UNAVAILABLE"
    state = info.get("State") or {}
    if state.get("Status") != "running":
        return "NOT_RUNNING"
    health = (state.get("Health") or {}).get("Status")
    if health == "healthy":
        return "HEALTHY"
    if health in ("starting", "unhealthy"):
        return "NOT_HEALTHY"
    return "NO_HEALTH_PROOF"


def inspect_container(name: str) -> dict[str, Any] | None:
    raw = docker(["inspect", "--type=container", name])
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list) or len(parsed) != 1:
            return None
        return parsed[0] if isinstance(parsed[0], dict) else None
    except ValueError:
        return None


def only_expected_mount(info: dict[str, Any], dest: str, kind: str) -> str:
    mounts = [
        m for m in (info.get("Mounts") or [])
        if isinstance(m, dict) and m.get("Destination") == dest
    ]
    if len(mounts) != 1:
        return "ABSENT_OR_AMBIGUOUS"
    mount = mounts[0]
    if mount.get("Type") != "bind" or mount.get("RW") is not False:
        return "NOT_READ_ONLY_BIND"
    source = mount.get("Source")
    if not isinstance(source, str) or not source.startswith("/"):
        return "INVALID_SOURCE"
    if not approved_nfcore_secret_source(Path(source)):
        return "CROSS_SAAS_SOURCE_DENIED"
    state = metadata(Path(source), directory=kind == "directory")
    if state != "RESTRICTED":
        return state
    try:
        return "RESTRICTED" if Path(source).lstat().st_uid == 10001 else "OWNER_MISMATCH"
    except OSError:
        return "UNVERIFIED"


def worker_policy(info: dict[str, Any], *, bling: bool) -> dict[str, str]:
    host = info.get("HostConfig") or {}
    cfg = info.get("Config") or {}
    env: dict[str, str] = {}
    # Sensitive values exist in memory ONLY. No raw Docker inspect or env output.
    for entry in cfg.get("Env") or []:
        if isinstance(entry, str) and "=" in entry:
            name, value = entry.split("=", 1)
            env[name] = value
    expected_mode = "multi-tenant-production-sa-v1"
    target = "/run/nfcore/bling" if bling else "/run/nfcore/worker-identity.json"
    network_names = set((info.get("NetworkSettings") or {}).get("Networks") or {})
    no_new_privileges = "no-new-privileges:true" in (host.get("SecurityOpt") or [])
    checks = {
        "POLICY_NONROOT": "PASS" if cfg.get("User") == "10001:10001" else "NO_GO",
        "POLICY_READONLY_FS": "PASS" if host.get("ReadonlyRootfs") is True else "NO_GO",
        "POLICY_UNPRIVILEGED": "PASS" if host.get("Privileged") is False else "NO_GO",
        "POLICY_NO_PORTS": "PASS" if not host.get("PortBindings") else "NO_GO",
        "POLICY_NO_NEW_PRIVS": "PASS" if no_new_privileges else "NO_GO",
        "POLICY_CAP_DROP": "PASS" if "ALL" in (host.get("CapDrop") or []) else "NO_GO",
        "POLICY_INTERNAL_NET": "PASS" if network_names == {"nfcore_internal"} else "NO_GO",
        "POLICY_ENV": "PASS" if env.get("NFCORE_ENVIRONMENT") == "production"
            and env.get("NFCORE_SECRET_BACKEND") == "external" else "NO_GO",
        "POLICY_MOUNT": only_expected_mount(info, target, "directory" if bling else "file"),
    }
    if bling:
        checks["POLICY_CONNECTOR"] = (
            "PASS" if env.get("NFCORE_WORKER_CONNECTOR") == "bling-multi"
            and env.get("NFCORE_BLING_INSTALLATIONS_ENABLED") == "true"
            and not env.get("NFCORE_WORKER_GSM_MODE") else "NO_GO"
        )
    else:
        checks["POLICY_CONNECTOR"] = (
            "PASS" if env.get("NFCORE_WORKER_GSM_MODE") == expected_mode
            and not env.get("NFCORE_WORKER_CONNECTOR") else "NO_GO"
        )
    # A restart policy is not itself proof of successful restart / backup.
    checks["POLICY_RESTART"] = (
        "PRESENT" if (host.get("RestartPolicy") or {}).get("Name") == "unless-stopped"
        else "NOT_SUPERVISED"
    )
    return checks


def command_sha() -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(ROOT / "src"), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=8, check=False,
        )
        value = r.stdout.strip()
        return value if r.returncode == 0 and SHA_RE.fullmatch(value) else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def collect(expected_sha: str) -> dict[str, str]:
    output: dict[str, str] = {
        "FORMAT": "NFCORE_WORKERS_READONLY_V1",
        "HOST": "PASS" if os.uname().nodename == HOST else "NO_GO",
    }
    source_sha = command_sha()
    try:
        state_lines = (ROOT / ".deployed").read_text(encoding="ascii").splitlines()
        # deploy.sh writes exactly SHA=<40-char commit>, not a bare commit SHA.
        deployed = (
            state_lines[0][4:]
            if len(state_lines) == 1
            and state_lines[0].startswith("SHA=")
            and SHA_RE.fullmatch(state_lines[0][4:])
            else ""
        )
    except (OSError, UnicodeError):
        deployed = ""
    output["SOURCE_VS_DEPLOYED"] = (
        "PASS" if source_sha is not None and source_sha == deployed else "NO_GO"
    )
    output["DEPLOY_VS_PIN"] = (
        "PASS" if source_sha == expected_sha and deployed == expected_sha else "NO_GO"
    )
    for key, filename in (
        ("WORKER_ENV", ".env.worker"),
        ("BLING_WORKER_ENV", ".env.bling.worker"),
        ("BLING_API_ENV", ".env.bling.api"),
        ("BLING_OVERRIDE", "docker-compose.override.yml"),
    ):
        output[key] = metadata(ROOT / filename)
    names_raw = docker(["ps", "-a", "--format", "{{.Names}}"])
    if names_raw is None:
        output["DOCKER_ACCESS"] = "NO_GO"
        output["RESULT"] = "NO_GO_HOST_INVENTORY"
        return output
    output["DOCKER_ACCESS"] = "PASS"
    names = set(names_raw.splitlines())
    # An inventory of Docker container names is not a complete outbox lock audit.
    # Never inspect unrelated SaaS containers or report remote leases as clear.
    output["LOCAL_OTHER_NFCORE_WORKERS"] = (
        "PRESENT" if any(
            name.startswith("nfcore-") and "worker" in name
            and name not in ("nfcore-worker", "nfcore-bling-worker")
            for name in names
        ) else "ABSENT"
    )
    output["REMOTE_OUTBOX_CONSUMERS"] = "UNVERIFIED_EXTERNAL"
    output["GSM_IDENTITY_PROVIDER"] = "UNVERIFIED_EXTERNAL"
    for name in CONTAINERS:
        prefix = name.upper().replace("-", "_")
        if name not in names:
            output[prefix] = "ABSENT"
            continue
        info = inspect_container(name)
        output[prefix] = container_state(info)
        if info is not None and name in ("nfcore-worker", "nfcore-bling-worker"):
            for key, val in worker_policy(info, bling=name == "nfcore-bling-worker").items():
                output[prefix + "_" + key] = val
    for suffix in ("API", "DB", "PORTAL"):
        if output.get("NFCORE_" + suffix) != "HEALTHY":
            output["RESULT"] = "NO_GO_HOST_BASELINE"
            return output
    if (
        output["HOST"] != "PASS"
        or output["SOURCE_VS_DEPLOYED"] != "PASS"
        or output["DEPLOY_VS_PIN"] != "PASS"
    ):
        output["RESULT"] = "NO_GO_RELEASE_OR_HOST_PIN"
        return output
    for component, file_gate in (
        ("NFCORE_WORKER", "WORKER_ENV"),
        ("NFCORE_BLING_WORKER", "BLING_WORKER_ENV"),
    ):
        if output.get(component) != "HEALTHY":
            continue
        if output.get(file_gate) != "RESTRICTED":
            output["RESULT"] = "NO_GO_WORKER_CONFIGURATION"
            return output
        check_prefix = component + "_POLICY_"
        if any(
            val not in ("PASS", "RESTRICTED")
            for key, val in output.items()
            if key.startswith(check_prefix) and key != component + "_POLICY_RESTART"
        ):
            output["RESULT"] = "NO_GO_WORKER_SECURITY"
            return output
    if output.get("NFCORE_WORKER") != "HEALTHY":
        output["RESULT"] = "NO_GO_GENERAL_WORKER"
    elif output["LOCAL_OTHER_NFCORE_WORKERS"] == "PRESENT":
        # Treat the possible rehearsal consumer as a blocker until scoped
        # outbox ownership is proven; a container name alone proves no lock.
        output["RESULT"] = "NO_GO_POSSIBLE_LOCAL_CONSUMER"
    elif output.get("NFCORE_WORKER_POLICY_RESTART") != "PRESENT":
        output["RESULT"] = "GENERAL_WORKER_RUNNING_RECOVERY_NOT_CERTIFIED"
    elif output.get("NFCORE_BLING_WORKER") != "HEALTHY":
        output["RESULT"] = "GENERAL_WORKER_PRESENT_BLING_NOT_ACTIVE"
    elif output.get("NFCORE_BLING_WORKER_POLICY_RESTART") != "PRESENT":
        output["RESULT"] = "BLING_WORKER_RUNNING_RECOVERY_NOT_CERTIFIED"
    else:
        output["RESULT"] = "WORKERS_PRESENT_EXTERNAL_E2E_UNVERIFIED"
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="NFCore-only read-only worker inventory")
    parser.add_argument("--expected-production-sha", required=True)
    args = parser.parse_args()
    if SHA_RE.fullmatch(args.expected_production_sha) is None:
        parser.error("expected-production-sha must be a 40-character lowercase SHA")
    report = collect(args.expected_production_sha)
    for key, value in report.items():
        if not re.fullmatch(r"[A-Z0-9_]{1,75}", key):
            raise RuntimeError("inventory key invalid")
        if not re.fullmatch(r"[A-Za-z0-9_]{1,100}", value):
            raise RuntimeError("inventory value invalid")
        print(key + "=" + value)
    # A successful inventory run is NOT an authorization to launch workers.
    return 2 if report["RESULT"].startswith("NO_GO") else 0


if __name__ == "__main__":
    raise SystemExit(main())
