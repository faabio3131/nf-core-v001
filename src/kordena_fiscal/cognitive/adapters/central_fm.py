"""Server-to-server adapter for the FM central cognitive backend (contract v1, PROPOSED).

Security posture:
- no AI provider key, bearer token or password ever passes through this code: requests are
  authenticated with an HMAC signature whose key is resolved from the Vault by reference;
- HTTPS only (loopback HTTP is allowed solely when explicitly enabled for local tests);
- redirects are refused, response size is capped, and the response is validated strictly;
- every failure maps to a typed ``ModelProviderError`` and degrades to the deterministic
  baseline in the service.

The contract is a proposal for the Command maintainers (see
``docs/NFCORE_COGNITIVE_S2S_CONTRACT_V1.md``); nothing here assumes an existing endpoint.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit

from kordena_fiscal.security.s2s import WebhookSecurity, WebhookSignatureError

from ..contracts import ModelUsage, SectionKind
from ..ports import (
    ModelPrompt,
    ModelProviderDenied,
    ModelProviderError,
    ModelProviderMalformed,
    ModelProviderRateLimited,
    ModelProviderUnavailable,
    ProviderAnswer,
    ProviderSection,
)
from ..redaction import Redactor

CONTRACT_VERSION = "nfcore.cognitive.s2s/v1"
PRODUCT_ID = "nfcore"
MAX_RESPONSE_BYTES = 64 * 1024
MAX_SECTIONS = 12
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes


class HttpTransport(Protocol):
    def post(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> HttpResponse:
        """Raise ``TimeoutError``/``ConnectionError`` on transport failure."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


class UrllibTransport:
    """Stdlib transport. No redirects, bounded read, explicit timeout."""

    def post(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> HttpResponse:
        request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=timeout_seconds) as response:  # noqa: S310
                return HttpResponse(response.status, response.read(MAX_RESPONSE_BYTES + 1))
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, exc.read(MAX_RESPONSE_BYTES + 1))
        except TimeoutError as exc:
            raise TimeoutError(str(exc)) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ConnectionError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class CentralFMConfig:
    endpoint_url: str
    allow_insecure_loopback: bool = False

    def __post_init__(self) -> None:
        parts = urlsplit(self.endpoint_url)
        host = (parts.hostname or "").lower()
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("endpoint must not embed credentials, query or fragment")
        if parts.scheme == "https" and host:
            return
        if parts.scheme == "http" and self.allow_insecure_loopback and host in _LOOPBACK:
            return
        raise ValueError("endpoint must be https (loopback http only when explicitly allowed)")


class CentralFMAdvisoryClient:
    """Implements ``AdvisoryModelPort`` against the central FM backend."""

    def __init__(
        self,
        *,
        config: CentralFMConfig,
        signer: WebhookSecurity,
        transport: HttpTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        redactor: Redactor | None = None,
    ) -> None:
        self._config = config
        self._signer = signer
        self._transport = transport or UrllibTransport()
        self._clock = clock
        self._redactor = redactor or Redactor()

    def advise(self, prompt: ModelPrompt, *, deadline_seconds: float) -> ProviderAnswer:
        body = self._encode(prompt)
        try:
            signature = self._signer.sign(body, now=self._clock())
        except WebhookSignatureError as exc:
            raise ModelProviderDenied("signing key unavailable") from exc
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-FM-Contract-Version": CONTRACT_VERSION,
            "X-FM-Product": PRODUCT_ID,
            "X-FM-Correlation-Id": prompt.correlation_id,
            "X-FM-Signature": signature.header_value,
            "Idempotency-Key": prompt.request_id,
        }
        try:
            response = self._transport.post(
                self._config.endpoint_url, headers, body, deadline_seconds
            )
        except TimeoutError as exc:
            raise ModelProviderUnavailable("central backend timed out") from exc
        except ConnectionError as exc:
            raise ModelProviderUnavailable("central backend unreachable") from exc
        return self._decode(response, prompt)

    # ------------------------------------------------------------------ wire

    def _encode(self, prompt: ModelPrompt) -> bytes:
        def clean(text: str) -> str:
            return self._redactor.redact(text).text

        payload = {
            "contractVersion": CONTRACT_VERSION,
            "productId": PRODUCT_ID,
            "tenantId": prompt.tenant_id,
            "unitId": prompt.unit_id,
            "requestId": prompt.request_id,
            "correlationId": prompt.correlation_id,
            "capability": prompt.capability.value,
            "contextHash": prompt.context_hash,
            "system": prompt.system,
            "trustedFacts": clean(prompt.trusted_facts),
            "untrustedData": clean(prompt.untrusted_data),
            "boundary": prompt.boundary,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def _decode(self, response: HttpResponse, prompt: ModelPrompt) -> ProviderAnswer:
        status = response.status
        if status in (401, 403):
            raise ModelProviderDenied(f"central backend denied the request ({status})")
        if status == 429:
            raise ModelProviderRateLimited("central backend rate limited the request")
        if status >= 500:
            raise ModelProviderUnavailable(f"central backend error ({status})")
        if status != 200:
            raise ModelProviderMalformed(f"unexpected status {status}")
        if len(response.body) > MAX_RESPONSE_BYTES:
            raise ModelProviderMalformed("response too large")
        try:
            data = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelProviderMalformed("response is not valid JSON") from exc
        try:
            return self._parse(data, prompt)
        except ModelProviderError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ModelProviderMalformed("response does not match the contract") from exc

    @staticmethod
    def _parse(data: object, prompt: ModelPrompt) -> ProviderAnswer:
        if not isinstance(data, dict):
            raise ModelProviderMalformed("response must be an object")
        if data.get("contractVersion") != CONTRACT_VERSION:
            raise ModelProviderMalformed("contract version mismatch")
        if data.get("requestId") != prompt.request_id:
            raise ModelProviderMalformed("response belongs to another request")
        raw_sections = data["sections"]
        if not isinstance(raw_sections, list) or len(raw_sections) > MAX_SECTIONS:
            raise ModelProviderMalformed("invalid sections")
        sections: list[ProviderSection] = []
        for item in raw_sections:
            if not isinstance(item, dict):
                raise ModelProviderMalformed("invalid section")
            ids = item.get("evidenceIds", [])
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                raise ModelProviderMalformed("invalid evidence ids")
            text = item["text"]
            if not isinstance(text, str):
                raise ModelProviderMalformed("invalid section text")
            sections.append(
                ProviderSection(SectionKind(item["kind"]), text, tuple(ids))
            )
        usage_raw = data.get("usage") or {}
        usage = ModelUsage(
            input_tokens=int(usage_raw.get("inputTokens", 0)),
            output_tokens=int(usage_raw.get("outputTokens", 0)),
            cost_micro_brl=(
                int(usage_raw["costMicroBrl"]) if "costMicroBrl" in usage_raw else None
            ),
        )
        return ProviderAnswer(
            sections=tuple(sections),
            provider_id=str(data["provider"])[:64],
            model=str(data["model"])[:128],
            model_version=str(data["modelVersion"])[:64],
            usage=usage,
        )
