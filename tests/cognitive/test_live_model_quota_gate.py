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
            "NFCORE_ENVIRONMENT": environment,
            "NFCORE_COGNITIVE_AI_PRIMARY_MODEL": "configured-but-not-enabled",
        },
    )
    assert router is not None
    app = FastAPI()
    app.include_router(router)
    paths = set(app.openapi()["paths"])
    assert "/v1/portal/cognitive/advise" in paths
    assert "/v1/command/cognitive/metrics" in paths
