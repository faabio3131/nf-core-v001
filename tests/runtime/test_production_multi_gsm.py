"""Multi-tenant GSM regression without cloud, persistent migration or host access."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kordena_fiscal.contingency import FiscalOutboxStatus
from kordena_fiscal.domain import FiscalEnvironment
from kordena_fiscal.runtime.config import RuntimeConfigurationError, RuntimeEnvironment
from kordena_fiscal.runtime.production_multi_gsm import (
    MULTI_MODE,
    MultiTenantGsmWorkerComposition,
    platform_project,
    production_multi_worker_handler_factory,
    production_worker_bindings,
)
from kordena_fiscal.security.secret_binding import SecretBinding
from kordena_fiscal.security.secrets import SecretResolutionError, SecretScope
from kordena_fiscal.vault.google_secret_manager import DurableGsmReader

NOW = datetime(2026, 10, 26, tzinfo=UTC)


def binding(tenant: str, unit: str, *, state: str = "active", ref: str = "") -> SecretBinding:
    return SecretBinding(
        reference_id=ref or f"sec_nfcore_{tenant}_{unit}_signing",
        tenant_id=tenant,
        unit_id=unit,
        purpose="webhook-signing",
        runtime_environment="production",
        fiscal_environment=None,
        provider_id="google-secret-manager",
        workload_id="nfcore-worker",
        kind="signature",
        canonical_version=1,
        resource=f"projects/fm-core-live/secrets/{tenant}-{unit}-signing",
        cloud_version="1",
        state=state,
    )


def env() -> dict[str, str]:
    return {
        "NFCORE_ENVIRONMENT": "production",
        "NFCORE_WORKER_GSM_MODE": MULTI_MODE,
        "NFCORE_GSM_PROJECT_ID": "fm-core-live",
        "NFCORE_GSM_PROJECT_NUMBER": "123456789012",
        "NFCORE_GSM_ALLOWED_PROJECTS": "fm-core-live",
        "NFCORE_GSM_API_SERVICE_ACCOUNT": "nfcore-api@fm-core-live.iam.gserviceaccount.com",
        "NFCORE_GSM_WORKER_SERVICE_ACCOUNT": "nfcore-worker@fm-core-live.iam.gserviceaccount.com",
        "NFCORE_WORKER_GSM_HOST_NAMESPACE": "nfcore",
    }


class FakeDatabase:
    def __init__(self, bindings: list[SecretBinding]):
        self.bindings = bindings
        self.destinations: dict[tuple[str, str], list[SimpleNamespace]] = {}
        self.valid_units: set[tuple[str, str]] = set()
        self.read_count = 0

    @contextmanager
    def __call__(self):
        self.read_count += 1
        registry = SimpleNamespace(
            list_active_signatures=lambda **_: tuple(
                x for x in self.bindings if x.state == "active"
            ),
            get=lambda reference: next(
                (x for x in self.bindings if x.reference_id == reference), None
            ),
        )
        control = SimpleNamespace(
            get_unit=lambda tenant, unit: (
                SimpleNamespace(enabled_environments=frozenset({FiscalEnvironment.HOMOLOGATION}))
                if (tenant, unit) in self.valid_units
                else None
            )
        )
        commercial = SimpleNamespace(
            list_webhook_destinations=lambda *, tenant_id, unit_id, environment: tuple(
                self.destinations.get((tenant_id, unit_id), [])
            ),
            webhook_approval=lambda scope, destination: {
                "enabled": True,
                "approval_status": "approved",
            },
        )
        outbox = SimpleNamespace(
            counts_by_status=lambda: {status: 0 for status in FiscalOutboxStatus}
        )
        yield SimpleNamespace(
            secret_bindings=registry,
            control_plane=control,
            commercial=commercial,
            outbox=outbox,
        )

    def allow(self, tenant: str, unit: str) -> None:
        self.valid_units.add((tenant, unit))
        self.destinations[(tenant, unit)] = [
            SimpleNamespace(destination_id=f"target-{tenant}-{unit}", enabled=True)
        ]


def test_registration_discovers_multiple_tenants_and_revocation_without_env_change() -> None:
    db = FakeDatabase([binding("academy-a", "main"), binding("academy-b", "north")])
    db.allow("academy-a", "main")
    db.allow("academy-b", "north")
    before = production_worker_bindings(db, project="fm-core-live", now=NOW)
    assert [(b.tenant_id, b.unit_id) for b, _ in before] == [
        ("academy-a", "main"),
        ("academy-b", "north"),
    ]
    db.bindings[0] = binding("academy-a", "main", state="revoked")
    after = production_worker_bindings(db, project="fm-core-live", now=NOW)
    assert [(b.tenant_id, b.unit_id) for b, _ in after] == [("academy-b", "north")]
    assert "NFCORE_WORKER_GSM_TENANT_ID" not in env()
    assert "NFCORE_WORKER_GSM_UNIT_ID" not in env()
    assert "NFCORE_WORKER_GSM_DESTINATION_ID" not in env()


def test_ambiguous_signatures_or_destinations_are_denied_by_scope() -> None:
    db = FakeDatabase(
        [
            binding("academy-a", "main", ref="sec_nfcore_academy_a_main_key_1"),
            binding("academy-a", "main", ref="sec_nfcore_academy_a_main_key_2"),
            binding("academy-b", "north"),
        ]
    )
    db.allow("academy-a", "main")
    db.allow("academy-b", "north")
    assert len(production_worker_bindings(db, project="fm-core-live", now=NOW)) == 1
    db.bindings = [binding("academy-a", "main"), binding("academy-b", "north")]
    db.destinations[("academy-a", "main")].append(
        SimpleNamespace(destination_id="other-destination", enabled=True)
    )
    assert len(production_worker_bindings(db, project="fm-core-live", now=NOW)) == 1


def test_bogus_cross_project_binding_never_becomes_claim_authority() -> None:
    db = FakeDatabase([binding("academy-a", "main"), binding("academy-b", "north")])
    db.allow("academy-a", "main")
    db.allow("academy-b", "north")
    outsider = binding("academy-a", "main", ref="sec_nfcore_outside_project")
    from dataclasses import replace

    db.bindings[0] = replace(outsider, resource="projects/other-project/secrets/outside")
    assert [
        (b.tenant_id, b.unit_id)
        for b, _ in production_worker_bindings(db, project="fm-core-live", now=NOW)
    ] == [("academy-b", "north")]


def test_worker_factory_denies_staging_and_weak_project_identity() -> None:
    current = env()
    assert platform_project(current) == ("fm-core-live", "123456789012")
    current["NFCORE_GSM_ALLOWED_PROJECTS"] = "other-cloud"
    with pytest.raises(RuntimeConfigurationError):
        production_multi_worker_handler_factory(current)
    current = env()
    current["NFCORE_ENVIRONMENT"] = "staging"
    with pytest.raises(RuntimeConfigurationError):
        production_multi_worker_handler_factory(current)
    current = env()
    build = production_multi_worker_handler_factory(current)
    with pytest.raises(RuntimeConfigurationError):
        build(
            FakeDatabase([]),
            SimpleNamespace(
                environment=RuntimeEnvironment.STAGING,
                secret_backend="external",
            ),
        )


def test_worker_continuous_bootstrap_requires_real_platform_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = env()
    factory = production_multi_worker_handler_factory(source)
    with pytest.raises(RuntimeConfigurationError, match="workload identity unavailable"):
        factory(
            FakeDatabase([]),
            SimpleNamespace(environment=RuntimeEnvironment.PRODUCTION, secret_backend="external"),
        )


def test_single_worker_process_accepts_new_tenant_without_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeDatabase([binding("academy-a", "main")])
    db.allow("academy-a", "main")
    stop = Event()
    calls: list[str] = []
    loops = 0

    def loader(database, *, project, now):
        nonlocal loops
        loops += 1
        if loops == 2:
            db.bindings.append(binding("academy-b", "north"))
            db.allow("academy-b", "north")
        if loops > 2:
            stop.set()
        return production_worker_bindings(db, project=project, now=now)

    def scoped(*args, binding, destination_id, namespace):
        calls.append(binding.tenant_id)
        return SimpleNamespace(
            runtime=SimpleNamespace(
                run_cycle=lambda: SimpleNamespace(
                    claimed=0,
                    succeeded=0,
                    retry_wait=0,
                    dead_letter=0,
                )
            )
        )

    worker = MultiTenantGsmWorkerComposition(
        db, env(), "nfcore", loader=loader, scoped_factory=scoped
    )
    worker.run_forever(stop)
    assert calls == ["academy-a", "academy-a", "academy-b"]
    assert loops == 3


def test_iam_failure_isolated_from_other_tenant_but_worker_not_ready() -> None:
    db = FakeDatabase([binding("academy-a", "main"), binding("academy-b", "north")])
    db.allow("academy-a", "main")
    db.allow("academy-b", "north")
    stop = Event()
    completed: list[str] = []
    calls = 0

    def loader(database, *, project, now):
        nonlocal calls
        calls += 1
        if calls == 2:
            stop.set()
        return production_worker_bindings(db, project=project, now=now)

    def scoped(*args, binding, destination_id, namespace):
        if binding.tenant_id == "academy-a":
            raise PermissionError("IAM denied")
        completed.append(binding.tenant_id)
        return SimpleNamespace(
            runtime=SimpleNamespace(
                run_cycle=lambda: SimpleNamespace(
                    claimed=0,
                    succeeded=0,
                    retry_wait=0,
                    dead_letter=0,
                )
            )
        )

    worker = MultiTenantGsmWorkerComposition(
        db, env(), "nfcore", loader=loader, scoped_factory=scoped
    )
    worker.run_forever(stop)
    assert completed == ["academy-b"]
    assert worker.health().ready is False


def test_revoked_binding_denied_before_provider_access() -> None:
    revoked = binding("academy-a", "main", state="revoked")
    db = FakeDatabase([revoked])
    access = Mock()
    reader = DurableGsmReader(
        uow_factory=db,
        access=access,
        environment="production",
        workload_id="nfcore-worker",
        allowed_resources=frozenset({revoked.resource}),
    )
    with pytest.raises(SecretResolutionError):
        reader.read(
            reference_id=revoked.reference_id,
            scope=SecretScope("academy-a", "main", "webhook-signing"),
            kind="signature",
            provider_id=revoked.provider_id,
            fiscal_environment=None,
            version=1,
        )
    access.access.assert_not_called()
