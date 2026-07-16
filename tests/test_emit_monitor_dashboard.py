"""Emit (OSCAL artifacts + report), monitor, and dashboard smoke tests."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from driftlab.baseline import BaselineCompiler, load_profile
from driftlab.ingest import load_jsonl
from driftlab.diff import BehavioralDiff
from driftlab.anomaly import AnomalyEngine
from driftlab.cycle import run_cycle
from driftlab.emit import emit_assessment_plan, emit_assessment_results, emit_report

SEED = Path(__file__).resolve().parent.parent / "src" / "driftlab" / "seed"


def _result(agent: str):
    profile = load_profile(SEED / "baselines" / f"{agent}-baseline.json")
    policy = BaselineCompiler().compile(profile)
    events = load_jsonl(SEED / "traces" / f"{agent}-trace.jsonl", agent)
    diff = BehavioralDiff(policy, events)
    anoms = AnomalyEngine().build(diff.run(), diff=diff)
    result = run_cycle(agent, str(SEED / "baselines" / f"{agent}-baseline.json"), events)
    return policy, result


def test_emit_artifacts(tmp_path):
    policy, result = _result("loan-officer")
    p1 = emit_assessment_plan("loan-officer", policy, tmp_path)
    p2 = emit_assessment_results("loan-officer", policy, result, tmp_path)
    p3 = emit_report("loan-officer", result, tmp_path)
    assert p1.exists() and p2.exists() and p3.exists()
    import json
    plan = json.loads(p1.read_text())
    assert plan["assessment-plan"]["metadata"]["version"] == "1.1.2"
    results = json.loads(p2.read_text())
    assert len(results["assessment-results"]["results"]["result"]) == 8  # DL-1..8
    satisfied = [r for r in results["assessment-results"]["results"]["result"]
                 if r["prop"][0]["value"] == "satisfied"]
    assert len(satisfied) < 7


def test_monitor_run(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTLAB_DATA_DIR", str(tmp_path / ".driftlab"))
    from driftlab.config import get_settings
    get_settings.cache_clear()
    from driftlab.monitor.runner import run_estate
    summary = run_estate(force=True, no_email=True)
    assert len(summary["ran"]) == 2
    scores = {r["agent"]: r["score"] for r in summary["ran"]}
    assert scores["support-triage"] == 100
    assert scores["loan-officer"] < 50


def test_dashboard_serves(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTLAB_DATA_DIR", str(tmp_path / ".driftlab"))
    from driftlab.config import get_settings
    get_settings.cache_clear()
    from driftlab.monitor.runner import run_estate
    from driftlab.dashboard.app import app
    run_estate(force=True, no_email=True)
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "DriftLab" in r.text
    r2 = client.get("/agent/loan-officer")
    assert r2.status_code == 200
    assert "loan-officer" in r2.text