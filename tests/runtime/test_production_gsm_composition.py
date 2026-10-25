"""Production GSM bootstrap contract tests; no Google Cloud or persistent DB writes."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from kordena_fiscal.runtime import production_gsm as gsm
from kordena_fiscal.runtime.config import RuntimeConfigurationError, RuntimeEnvironment
from kordena_fiscal.security.secret_binding import SecretBinding

NOW = datetime.now(UTC)


def production_env(tmp_path: Path) -> dict[str, str]:
    keyfile = tmp_path / "worker-private.json"
    keyfile.write_text("s" * 255)
    keyfile.chmod(0o600)
    common = {
        "NFCORE_ENVIRONMENT": "production",
        "NFCORE_GSM_ALLOWED_PROJECTS": "fm-core-live",
        "NFCORE_GSM_PROJECT_ID": "fm-core-live",
        "NFCORE_GSM_PROJECT_NUMBER": "123456789012",
        "NFCORE_GSM_API_SERVICE_ACCOUNT": "nfcore-api@fm-core-live.iam.gserviceaccount.com",
        "NFCORE_GSM_WORKER_SERVICE_ACCOUNT": "nfcore-worker@fm-core-live.iam.gserviceaccount.com",
        "NFCORE_PRODUCTION_GSM_BINDINGS_MODE": "platform-admin-v1",
    }
    for role in ("API", "WORKER"):
        prefix = f"NFCORE_{role}_GSM_"
        common.update(
            {
                prefix + "MODE": "scoped-production-sa-v1",
                prefix + "TENANT_ID": "fm-platform",
                prefix + "UNIT_ID": "production-unit",
                prefix + "SIGNING_REFERENCE": f"sec_nfcore_production_{role.lower()}_signing",
                prefix + "SIGNING_VERSION": "1",
                prefix + "PROVIDER_ID": "google-secret-manager",
                prefix + "RESOURCE": f"projects/fm-core-live/secrets/nfcore-{role.lower()}-signing",
                prefix + "CLOUD_VERSION": "1",
                prefix + "CREDENTIAL_FILE": str(keyfile),
                prefix + "KEY_ID": "a" * 40,
                prefix + "KEY_CREATED_AT": (NOW - timedelta(days=1)).isoformat(),
                prefix + "KEY_NOT_AFTER": (NOW + timedelta(days=30)).isoformat(),
            }
        )
    common.update(
        {
            "NFCORE_WORKER_GSM_HOST_NAMESPACE": "nfcore-production",
            "NFCORE_WORKER_GSM_DESTINATION_ID": "webhook-production",
        }
    )
    return common


class FakeDatabase:
    def __init__(self, bindings: dict[str, SecretBinding]):
        self.bindings = bindings
        self.reads = 0

    @contextmanager
    def __call__(self):
        self.reads += 1
        yield SimpleNamespace(
            secret_bindings=SimpleNamespace(get=lambda ref: self.bindings.get(ref)),
        )


def test_production_scopes_have_separate_identity_and_binding(tmp_path: Path) -> None:
    cfg = production_env(tmp_path)
    worker, api = gsm.provisionable_production_bindings(cfg)
    assert worker.workload_id == "nfcore-worker"
    assert api.workload_id == "nfcore-api"
    assert worker.reference_id != api.reference_id
    assert worker.resource != api.resource
    assert worker.runtime_environment == api.runtime_environment == "production"
    assert worker.fiscal_environment is api.fiscal_environment is None
    assert worker.cloud_version == "1"


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("NFCORE_ENVIRONMENT", "staging"),
        ("NFCORE_GSM_PROJECT_ID", "fm-nfcore-staging"),
        ("NFCORE_GSM_ALLOWED_PROJECTS", "fm-unrelated"),
        ("NFCORE_GSM_ALLOWED_PROJECTS", "fm-core-live,fm-core-live"),
        ("NFCORE_GSM_PROJECT_NUMBER", "foo"),
        ("NFCORE_GSM_API_SERVICE_ACCOUNT", "nfcore-worker@fm-core-live.iam.gserviceaccount.com"),
        ("NFCORE_WORKER_GSM_UNIT_ID", "*"),
        ("NFCORE_WORKER_GSM_SIGNING_VERSION", "0"),
        ("NFCORE_WORKER_GSM_RESOURCE", "projects/other-project/secrets/k"),
        ("NFCORE_WORKER_GSM_CLOUD_VERSION", "latest"),
        ("NFCORE_API_GSM_RESOURCE", "projects/fm-nfcore-staging/secrets/x"),
    ],
)
def test_production_configuration_denies_unapproved_scopes(
    tmp_path: Path, field: str, invalid: str
) -> None:
    cfg = production_env(tmp_path)
    cfg[field] = invalid
    with pytest.raises(RuntimeConfigurationError):
        gsm.provisionable_production_bindings(cfg)


def test_production_opt_in_is_exact_and_never_reuses_staging(tmp_path: Path) -> None:
    assert gsm.production_worker_handler_factory({}) is None
    cfg = production_env(tmp_path)
    cfg["NFCORE_WORKER_GSM_MODE"] = "scoped-staging-sa-v1"
    with pytest.raises(RuntimeConfigurationError):
        gsm.production_worker_handler_factory(cfg)
    cfg["NFCORE_WORKER_GSM_MODE"] = "scoped-production-sa-v1"
    factory = gsm.production_worker_handler_factory(cfg)
    assert factory is not None
    with pytest.raises(RuntimeConfigurationError, match="requires production/external"):
        factory(
            FakeDatabase({}),  # type: ignore[arg-type]
            SimpleNamespace(environment=RuntimeEnvironment.STAGING, secret_backend="external"),
        )


def test_empty_or_wrong_binding_blocks_before_loading_private_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = production_env(tmp_path)
    worker = gsm.production_config(cfg, "WORKER")
    factory = gsm.production_worker_handler_factory(cfg)
    assert factory is not None
    monkeypatch.setattr(gsm, "production_credentials", lambda *_: pytest.fail("identity opened"))
    for bindings in (
        {},
        {worker.reference.reference_id: replace(worker.binding(), runtime_environment="staging")},
    ):
        db = FakeDatabase(bindings)
        with pytest.raises(RuntimeConfigurationError, match="durable binding"):
            factory(
                db,  # type: ignore[arg-type]
                SimpleNamespace(
                    environment=RuntimeEnvironment.PRODUCTION, secret_backend="external"
                ),
            )
        assert db.reads == 1


def test_production_binding_rejects_replay_with_new_identity(tmp_path: Path) -> None:
    cfg = production_env(tmp_path)
    cfg["NFCORE_API_GSM_SIGNING_REFERENCE"] = cfg["NFCORE_WORKER_GSM_SIGNING_REFERENCE"]
    with pytest.raises(RuntimeConfigurationError, match="must differ"):
        gsm.provisionable_production_bindings(cfg)


def test_credential_source_is_file_only_and_bounded(tmp_path: Path) -> None:
    cfg = production_env(tmp_path)
    role = gsm.production_config(cfg, "WORKER")
    cfg["NFCORE_WORKER_GSM_CREDENTIAL_JSON"] = '{"type":"service_account"}'
    with pytest.raises(RuntimeConfigurationError):
        gsm.production_credentials(cfg, role)
    cfg.pop("NFCORE_WORKER_GSM_CREDENTIAL_JSON")
    cfg["NFCORE_WORKER_GSM_KEY_NOT_AFTER"] = (NOW + timedelta(days=200)).isoformat()
    with pytest.raises(RuntimeConfigurationError):
        gsm.production_credentials(cfg, role)
    cfg["NFCORE_WORKER_GSM_KEY_NOT_AFTER"] = (NOW + timedelta(days=20)).isoformat()
    Path(cfg["NFCORE_WORKER_GSM_CREDENTIAL_FILE"]).chmod(0o644)
    with pytest.raises(RuntimeConfigurationError):
        gsm.production_credentials(cfg, role)


def test_api_probe_explicit_mode_denied_with_empty_production_db(tmp_path: Path) -> None:
    cfg = production_env(tmp_path)
    with pytest.raises(RuntimeConfigurationError, match="durable binding"):
        gsm.production_api_verifier(FakeDatabase({}), cfg)  # type: ignore[arg-type]


def test_worker_still_requires_durable_binding_and_real_gsm_read(tmp_path: Path) -> None:
    cfg = production_env(tmp_path)
    worker = gsm.production_config(cfg, "WORKER")
    with pytest.raises(RuntimeConfigurationError):
        gsm.validated_binding(FakeDatabase({}), worker)  # type: ignore[arg-type]
    assert worker.binding().state == "active"
    # The production mode never synthesizes a local secret or a signing handler.
    assert gsm.production_worker_handler_factory(cfg) is not None
