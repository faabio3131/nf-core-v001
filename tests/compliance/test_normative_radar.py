"""T03 real pipeline with synthetic official-source HTML and session-authorized projection."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kordena_fiscal.compliance.normative_radar import REGISTRY, detect_signals, project_radar
from kordena_fiscal.compliance.normative_watch import (
    ECONOMY_SOURCES,
    SOURCES,
    NormativeWatchError,
    poll_normative_sources,
)
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment

WHEN = datetime(2026, 11, 20, tzinfo=UTC)
HTML = b"""<html><h2>Lei 123 de teste</h2>
<a href="/edital-anistia">Edital de anistia (fixture)</a>
<a href="/edital-refis">REFIS 2026 (fixture)</a>
<a href="/edital-parcelamento">Parcelamento especial (fixture)</a>
<a href="/edital-transacao">Edital de transacao tributaria (fixture)</a>
<script>var hidden = "anistia";</script></html>"""


def scope(tenant="a", unit="u", env=FiscalEnvironment.HOMOLOGATION, host="fm-nfcore"):
    return ExecutionScope(
        tenant_id=tenant, unit_id=unit, environment=env, host_namespace=host,
        correlation_id="test",
    )


def fixture_fetch(url: str) -> bytes:
    return HTML if url in ECONOMY_SOURCES.values() else b"<h1>Portal oficial</h1>"


def test_all_categories_and_scoped_alerts_restart_and_replay(tmp_path: Path):
    state = tmp_path / "state.json"
    first = poll_normative_sources(
        state_path=state, fetch=fixture_fetch, observed_at=WHEN, economy=True,
    )
    assert len(first) == len(REGISTRY) == 7
    assert all(x["status"] == "FIRST_OBSERVATION_REVIEW_REQUIRED" for x in first)
    result = project_radar(state, scope(), now=WHEN)
    assert result["status"] == "review_required"
    assert {x["category"] for x in result["alerts"]} == {
        "alteracao_portal", "legislacao", "anistia", "refis", "parcelamento", "transacao",
    }
    for alert in result["alerts"]:
        assert alert["source_url"] in REGISTRY.values()
        assert alert["source_current"] is True
        assert alert["status"] == "review_required"
        assert alert["eligibility_checked"] is False
        assert alert["normative_approved"] is False
        assert alert["fiscal_production_approved"] is False
    assert "fixture)" not in state.read_text()
    assert any(x["document_url"].endswith("/edital-anistia") for x in result["alerts"])
    ids = {x["alert_id"] for x in result["alerts"]}
    for other in (scope("b"), scope(unit="other"), scope(env=FiscalEnvironment.PRODUCTION),
                  scope(host="other")):
        foreign = project_radar(state, other, now=WHEN)["alerts"]
        assert ids.isdisjoint(x["alert_id"] for x in foreign)
    replay = poll_normative_sources(
        state_path=state, fetch=fixture_fetch, observed_at=WHEN + timedelta(days=1), economy=True,
    )
    assert all(x["status"] == "UNCHANGED" for x in replay)
    again = project_radar(state, scope(), now=WHEN + timedelta(days=1))
    assert ids == {x["alert_id"] for x in again["alerts"]}
    assert all(x["observed_at"] == WHEN.isoformat() for x in again["alerts"])


def test_change_signals_and_partial_failure_are_not_approval(tmp_path: Path):
    state = tmp_path / "state.json"
    poll_normative_sources(
        state_path=state, fetch=fixture_fetch, observed_at=WHEN, economy=True,
    )
    old = project_radar(state, scope(), now=WHEN)["alerts"]

    def changed(url):
        if url == REGISTRY["PGFN_EDITAIS"]:
            raise NormativeWatchError("source down")
        if url == REGISTRY["RFB_TRANSACAO"]:
            return HTML.replace(b"REFIS 2026", b"REFIS 2027")
        return fixture_fetch(url)

    later = WHEN + timedelta(days=1)
    events = poll_normative_sources(
        state_path=state, fetch=changed, observed_at=later, economy=True,
    )
    assert any(x["status"] == "SOURCE_UNAVAILABLE" for x in events)
    assert any(x["status"] == "PORTAL_CONTENT_CHANGED_REVIEW_REQUIRED" for x in events)
    result = project_radar(state, scope(), now=later)
    assert result["status"] == "partial_or_unavailable"
    assert all(not x["source_current"] for x in result["alerts"] if x["source"] == "PGFN_EDITAIS")
    assert all(not x["source_current"] for x in project_radar(
        state, scope(), now=later + timedelta(days=3),
    )["alerts"])
    old_refis = next(x for x in old if x["category"] == "refis" and x["source"] == "RFB_TRANSACAO")
    new_refis = next(x for x in result["alerts"] if x["category"] == "refis"
                     and x["source"] == "RFB_TRANSACAO")
    assert old_refis["alert_id"] != new_refis["alert_id"]
    assert new_refis["observed_at"] == later.isoformat()
    old_anistia = next(x for x in old if x["category"] == "anistia"
                       and x["source"] == "RFB_TRANSACAO")
    new_anistia = next(x for x in result["alerts"] if x["category"] == "anistia"
                       and x["source"] == "RFB_TRANSACAO")
    assert old_anistia["alert_id"] == new_anistia["alert_id"]


def test_v1_checkpoint_upgrade_and_corruption_fail_closed(tmp_path: Path):
    state = tmp_path / "state.json"
    poll_normative_sources(state_path=state, fetch=fixture_fetch, observed_at=WHEN)
    legacy = json.loads(state.read_text())
    assert set(legacy["hashes"]) == set(SOURCES)
    poll_normative_sources(
        state_path=state, fetch=fixture_fetch, observed_at=WHEN, economy=True,
    )
    upgraded = json.loads(state.read_text())
    assert upgraded["schema_version"] == 2
    assert all(upgraded["hashes"][key] == digest for key, digest in legacy["hashes"].items())
    upgraded["alerts"]["NFE"][0]["source_sha256"] = "f" * 64
    state.write_text(json.dumps(upgraded))
    invalid = state.read_bytes()
    with pytest.raises(NormativeWatchError):
        project_radar(state, scope(), now=WHEN)
    with pytest.raises(NormativeWatchError):
        poll_normative_sources(
            state_path=state, fetch=fixture_fetch, observed_at=WHEN, economy=True,
        )
    assert state.read_bytes() == invalid


def test_untrusted_markup_and_links_are_not_exposed():
    signals = detect_signals(
        b'<script><a href="/fake">REFIS</a></script>'
        b'<a href="https://evil.test/refis?secret=1">Edital de anistia</a>'
        b'<a href="/official?private=1#fragment">Parcelamento</a>',
        REGISTRY["PGFN_EDITAIS"],
    )
    assert {kind for kind, _, _ in signals} == {"anistia", "parcelamento"}
    assert all("evil.test" not in url and "private" not in url for _, _, url in signals)


def test_missing_cache_and_parallel_lock(tmp_path: Path):
    state = tmp_path / "state.json"
    assert project_radar(state, scope(), now=WHEN)["status"] == "partial_or_unavailable"
    assert project_radar(state, scope(), now=WHEN)["alerts"] == []
    (tmp_path / "state.json.lock").write_text("lock")
    with pytest.raises(NormativeWatchError):
        poll_normative_sources(
            state_path=state, fetch=fixture_fetch, observed_at=WHEN, economy=True,
        )
    assert not state.exists()
