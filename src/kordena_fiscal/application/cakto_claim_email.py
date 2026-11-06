"""Secure, provider-neutral email delivery for the automatic Cakto claim link.

Reuses the existing ``ActivationMessageTransport`` port (one outbound email
capability for the whole product, selected at the runtime boundary) with
claim-specific content. This module never selects a concrete email provider
and never persists, logs or re-derives the raw claim token outside this one
send.
"""

from __future__ import annotations

from html import escape
from urllib.parse import quote, urlparse

from kordena_fiscal.application.activation_delivery import (
    ActivationEmailMessage,
    ActivationMessageTransport,
)
from kordena_fiscal.application.cakto_claim_automation import CaktoClaimDeliveryError
from kordena_fiscal.application.commercial_claim import IssuedCommercialClaim


class SecureCaktoClaimEmailDelivery:
    """Deliver the one-time post-payment claim link without becoming identity authority."""

    def __init__(
        self,
        *,
        transport: ActivationMessageTransport,
        claim_base_url: str,
        sender_email: str,
        product_name: str = "FM NFCORE",
    ) -> None:
        self._transport = transport
        self._claim_base_url = self._validate_base_url(claim_base_url)
        self._sender_email = self._validate_email(sender_email, "sender_email")
        normalized_product = product_name.strip()
        if not normalized_product or len(normalized_product) > 80:
            raise ValueError("product_name must be non-blank and <= 80 chars")
        self._product_name = normalized_product

    def deliver(self, *, email: str, claim: IssuedCommercialClaim) -> None:
        recipient = self._validate_email(email, "email")
        if not isinstance(claim, IssuedCommercialClaim):
            raise CaktoClaimDeliveryError("commercial claim is invalid")

        # The fragment is deliberately used instead of a query parameter so the raw
        # token is not sent to the web server in the initial GET request/access log.
        claim_url = f"{self._claim_base_url}#claim={quote(claim.claim_token, safe='')}"
        safe_product = escape(self._product_name)
        safe_claim_url = escape(claim_url, quote=True)
        message = ActivationEmailMessage(
            to_email=recipient,
            from_email=self._sender_email,
            subject=f"Confirme sua compra no {self._product_name}",
            text_body=(
                f"Seu pagamento no {self._product_name} foi confirmado.\n\n"
                "Para liberar o acesso, abra o link abaixo e confirme seus dados.\n\n"
                f"{claim_url}\n\n"
                "Por seguranca, o link e valido por um periodo limitado e so pode "
                "ser usado uma vez.\n\n"
                "Se voce nao reconhece esta compra, ignore esta mensagem."
            ),
            html_body=(
                '<!doctype html><html lang="pt-BR"><body '
                'style="margin:0;padding:0;background:#07111f;font-family:Arial,sans-serif;'
                'color:#eaf4ff;">'
                '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
                'style="background:#07111f;padding:20px 12px;"><tr><td align="center">'
                '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
                'style="max-width:520px;background:#0b1b30;border:1px solid #173a63;'
                'border-radius:18px;padding:32px;">'
                f'<tr><td style="font-size:13px;letter-spacing:1.4px;color:#88a8c8;'
                f'font-weight:700;">{safe_product} · PAGAMENTO CONFIRMADO</td></tr>'
                '<tr><td style="padding-top:12px;font-size:24px;line-height:1.25;'
                'font-weight:700;color:#ffffff;">Confirme seu acesso</td></tr>'
                '<tr><td style="padding-top:14px;font-size:15px;line-height:1.55;'
                'color:#c7d8ea;">Recebemos a confirmacao do seu pagamento. '
                'Use o botao abaixo para confirmar seus dados e liberar o acesso.</td></tr>'
                '<tr><td align="center" style="padding:22px 0;">'
                f'<a href="{safe_claim_url}" '
                'style="display:inline-block;background:#2f6dff;color:#ffffff;'
                'text-decoration:none;font-weight:700;font-size:15px;'
                'padding:13px 22px;border-radius:9px;">Confirmar meus dados</a>'
                '</td></tr>'
                '<tr><td style="font-size:13px;line-height:1.55;color:#9fb6cc;">'
                'Por seguranca, este link e valido por um periodo limitado e so pode '
                'ser usado uma vez.</td></tr>'
                '<tr><td style="padding-top:12px;font-size:13px;line-height:1.6;'
                'color:#7f9bb7;">Se voce nao reconhece esta compra, ignore esta '
                'mensagem.</td></tr>'
                '</table></td></tr></table></body></html>'
            ),
        )
        try:
            self._transport.send(message)
        except Exception:
            # Provider details can contain endpoint/header/credential information.
            raise CaktoClaimDeliveryError("claim delivery failed") from None

    @staticmethod
    def _validate_base_url(value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "claim_base_url must be an absolute HTTPS URL without credentials, "
                "query or fragment"
            )
        return normalized

    @staticmethod
    def _validate_email(value: str, field_name: str) -> str:
        normalized = value.strip().casefold()
        if (
            not normalized
            or len(normalized) > 320
            or normalized.count("@") != 1
            or normalized.startswith("@")
            or normalized.endswith("@")
            or "\r" in normalized
            or "\n" in normalized
        ):
            raise ValueError(f"{field_name} is invalid")
        return normalized


__all__ = ["SecureCaktoClaimEmailDelivery"]
