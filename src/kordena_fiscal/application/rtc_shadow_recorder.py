"""RTC-RFB-07: run the official-calculator shadow AFTER a preparation commits.

Opt-in: only when NFCORE_RTC_SIMPLES_URL and/or NFCORE_RTC_REGIME_REGULAR_URL
point to the internal calculators. The comparison never changes the prepared
document, never blocks issuance and never raises: any failure (calculator down,
archive unavailable) is swallowed after the fiscal transaction is durable. The
record is archived next to the document with SHADOW_MEDIA_TYPE.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from kordena_fiscal.archive import FiscalArchiveEntry, FiscalArchiveKind, RetentionPolicyMetadata
from kordena_fiscal.tax.rfb_regime_regular_calculator import RfbRegimeRegularCalculatorClient
from kordena_fiscal.tax.rfb_simples_calculator import RfbSimplesCalculatorClient
from kordena_fiscal.tax.rtc_shadow import SHADOW_MEDIA_TYPE, run_nfe_rtc_shadow

_RETENTION = RetentionPolicyMetadata("nfcore-rtc-official-shadow", 1)


def shadow_clients_from_env(
    environ: Mapping[str, str] | None = None,
) -> tuple[RfbSimplesCalculatorClient | None, RfbRegimeRegularCalculatorClient | None]:
    source = os.environ if environ is None else environ
    simples_url = source.get("NFCORE_RTC_SIMPLES_URL", "").strip()
    regular_url = source.get("NFCORE_RTC_REGIME_REGULAR_URL", "").strip()
    simples = RfbSimplesCalculatorClient(base_url=simples_url) if simples_url else None
    regular = (
        RfbRegimeRegularCalculatorClient(base_url=regular_url) if regular_url else None
    )
    return simples, regular


def record_rtc_shadow(
    factory: Any,
    document: Any,
    *,
    model: str,
    occurred_at: datetime,
    simples: RfbSimplesCalculatorClient | None,
    regime_regular: RfbRegimeRegularCalculatorClient | None,
) -> dict[str, object] | None:
    """Returns the archived record, or None when disabled or not archivable."""
    if simples is None and regime_regular is None:
        return None
    try:
        record = run_nfe_rtc_shadow(
            simples, document, model=model, occurred_at=occurred_at,
            regime_regular_client=regime_regular,
        )
        content = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        with factory() as uow:
            uow.archive.append(FiscalArchiveEntry.build(
                scope=document.scope, document_reference=document.document_id,
                kind=FiscalArchiveKind.OTHER, content=content, media_type=SHADOW_MEDIA_TYPE,
                archived_at=occurred_at, retention=_RETENTION,
            ))
            uow.commit()
        return record
    except Exception:  # shadow must never affect issuance  # noqa: BLE001
        return None
