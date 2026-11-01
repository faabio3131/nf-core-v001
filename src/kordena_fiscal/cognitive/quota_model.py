"""Quota-first model transport: never call a provider without a durable reservation."""

from __future__ import annotations

from collections.abc import Sequence

from .adapters.openai_compatible import FallbackAdvisoryClient
from .durable_usage import DurableTokenQuotaStore, QuotaDenied
from .ports import (
    AdvisoryModelPort,
    ModelPrompt,
    ModelProviderDenied,
    ProviderAnswer,
)

# The OpenAI-compatible adapters currently configure max_output_tokens=700.
# Reserve both slots on a fallback chain, even if just one ultimately succeeds.
_MAX_OUTPUT_TOKENS_PER_ATTEMPT = 700
_MAX_RESERVATION_INPUT = 120_000


class QuotaGovernedAdvisoryClient:
    """Wrap the *existing* advisory model, not a second model executor.

    Safety assumptions:
    - Input is bounded by UTF-8 bytes of sanitized prompt plus wire overhead.
    - Duplicate request IDs cannot initiate two provider calls.
    - A timeout or uncertain provider charge retains full reserved capacity.
    - Fallback may charge on both attempts, so do not refund its estimate.
    - Only one-provider calls with positive, bounded usage may be settled.
    """

    def __init__(self, delegate: AdvisoryModelPort, quotas: DurableTokenQuotaStore) -> None:
        self._delegate = delegate
        self._quotas = quotas

    @staticmethod
    def _maximum_input(prompt: ModelPrompt, attempts: int) -> int:
        fields: Sequence[str] = (
            prompt.system,
            prompt.trusted_facts,
            prompt.untrusted_data,
            prompt.boundary,
            prompt.context_hash,
            prompt.capability.value,
        )
        maximum = attempts * (sum(len(text.encode("utf-8")) for text in fields) + 4096)
        if maximum < 1 or maximum > _MAX_RESERVATION_INPUT:
            raise ModelProviderDenied("model context exceeds governed token budget")
        return maximum

    def advise(self, prompt: ModelPrompt, *, deadline_seconds: float) -> ProviderAnswer:
        # Current fallback adapter has at most two configured providers.
        attempts = 2 if isinstance(self._delegate, FallbackAdvisoryClient) else 1
        maximum_input = self._maximum_input(prompt, attempts)
        maximum_output = attempts * _MAX_OUTPUT_TOKENS_PER_ATTEMPT
        try:
            reservation = self._quotas.reserve(
                tenant_id=prompt.tenant_id,
                request_id=prompt.request_id,
                max_input_tokens=maximum_input,
                max_output_tokens=maximum_output,
            )
        except QuotaDenied as exc:
            raise ModelProviderDenied("cognitive quota or subscription denied") from exc
        except Exception as exc:
            raise ModelProviderDenied("durable cognitive quota unavailable") from exc
        if not reservation.created:
            # Never repeat a paid model call on HTTP retry, including after a timeout.
            raise ModelProviderDenied("duplicate cognitive request not re-executed")
        answer = self._delegate.advise(prompt, deadline_seconds=deadline_seconds)
        if attempts == 1 and answer.usage.input_tokens > 0 and answer.usage.output_tokens > 0:
            try:
                self._quotas.settle(
                    tenant_id=prompt.tenant_id,
                    request_id=prompt.request_id,
                    input_tokens=answer.usage.input_tokens,
                    output_tokens=answer.usage.output_tokens,
                )
            except Exception:
                # The conservative reservation remains counted. Never fail open,
                # return extra allowance or silently retry a potentially billed call.
                pass
        return answer
