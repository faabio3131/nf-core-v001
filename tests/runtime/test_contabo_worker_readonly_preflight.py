"""Only read-only, synthetic tests for NFCore Contabo worker inventory."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "nfcore_worker_inventory",
    Path(__file__).resolve().parents[2] / "deploy/contabo/worker-readonly-preflight.py",
)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
SHA = "a" * 40


def _worker_info(*, env: list[str] | None = None, privileged: bool = False) -> dict:
    return {
        "State": {"Status": "running", "Health": {"Status": "healthy"}},
        "Config": {
            "User": "10001:10001",
            "Env": env if env is not None else [
                "NFCORE_ENVIRONMENT=production",
                "NFCORE_SECRET_BACKEND=external",
                "NFCORE_WORKER_GSM_MODE=multi-tenant-production-sa-v1",
                "SENSITIVE_API_TOKEN=do-not-leak",
            ],
        },
        "HostConfig": {
            "ReadonlyRootfs": True,
            "Privileged": privileged,
            "PortBindings": {},
            "SecurityOpt": ["no-new-privileges:true"],
            "CapDrop": ["ALL"],
            "RestartPolicy": {"Name": "no"},
        },
        "NetworkSettings": {"Networks": {"nfcore_internal": {}}},
        "Mounts": [{
            "Destination": "/run/nfcore/worker-identity.json",
            "Source": "/opt/fm/nfcore/identity/worker.json",
            "Type": "bind",
            "RW": False,
        }],
    }


def test_metadata_never_reads_file_bytes(tmp_path: Path) -> None:
    f = tmp_path / "secret"
    f.write_text("sensitive private key", encoding="utf-8")
    f.chmod(0o600)
    assert audit.metadata(f) == "RESTRICTED"
    f.chmod(0o644)
    assert audit.metadata(f) == "ACCESS_TOO_BROAD"
    f.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(f)
    assert audit.metadata(link) == "SYMLINK_DENIED"
    assert audit.metadata(tmp_path / "missing") == "ABSENT"


def test_container_policy_never_returns_secret_or_path_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = _worker_info()
    monkeypatch.setattr(audit, "only_expected_mount", lambda *_a: "RESTRICTED")
    result = audit.worker_policy(info, bling=False)
    assert result["POLICY_NONROOT"] == "PASS"
    assert result["POLICY_MOUNT"] == "RESTRICTED"
    assert result["POLICY_RESTART"] == "NOT_SUPERVISED"
    assert result["POLICY_INTERNAL_NET"] == "PASS"
    assert result["POLICY_CONNECTOR"] == "PASS"
    assert all("do-not-leak" not in v for v in result.values())


def test_privilege_and_cross_network_violation_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = _worker_info(privileged=True)
    info["NetworkSettings"]["Networks"]["proxy-net"] = {}
    monkeypatch.setattr(audit, "only_expected_mount", lambda *_a: "RESTRICTED")
    result = audit.worker_policy(info, bling=False)
    assert result["POLICY_UNPRIVILEGED"] == "NO_GO"
    assert result["POLICY_INTERNAL_NET"] == "NO_GO"


def test_wrong_worker_mode_is_not_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = _worker_info(env=[
        "NFCORE_ENVIRONMENT=production",
        "NFCORE_SECRET_BACKEND=external",
        "NFCORE_WORKER_GSM_MODE=scoped-production-sa-v1",
    ])
    monkeypatch.setattr(audit, "only_expected_mount", lambda *_a: "RESTRICTED")
    assert audit.worker_policy(info, bling=False)["POLICY_CONNECTOR"] == "NO_GO"


def test_bling_cannot_pretend_to_be_gsm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = _worker_info(env=[
        "NFCORE_ENVIRONMENT=production",
        "NFCORE_SECRET_BACKEND=external",
        "NFCORE_WORKER_GSM_MODE=multi-tenant-production-sa-v1",
        "NFCORE_WORKER_CONNECTOR=bling-multi",
        "NFCORE_BLING_INSTALLATIONS_ENABLED=true",
    ])
    monkeypatch.setattr(audit, "only_expected_mount", lambda *_a: "RESTRICTED")
    assert audit.worker_policy(info, bling=True)["POLICY_CONNECTOR"] == "NO_GO"


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit.os, "uname", lambda: SimpleNamespace(nodename=audit.HOST))
    monkeypatch.setattr(audit, "command_sha", lambda: SHA)
    (tmp_path / ".deployed").write_text(f"SHA={SHA}\n", encoding="ascii")

    def configure(containers: dict[str, dict]):
        names = set(containers)

        def fake_docker(args: list[str]) -> str | None:
            if args == ["ps", "-a", "--format", "{{.Names}}"]:
                return "\n".join(names) + "\n"
            if args[:2] == ["inspect", "--type=container"]:
                return json.dumps([containers[args[2]]])
            raise AssertionError("unexpected Docker API request")

        monkeypatch.setattr(audit, "docker", fake_docker)
    return configure


def test_missing_workers_never_count_as_ready(host) -> None:
    host({name: _worker_info() for name in ("nfcore-db", "nfcore-api", "nfcore-portal")})
    result = audit.collect(SHA)
    assert result["DOCKER_ACCESS"] == "PASS"
    assert result["NFCORE_WORKER"] == "ABSENT"
    assert result["NFCORE_BLING_WORKER"] == "ABSENT"
    assert result["RESULT"] == "NO_GO_GENERAL_WORKER"


def test_remote_outbox_and_gcp_authorization_never_inferred_from_host(host) -> None:
    host({name: _worker_info() for name in ("nfcore-db", "nfcore-api", "nfcore-portal")})
    result = audit.collect(SHA)
    assert result["LOCAL_OTHER_NFCORE_WORKERS"] == "ABSENT"
    assert result["REMOTE_OUTBOX_CONSUMERS"] == "UNVERIFIED_EXTERNAL"
    assert result["GSM_IDENTITY_PROVIDER"] == "UNVERIFIED_EXTERNAL"


def test_local_rehearsal_worker_requires_concurrency_review(
    host, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    f = tmp_path / ".env.worker"
    f.write_text("synthetic-secret-not-for-output", encoding="utf-8")
    f.chmod(0o600)
    host({name: _worker_info() for name in (
        "nfcore-db", "nfcore-api", "nfcore-portal",
        "nfcore-worker", "nfcore-ensaio-worker-1",
    )})
    monkeypatch.setattr(audit, "only_expected_mount", lambda *_a: "RESTRICTED")
    result = audit.collect(SHA)
    assert result["LOCAL_OTHER_NFCORE_WORKERS"] == "PRESENT"
    assert result["RESULT"] == "NO_GO_POSSIBLE_LOCAL_CONSUMER"
    assert "synthetic-secret-not-for-output" not in str(result)


def test_wrong_release_pin_fails_even_if_api_healthy(host) -> None:
    host({name: _worker_info() for name in ("nfcore-db", "nfcore-api", "nfcore-portal")})
    result = audit.collect("b" * 40)
    assert result["RESULT"] == "NO_GO_RELEASE_OR_HOST_PIN"


def test_no_env_file_cannot_be_accepted_for_running_worker(
    host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    host({name: _worker_info() for name in (
        "nfcore-db", "nfcore-api", "nfcore-portal", "nfcore-worker",
    )})
    monkeypatch.setattr(audit, "only_expected_mount", lambda *_a: "RESTRICTED")
    result = audit.collect(SHA)
    assert result["WORKER_ENV"] == "ABSENT"
    assert result["RESULT"] == "NO_GO_WORKER_CONFIGURATION"


def test_policy_failure_is_not_hidden_by_healthy_status(
    host, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    f = tmp_path / ".env.worker"
    f.write_text("private-content-do-not-print", encoding="utf-8")
    f.chmod(0o600)
    host({
        **{name: _worker_info() for name in ("nfcore-db", "nfcore-api", "nfcore-portal")},
        "nfcore-worker": _worker_info(privileged=True),
    })
    monkeypatch.setattr(audit, "only_expected_mount", lambda *_a: "RESTRICTED")
    result = audit.collect(SHA)
    assert result["RESULT"] == "NO_GO_WORKER_SECURITY"
    assert "private-content-do-not-print" not in str(result)


def test_deployment_marker_must_match_real_deploy_format(host, monkeypatch, tmp_path: Path) -> None:
    host({name: _worker_info() for name in ("nfcore-db", "nfcore-api", "nfcore-portal")})
    state = tmp_path / ".deployed"
    assert audit.collect(SHA)["SOURCE_VS_DEPLOYED"] == "PASS"
    state.write_text(SHA, encoding="ascii")
    assert audit.collect(SHA)["RESULT"] == "NO_GO_RELEASE_OR_HOST_PIN"
    state.write_text(f"SHA={SHA}\nSHA={SHA}\n", encoding="ascii")
    assert audit.collect(SHA)["RESULT"] == "NO_GO_RELEASE_OR_HOST_PIN"


def test_no_go_inventory_must_exit_nonzero(monkeypatch, capsys) -> None:
    monkeypatch.setattr(audit, "collect", lambda _sha: {
        "HOST": "PASS", "DOCKER_ACCESS": "PASS", "RESULT": "NO_GO_GENERAL_WORKER",
    })
    monkeypatch.setattr(
        "sys.argv", ["worker-readonly-preflight.py", "--expected-production-sha", SHA],
    )
    assert audit.main() == 2
    assert "RESULT=NO_GO_GENERAL_WORKER" in capsys.readouterr().out


def test_secret_mount_source_cannot_escape_nfcore_namespace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    root = tmp_path / "nfcore"
    other = tmp_path / "other-saas"
    root.mkdir()
    other.mkdir()
    approved = root / "worker.json"
    foreign = other / "worker.json"
    approved.write_text("synthetic", encoding="utf-8")
    foreign.write_text("synthetic", encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", root)
    assert audit.approved_nfcore_secret_source(approved)
    assert not audit.approved_nfcore_secret_source(foreign)
    alias = root / "foreign-alias"
    alias.symlink_to(other, target_is_directory=True)
    assert not audit.approved_nfcore_secret_source(alias / "worker.json")
    assert not audit.approved_nfcore_secret_source(root / ".." / "other-saas" / "worker.json")
