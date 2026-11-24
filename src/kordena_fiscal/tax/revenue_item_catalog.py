"""Exact item matching against the immutable, reviewed T06 rule snapshot."""

from __future__ import annotations

import hashlib
import json
import re
from calendar import monthrange
from datetime import date
from importlib.resources import files
from typing import Any

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.simples_nacional import UF_CODES, Activity
from kordena_fiscal.tax.simples_segregation import (
    TRANSITION_SPECIAL_TAXES,
    FederalTreatment,
    LocalTreatment,
    Market,
)

Key = tuple[str, str | None, str, str, str, str, str]
Treatment = tuple[FederalTreatment, LocalTreatment, str, tuple[str, ...] | None]


def _key(item: dict[str, Any], uf: str) -> Key:
    for field, pattern in (
        ("ncm", r"[0-9]{8}"),
        ("cfop", r"[567][0-9]{3}"),
        ("operation_context", r"[A-Za-z0-9_.:-]{1,100}"),
    ):
        if not isinstance(item.get(field), str) or not re.fullmatch(pattern, item[field]):
            raise FiscalValidationError(f"invalid item {field}")
    cest = item["cest"]  # Explicit null means this reviewed operation has no CEST.
    if cest is not None and (not isinstance(cest, str) or not re.fullmatch(r"[0-9]{7}", cest)):
        raise FiscalValidationError("invalid item CEST")
    activity, market = Activity(item["activity"]), Market(item["market"])
    if uf not in UF_CODES or (item["cfop"][0] == "7") != (market is Market.EXPORT):
        raise FiscalValidationError("item operation jurisdiction or market mismatch")
    return item["ncm"], cest, item["cfop"], uf, activity, market, item["operation_context"]


class ReviewedItemCatalog:
    def __init__(self, rows: object, competence: date, sources: set[str]) -> None:
        if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
            raise FiscalValidationError("bounded reviewed item catalog required")
        self.matches: dict[Key, list[Treatment | None]] = {}
        end = competence.replace(day=monthrange(competence.year, competence.month)[1])
        for row in rows:
            key = _key(row, row["uf"])
            start, stop = (
                date.fromisoformat(row["valid_from"]),
                date.fromisoformat(row["valid_until"]),
            )
            if (
                stop <= start
                or row["source_url"] not in sources
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", row["rule_reference"])
            ):
                raise FiscalValidationError("invalid item rule period or reviewed citation")
            transition = None
            if competence.year == 2027 and start <= end and stop > competence:
                parts = row.get("transition_treatments")
                if not isinstance(parts, dict) or set(parts) != set(TRANSITION_SPECIAL_TAXES):
                    raise FiscalValidationError("reviewed per-tax item rules required for 2027")
                transition = tuple(parts[tax] for tax in TRANSITION_SPECIAL_TAXES)
            treatment = (
                FederalTreatment(row["federal"]),
                LocalTreatment(row["local"]),
                row["rule_reference"],
                transition,
            )
            if start <= end and stop > competence:
                self.matches.setdefault(key, []).append(
                    treatment if start <= competence and stop > end else None
                )

    def resolve(self, item: dict[str, Any], uf: str) -> Treatment:
        if {"federal", "local", "treatment_reference", "transition_treatments"} & item.keys():
            raise FiscalValidationError("coded item cannot override reviewed treatment")
        matches = self.matches.get(_key(item, uf), [])
        if len(matches) == 1 and matches[0] is not None:
            return matches[0]
        return FederalTreatment.UNKNOWN, LocalTreatment.UNKNOWN, "item_rule_unresolved", None


def materialize_item_release(policy: dict[str, Any], competence: date) -> dict[str, Any]:
    """Expand an explicitly pinned release inside the reviewed import transaction."""
    if "item_catalog_sha256" not in policy:
        return policy
    data = files("kordena_fiscal.tax").joinpath("official/sp_2026s1_v1.json").read_bytes()
    if (
        policy["item_catalog_sha256"] != hashlib.sha256(data).hexdigest()
        or "item_rules" in policy
        or policy.get("review_status") != "reviewed"
    ):
        raise FiscalValidationError("invalid reviewed item release pin or conflicting item rules")
    pack = json.loads(data)
    month = competence.isoformat()
    rules = [r for r in pack["item_rules"] if r["valid_from"] <= month < r["valid_until"]]
    if not rules:
        raise FiscalValidationError("item release unavailable for competence")
    # Require the responsible reviewer to supply the exact bytes of every
    # supporting source, including corroboration of the federal treatment.
    citations = policy.get("legal_citations")
    if not isinstance(citations, list):
        raise FiscalValidationError("item release requires reviewed citations")
    sources = {(c.get("source_url"), c.get("source_sha256"))
               for c in citations if isinstance(c, dict)
               and isinstance(c.get("source_url"), str) and isinstance(c.get("source_sha256"), str)}
    for key in {key for rule in rules for key in rule["sources"]}:
        source = pack["sources"][key]
        if (source["url"], source["sha256"]) not in sources:
            raise FiscalValidationError("item release citation missing or changed")
    return {**policy, "item_rules": rules}
