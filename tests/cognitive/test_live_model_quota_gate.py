"""Safety regression: no production/staging model on process-local pilot quotas."""

import pytest
from fastapi import FastAPI

from kordena_fiscal.cognitive import composition
from kordena_fiscal.security.human_identity import HumanIdentityService


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_live_model_is_not_initialized_without_durable_quota(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    def forbidden_model(_: object) -> None:
        pytest.fail("model client must not initialize without durable cross-worker quotas")

    monkeypatch.setattr(composition, "build_model_from_environ", forbidden_model)

    class Reader:
        def surface(self, **kwargs: object) -> tuple[()]:
            return ()

    identity = object.__new__(HumanIdentityService)
    router = composition.build_cognitive_router(
        identity,
        Reader(),  # type: ignore[arg-type]
        {
            "NFCORE_COGNITIVE_ENABLED": "true",
            # Conflicting environment setting must not override the runtime authority.
            "NFCORE_ENVIRONMENT": "development",
            "NFCORE_COGNITIVE_AI_PRIMARY_MODEL": "configured-but-not-enabled",
        },
        runtime_environment=environment,
    )
    assert router is not None
    app = FastAPI()
    app.include_router(router)
    paths = set(app.openapi()["paths"])
    assert "/v1/portal/cognitive/advise" in paths
    assert "/v1/command/cognitive/metrics" in paths


def test_model_client_initialization_only_in_explicit_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    def model_builder(environ: object) -> None:
        called.append("configured")
        return None

    monkeypatch.setattr(composition, "build_model_from_environ", model_builder)

    class Reader:
        def surface(self, **kwargs: object) -> tuple[()]:
            return ()

    router = composition.build_cognitive_router(
        object.__new__(HumanIdentityService),
        Reader(),  # type: ignore[arg-type]
        {"NFCORE_COGNITIVE_ENABLED": "true"},
        runtime_environment="development",
    )
    assert router is not None
    assert called == ["configured"]


@pytest.mark.parametrize(
    ("flag", "has_quota", "has_audit", "expect_model"),
    [
        ("", True, True, False),
        ("true", False, True, False),
        ("true", True, False, False),
        ("true", True, True, True),
    ],
)
def test_production_model_requires_all_independent_gates(
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
    has_quota: bool,
    has_audit: bool,
    expect_model: bool,
) -> None:
    called: list[str] = []

    class Model:
        def advise(self, *args: object, **kwargs: object) -> None:
            return None

    def model_builder(environ: object) -> Model:
        called.append("provider")
        return Model()

    def wrapped_model(model: object, quota: object) -> object:
        called.append("durable-wrapper")
        return model

    monkeypatch.setattr(composition, "build_model_from_environ", model_builder)
    monkeypatch.setattr(composition, "QuotaGovernedAdvisoryClient", wrapped_model)

    class Reader:
        def surface(self, **kwargs: object) -> tuple[()]:
            return ()

    router = composition.build_cognitive_router(
        object.__new__(HumanIdentityService),
        Reader(),  # type: ignore[arg-type]
        {
            "NFCORE_COGNITIVE_ENABLED": "true",
            "NFCORE_COGNITIVE_DURABLE_AI_ENABLED": flag,
        },
        runtime_environment="production",
        quota_store=object() if has_quota else None,  # type: ignore[arg-type]
        audit_uow_factory=(lambda: None) if has_audit else None,  # type: ignore[arg-type]
    )
    assert router is not None
    assert called == (["provider", "durable-wrapper"] if expect_model else [])
