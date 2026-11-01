"""Protect the canonical RTC schedule against future documentary state drift.

This is a structural consistency test, not a fiscal/legal certification.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEDULE = ROOT / "docs/NFCORE_RTC_MASTER_EXECUTION_SCHEDULE_2026-10-30.md"
LEDGER = ROOT / "docs/NFCORE_V1_RTC_BUILD_PENDING_EXECUTION_2026-10-31.md"

_STATUS = re.compile(r"^(?:IMPLEMENTED_PARTIAL|IMPLEMENTED_NOT_MERGED|PENDING|"
                     r"BLOCKED_EXTERNAL|BLOCKED_NORMATIVE|IN_PROGRESS|"
                     r"DONE_CERTIFIED_INTERNAL|DONE_CERTIFIED_OPERATIONAL)\\b")


def _canonical_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in SCHEDULE.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| **RTC-"):
            continue
        cells = [part.strip() for part in line.split("|")]
        name = cells[1].strip("*")
        assert name not in rows, f"duplicated canonical RTC WP: {name}"
        rows[name] = cells[5]
    return rows


def _operational_rows() -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    in_operational_table = False
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if line.startswith("## 2. Trilha RTC"):
            in_operational_table = True
            continue
        if in_operational_table and line.startswith("## 3."):
            break
        if not in_operational_table or not line.startswith("| NFC-EXEC-"):
            continue
        cells = [part.strip() for part in line.split("|")]
        execution_id = cells[1]
        assert execution_id not in rows, f"duplicated RTC ledger entry: {execution_id}"
        rows[execution_id] = (cells[2], cells[5])
    return rows


def _state(value: str) -> str:
    match = _STATUS.match(value)
    assert match, f"unknown RTC state: {value}"
    return match.group(0)


def test_rtc_schedule_covers_each_wp_exactly_once() -> None:
    rows = _canonical_rows()
    assert set(rows) == {f"RTC-{i:02d}" for i in range(13)}
    assert all(_state(state) for state in rows.values())


def test_rtc_ledger_matches_canonical_wp_state() -> None:
    canonical = _canonical_rows()
    operational = _operational_rows()
    assert set(operational) == {f"NFC-EXEC-{i:02d}" for i in range(1, 13)}
    for execution_id, (wp, state) in operational.items():
        expected = tuple(token.strip() for token in wp.split("/"))
        assert all(part in canonical for part in expected)
        actual_status = _state(state)
        for part in expected:
            assert _state(canonical[part]) == actual_status, (
                f"{execution_id}/{part}: ledger {actual_status} != schedule "
                f"{_state(canonical[part])}"
            )


def test_rtc_external_homologation_is_not_claimed_complete() -> None:
    canonical = _canonical_rows()
    assert _state(canonical["RTC-12"]) == "BLOCKED_EXTERNAL"
    checkpoint = ROOT / "docs/checkpoints/NFCORE_RTC_CURRENT_RECONCILIATION_2026-11-01.md"
    assert checkpoint.exists()
