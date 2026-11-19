"""RTC-RFB-04/07: shadow comparison of NF-e/NFC-e IBS/CBS with the official calculator.

Shadow only: this module NEVER changes a fiscal value, never blocks issuance and
never raises to its caller. It recomputes NFCore's own per-line RTC values with
the same pure function the XML builder uses, asks the pinned official Simples
calculator (internal service) for the same lines, and returns a JSON-safe
evidence record with every divergence. The caller may archive it.

Scope limits taken from the official contract: NF-e (55) / NFC-e (65) only,
CRT 1/2 (or 3 with tpRegimeIBSCBS=2); lines without an IBS/CBS classification
are skipped. NFCore has no cAtivSN (Simples activity code) yet, so the official
component may answer NAO_CALCULADO; that is recorded, not hidden.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from kordena_fiscal.tax.nfe_calculation import calculate_nfe_line
from kordena_fiscal.tax.rfb_simples_calculator import (
    RfbSimplesCalculatorClient,
    SimplesItem,
    build_request,
    compare_shadow,
)

SHADOW_MEDIA_TYPE = "application/vnd.nfcore.rtc-official-shadow.v1+json"


def _crt(document: Any) -> str:
    return str(int(document.issuer.tax_regime))


def nfe_rtc_lines(document: Any) -> list[dict[str, object]]:
    """NFCore's own per-line RTC values, exactly as the NF-e builder computes them."""
    issuer, recipient = document.issuer, document.recipient
    interstate_final_consumer = (
        recipient is not None
        and issuer.address.jurisdiction.state_code != recipient.address.jurisdiction.state_code
        and recipient.final_consumer
        and recipient.ie_indicator == 9
    )
    lines: list[dict[str, object]] = []
    for number, line in enumerate(document.items, start=1):
        outcome = line.tax_decision.outcome
        if outcome.ibs_cbs_classification_code is None:
            continue
        taxes = calculate_nfe_line(
            line.tax_decision, net_amount=line.net_amount.amount,
            regime=issuer.tax_regime, interstate_final_consumer=interstate_final_consumer,
            taxable_quantity=line.taxable_quantity or line.quantity,
        )
        lines.append({
            "numero": number,
            "cClassTrib": outcome.ibs_cbs_classification_code,
            "base": taxes.rtc_base,
            "vIBS": taxes.rtc_ibs_uf_amount + taxes.rtc_ibs_municipal_amount,
            "vCBS": taxes.rtc_cbs_amount,
        })
    return lines


def _json(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json(v) for v in value]
    return value


def run_nfe_rtc_shadow(
    client: RfbSimplesCalculatorClient, document: Any, *, model: str,
    occurred_at: datetime,
) -> dict[str, object]:
    """Return an evidence record; every failure becomes a status, never an exception."""
    record: dict[str, object] = {
        "document_id": getattr(document, "document_id", None),
        "model": model, "recorded_at": occurred_at.isoformat(),
        "authoritative": False,
    }
    try:
        lines = nfe_rtc_lines(document)
        if not lines:
            return {**record, "status": "skipped_no_rtc_classification"}
        crt = _crt(document)
        if crt not in {"1", "2"}:
            return {**record, "status": "skipped_outside_official_simples_scope", "crt": crt}
        request = build_request(
            operation_id=str(record["document_id"] or "shadow"),
            date=document.issued_at.date().isoformat(), document_type=model, crt=crt,
            items=[
                SimplesItem(
                    numero=int(str(line["numero"])), c_class_trib=str(line["cClassTrib"]),
                    base_calculo=Decimal(str(line["base"])).quantize(Decimal("0.01")),
                ) for line in lines
            ],
        )
        official = client.calculate(request)
        ours = {
            int(str(line["numero"])): {
                "vBC": Decimal(str(line["base"])),
                "vIBSSN": Decimal(str(line["vIBS"])),
                "vCBSSN": Decimal(str(line["vCBS"])),
            } for line in lines
        }
        divergences = compare_shadow(official, ours)
        return {
            **record,
            "status": "compared",
            "component_version": official.component_version,
            "official_states": {str(item.numero): item.state for item in official.items},
            "official_error_codes": {
                str(item.numero): list(item.error_codes)
                for item in official.items if item.error_codes
            },
            "nfcore": _json({str(k): v for k, v in ours.items()}),
            "divergences": [
                {"numero": d.numero, "field": d.field,
                 "nfcore": _json(d.nfcore), "official": _json(d.official)}
                for d in divergences
            ],
        }
    except Exception as exc:  # shadow must never affect issuance
        return {**record, "status": "shadow_unavailable", "error": type(exc).__name__}
