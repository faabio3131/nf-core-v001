"""Model calls never bypass durable commercial token reservations."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from kordena_fiscal.cognitive.contracts import (
    Capability,
    ModelUsage,
)
from kordena_fiscal.cognitive.ports import (
    ModelPrompt,
    ModelProviderDenied,
    ModelProviderUnavailable,
    ProviderAnswer,
)
from kordena_fiscal.cognitive.quota_model import QuotaGovernedAdvisoryClient


def prompt(request_id: str = "req-1") -> ModelPrompt:
    return ModelPrompt(
        capability=Capability.EXPLAIN_REJECTION,
        system="System advisory instructions",
        trusted_facts="No secrets",
        untrusted_data="Fiscal evidence",
        boundary="untrusted",
        context_hash="abc123",
        tenant_id="tenant-a",
        unit_id="unit-a",
        request_id=request_id,
        correlation_id="corr-1",
    )


@dataclass
class Claim:
    created: bool


class FakeQuota:
    def __init__(self) -> None:
        self.requests: set[str] = set()
        self.reservations: list[tuple[str, str, int, int]] = []
        self.settlements: list[tuple[str, str, int, int]] = []
        self.fail = False

    def reserve(
        self, *, tenant_id: str, request_id: str,
        max_input_tokens: int, max_output_tokens: int,
    ) -> Claim:
        if self.fail:
            raise ConnectionError("SQL unavailable")
        self.reservations.append(
            (tenant_id, request_id, max_input_tokens, max_output_tokens)
        )
        if request_id in self.requests:
            return Claim(False)
        self.requests.add(request_id)
        return Claim(True)

    def settle(
        self, *, tenant_id: str, request_id: str,
        input_tokens: int, output_tokens: int,
    ) -> bool:
        self.settlements.append((tenant_id, request_id, input_tokens, output_tokens))
        return True


class FakeModel:
    def __init__(self, fail: bool = False, unknown_usage: bool = False) -> None:
        self.calls = 0
        self.fail = fail
        self.unknown_usage = unknown_usage

    def advise(self, prompt: ModelPrompt, *, deadline_seconds: float) -> ProviderAnswer:
        self.calls += 1
        if self.fail:
            raise ModelProviderUnavailable("failed after provider call")
        return ProviderAnswer(
            sections=(), provider_id="fake", model="test", model_version="v1",
            usage=ModelUsage() if self.unknown_usage else ModelUsage(
                input_tokens=120, output_tokens=30
            ),
        )


def test_model_reserves_before_call_and_settles_verified_usage() -> None:
    quota = FakeQuota()
    model = FakeModel()
    advisor = QuotaGovernedAdvisoryClient(model, quota)  # type: ignore[arg-type]
    result = advisor.advise(prompt(), deadline_seconds=5.0)
    assert result.usage.input_tokens == 120
    assert model.calls == 1
    assert quota.reservations[0][:2] == ("tenant-a", "req-1")
    assert quota.reservations[0][2] >= 120
    assert quota.reservations[0][3] == 700
    assert quota.settlements == [("tenant-a", "req-1", 120, 30)]
    with pytest.raises(ModelProviderDenied, match="duplicate"):
        advisor.advise(prompt(), deadline_seconds=5.0)
    assert model.calls == 1


def test_unavailable_sql_blocks_model_without_fallback_to_in_memory() -> None:
    quota = FakeQuota()
    quota.fail = True
    model = FakeModel()
    advisor = QuotaGovernedAdvisoryClient(model, quota)  # type: ignore[arg-type]
    with pytest.raises(ModelProviderDenied, match="unavailable"):
        advisor.advise(prompt(), deadline_seconds=5.0)
    assert model.calls == 0


def test_uncertain_model_failure_keeps_reservation() -> None:
    quota = FakeQuota()
    model = FakeModel(fail=True)
    advisor = QuotaGovernedAdvisoryClient(model, quota)  # type: ignore[arg-type]
    with pytest.raises(ModelProviderUnavailable):
        advisor.advise(prompt(), deadline_seconds=5.0)
    assert quota.reservations and not quota.settlements
    with pytest.raises(ModelProviderDenied, match="duplicate"):
        advisor.advise(prompt(), deadline_seconds=5.0)
    assert model.calls == 1


def test_missing_provider_usage_keeps_conservative_reservation() -> None:
    quota = FakeQuota()
    model = FakeModel(unknown_usage=True)
    advisor = QuotaGovernedAdvisoryClient(model, quota)  # type: ignore[arg-type]
    advisor.advise(prompt(), deadline_seconds=5.0)
    assert quota.reservations and not quota.settlements
