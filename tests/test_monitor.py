"""Staleness policy math (regitel port) + estate runner behavior."""

from datetime import datetime, timedelta
from driftlab.clock import naive_utcnow

import pytest

from driftlab.config import Settings
from driftlab.monitor.policy import NEVER_CHECKED, select_due_agents
from driftlab.monitor.registry import load_registry, sync_registry
from driftlab.monitor.runner import run_monitor
from driftlab.store.db import AgentRow, Database, MonitorRunRow

INTERVALS = {1: 1, 3: 3}


@pytest.fixture()
def database(tmp_path):
    return Database(tmp_path / "db.sqlite3")


def _add_agent(database, agent_id, priority, last_checked_at):
    with database.session() as session:
        session.add(
            AgentRow(id=agent_id, name=agent_id, priority=priority, last_checked_at=last_checked_at)
        )


def test_never_checked_sorts_first(database):
    now = naive_utcnow()
    _add_agent(database, "checked", 1, now - timedelta(days=5))
    _add_agent(database, "fresh", 1, None)
    due = select_due_agents(database, INTERVALS, 7, now=now)
    assert [d.id for d in due] == ["fresh", "checked"]
    assert due[0].days_overdue == NEVER_CHECKED


def test_priority_bands_then_overdue(database):
    now = naive_utcnow()
    _add_agent(database, "p3-very-late", 3, now - timedelta(days=30))
    _add_agent(database, "p1-late", 1, now - timedelta(days=2))
    _add_agent(database, "p1-later", 1, now - timedelta(days=4))
    due = select_due_agents(database, INTERVALS, 7, now=now)
    assert [d.id for d in due] == ["p1-later", "p1-late", "p3-very-late"]


def test_not_due_is_filtered_and_force_includes(database):
    now = naive_utcnow()
    _add_agent(database, "recent", 1, now - timedelta(hours=2))
    assert select_due_agents(database, INTERVALS, 7, now=now) == []
    assert [d.id for d in select_due_agents(database, INTERVALS, 7, now=now, include_all=True)] == ["recent"]


def test_max_count_caps(database):
    now = naive_utcnow()
    for i in range(5):
        _add_agent(database, f"a{i}", 1, now - timedelta(days=3 + i))
    assert len(select_due_agents(database, INTERVALS, 7, now=now, max_count=2)) == 2


# ---------------------------------------------------------------------------
def test_registry_loads_seed(settings):
    specs = load_registry(settings.registry_path)
    assert [s.id for s in specs] == ["loan-officer", "support-triage"]
    assert all(s.baseline.exists() and s.traces.exists() for s in specs)


def test_monitor_run_end_to_end(settings):
    digest, meta = run_monitor(settings, force=True, send_email=False)
    checked = {item["id"]: item for item in digest.agents_checked}
    assert set(checked) == {"loan-officer", "support-triage"}
    assert checked["loan-officer"]["score"] == 5.0
    assert checked["support-triage"]["score"] == 100.0
    assert len(digest.new_critical) == 1
    assert len(digest.confirmed_drifts) == 4
    assert digest.has_alerts
    assert meta["email_skipped_reason"] == "--no-email"

    # staleness loop closed: immediate re-run selects nothing
    digest2, _ = run_monitor(settings, send_email=False)
    assert digest2.agents_checked == []
    assert not digest2.has_alerts


def test_monitor_email_failure_never_kills_cycle(settings):
    settings.email.enabled = True  # but SMTP entirely unconfigured
    digest, meta = run_monitor(settings, force=True, send_email=True)
    assert digest.agents_checked  # cycles ran and persisted
    assert meta["email_sent"] is False
    assert "not configured" in (meta["email_error"] or "")
    database = Database(settings.db_path)
    with database.session() as session:
        run = session.query(MonitorRunRow).order_by(MonitorRunRow.started_at.desc()).first()
    assert run.status == "completed"


def test_monitor_isolates_broken_agent(settings, tmp_path):
    registry = tmp_path / "agents.yaml"
    seed = settings.registry_path.parent
    registry.write_text(
        f"""
agents:
  - id: broken
    priority: 1
    baseline: {tmp_path}/missing-baseline.json
    traces: {tmp_path}/missing.jsonl
  - id: support-triage
    priority: 1
    baseline: {seed}/baselines/support-triage-profile.json
    traces: {seed}/traces/support-triage-clean.jsonl
""",
        encoding="utf-8",
    )
    my_settings = Settings(data_dir=tmp_path / "ws", registry_path=registry, llm_provider="none")
    digest, _ = run_monitor(my_settings, force=True, send_email=False)
    assert [e["agent_id"] for e in digest.errors] == ["broken"]
    assert [c["id"] for c in digest.agents_checked] == ["support-triage"]


def test_unknown_explicit_agent_reports_error(settings):
    digest, _ = run_monitor(settings, agents=["ghost"], send_email=False)
    assert digest.errors and digest.errors[0]["agent_id"] == "ghost"


def test_registry_rejects_duplicates(tmp_path):
    registry = tmp_path / "agents.yaml"
    registry.write_text(
        "agents:\n"
        "  - {id: a, baseline: b.json, traces: t.jsonl}\n"
        "  - {id: a, baseline: b.json, traces: t.jsonl}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_registry(registry)


def test_sync_registry_preserves_last_checked(settings, tmp_path):
    database = Database(tmp_path / "db.sqlite3")
    specs = load_registry(settings.registry_path)
    sync_registry(database, specs)
    stamp = naive_utcnow()
    with database.session() as session:
        session.get(AgentRow, "loan-officer").last_checked_at = stamp
    sync_registry(database, specs)  # re-sync must not reset the stamp
    with database.session() as session:
        assert session.get(AgentRow, "loan-officer").last_checked_at == stamp
