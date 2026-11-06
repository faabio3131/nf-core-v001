"""External Cakto claim-email composition for FM NFCORE.

Reuses the same outbound transport selection as activation email
(``runtime/activation_email.py``) -- one provider configuration, one
credential -- with claim-specific message content and base URL. The Core
never selects a concrete provider; this module only builds the governed
adapter when it is explicitly configured.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from kordena_fiscal.application.cakto_claim_email import SecureCaktoClaimEmailDelivery

from .activation_email import BrevoActivationMessageTransport
from .config import RuntimeConfigurationError


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise RuntimeConfigurationError(f"{name} is required")
    return value


def build_cakto_claim_delivery_from_mapping(
    values: Mapping[str, str],
) -> SecureCaktoClaimEmailDelivery | None:
    """Build the automatic Cakto claim-email delivery only when explicitly configured.

    Deliberately reuses the activation email provider/credential envs (one
    outbound transport, several message templates) and only adds the claim
    redemption base URL as Cakto-specific configuration.
    """

    provider = values.get("NFCORE_ACTIVATION_EMAIL_PROVIDER", "").strip().lower()
    claim_base_url = values.get("NFCORE_CAKTO_CLAIM_BASE_URL", "").strip()
    if not provider and not claim_base_url:
        return None
    if not provider or not claim_base_url:
        raise RuntimeConfigurationError(
            "Cakto claim email requires both NFCORE_ACTIVATION_EMAIL_PROVIDER and "
            "NFCORE_CAKTO_CLAIM_BASE_URL"
        )
    if provider != "brevo":
        raise RuntimeConfigurationError("unsupported activation email provider")

    api_key = _required(values, "NFCORE_ACTIVATION_EMAIL_API_KEY")
    sender = _required(values, "NFCORE_ACTIVATION_EMAIL_SENDER")
    timeout_raw = values.get("NFCORE_ACTIVATION_EMAIL_TIMEOUT_SECONDS", "10").strip()
    try:
        timeout = float(timeout_raw)
    except ValueError:
        raise RuntimeConfigurationError(
            "NFCORE_ACTIVATION_EMAIL_TIMEOUT_SECONDS must be numeric"
        ) from None

    transport = BrevoActivationMessageTransport(api_key=api_key, timeout_seconds=timeout)
    return SecureCaktoClaimEmailDelivery(
        transport=transport,
        claim_base_url=claim_base_url,
        sender_email=sender,
    )


def build_cakto_claim_delivery_from_environ() -> SecureCaktoClaimEmailDelivery | None:
    return build_cakto_claim_delivery_from_mapping(os.environ)


__all__ = [
    "build_cakto_claim_delivery_from_environ",
    "build_cakto_claim_delivery_from_mapping",
]
