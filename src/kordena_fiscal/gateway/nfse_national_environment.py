"""Single authority mapping a fiscal environment to NFS-e Nacional parameters.

Homologation (produção restrita) keeps its fixed, pinned endpoint. Production
is deliberately *configuration-gated*: it needs an explicit kill switch, an
exact official host, and (enforced by the transport) an injected human
production grant. Nothing here performs I/O or reads secrets.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from kordena_fiscal.domain import FiscalEnvironment, FiscalValidationError

SEFIN_HOMOLOGATION_NFSE_URL = (
    "https://sefin.producaorestrita.nfse.gov.br/API/SefinNacional/nfse"
)
# Official production host published by the national portal (SEFIN Nacional).
SEFIN_PRODUCTION_HOST = "sefin.nfse.gov.br"
ENV_PRODUCTION_ENABLED = "NFCORE_NFSE_PRODUCTION_ENABLED"
ENV_PRODUCTION_URL = "NFCORE_NFSE_SEFIN_PRODUCTION_URL"


@dataclass(frozen=True, slots=True)
class NationalEnvironmentProfile:
    environment: FiscalEnvironment
    tp_amb: int
    nfse_url: str
    provider_label: str

    @property
    def tp_amb_text(self) -> str:
        return str(self.tp_amb)

    @property
    def base_url(self) -> str:
        return self.nfse_url.rsplit("/nfse", 1)[0]


def validate_production_nfse_url(url: object) -> str:
    """Accept only the exact official HTTPS production host and a /nfse path."""
    if not isinstance(url, str) or not url or url != url.strip() or len(url) > 256:
        raise FiscalValidationError("NFS-e production URL is not configured")
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname != SEFIN_PRODUCTION_HOST
        or parts.port not in (None, 443)
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or not parts.path.endswith("/nfse")
        or ".." in parts.path
        or "//" in parts.path
    ):
        raise FiscalValidationError("NFS-e production URL must be the official SEFIN host")
    return url


def resolve_national_environment(
    environment: FiscalEnvironment, *, env: Mapping[str, str] | None = None,
) -> NationalEnvironmentProfile:
    source = os.environ if env is None else env
    if environment is FiscalEnvironment.HOMOLOGATION:
        return NationalEnvironmentProfile(
            environment, 2, SEFIN_HOMOLOGATION_NFSE_URL, "nfse-nacional-producao-restrita",
        )
    if environment is FiscalEnvironment.PRODUCTION:
        if source.get(ENV_PRODUCTION_ENABLED, "").strip().lower() != "true":
            raise FiscalValidationError("NFS-e production emission is not enabled on this host")
        url = validate_production_nfse_url(source.get(ENV_PRODUCTION_URL))
        return NationalEnvironmentProfile(environment, 1, url, "nfse-nacional-producao")
    raise FiscalValidationError("Unsupported national fiscal environment")


ENV_PRODUCTION_GRANTS_FILE = "NFCORE_NFSE_PRODUCTION_GRANTS_FILE"
_MAX_GRANTS_BYTES = 64 * 1024


def load_nfse_production_authority(env: Mapping[str, str] | None = None):  # type: ignore[no-untyped-def]
    """Load the host-owned human production grants; absent file means no grant.

    The file is operator-managed on the server (outside the repository and the
    container image). Each entry is one exact human-approved production cell:
    tenant_id, unit_id, uf, municipality_ibge_code, approved_by,
    approval_reference, external_evidence_id, approved_at (ISO-8601 with TZ).
    A configured-but-malformed file fails closed (raises) instead of silently
    granting or silently ignoring entries.
    """
    import json
    from datetime import datetime
    from pathlib import Path

    from kordena_fiscal.domain import BrazilianJurisdiction, FiscalDocumentKind
    from kordena_fiscal.gateway.production_activation import (
        ProductionActivationKey,
        ProductionActivationRecord,
        ProductionActivationState,
        ProductionExecutionAuthority,
    )
    from kordena_fiscal.gateway.provider import ProviderOperation

    source = os.environ if env is None else env
    raw_path = source.get(ENV_PRODUCTION_GRANTS_FILE, "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    try:
        if not path.is_file() or path.stat().st_size > _MAX_GRANTS_BYTES:
            raise ValueError
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload["grants"]
        if not isinstance(entries, list):
            raise ValueError
        records = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError
            key = ProductionActivationKey(
                tenant_id=entry["tenant_id"], unit_id=entry["unit_id"],
                provider_id="nfse-nacional-producao-restrita",
                document_kind=FiscalDocumentKind.NFSE,
                jurisdiction=BrazilianJurisdiction(entry["uf"], entry["municipality_ibge_code"]),
                operation=ProviderOperation.AUTHORIZE,
            )
            records.append(ProductionActivationRecord(
                key=key, state=ProductionActivationState.ACTIVE,
                approval_reference=entry["approval_reference"],
                external_evidence_id=entry["external_evidence_id"],
                changed_by=entry["approved_by"],
                changed_at=datetime.fromisoformat(entry["approved_at"]),
                correlation_id="host-grant-file",
            ))
    except (OSError, ValueError, KeyError, TypeError, FiscalValidationError):
        raise FiscalValidationError("NFS-e production grants file is invalid") from None
    return ProductionExecutionAuthority(tuple(records))
