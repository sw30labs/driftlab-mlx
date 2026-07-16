"""Smoke test of the deterministic compliance core on seed traces."""

from pathlib import Path

from driftlab.baseline import BaselineCompiler, load_profile
from driftlab.ingest import load_jsonl
from driftlab.diff import BehavioralDiff
from driftlab.anomaly import AnomalyEngine
from driftlab.sensor import load_resource_jsonl

SEED = Path(__file__).resolve().parent.parent / "src" / "driftlab" / "seed"


def _run(agent: str):
    profile = load_profile(SEED / "baselines" / f"{agent}-baseline.json")
    policy = BaselineCompiler().compile(profile)
    events = load_jsonl(SEED / "traces" / f"{agent}-trace.jsonl", agent)
    records = load_resource_jsonl(SEED / "resource" / f"{agent}-resource.jsonl")
    findings = BehavioralDiff(policy, events, resource_records=records).run()
    anomalies = AnomalyEngine().build(
        findings, diff=BehavioralDiff(policy, events, resource_records=records))
    score = AnomalyEngine.score(anomalies)
    return policy, events, findings, anomalies, score


def test_loan_officer_drifts():
    policy, events, findings, anomalies, score = _run("loan-officer")
    controls = {a.control for a in anomalies}
    # Five drift families should be present.
    assert "DL-1" in controls   # unvetted wire_funds tool
    assert "DL-3" in controls   # HITL bypass on high-value
    assert "DL-4" in controls   # missing error fallback
    assert "DL-6" in controls   # autonomy budget exceeded
    assert "DL-8" in controls   # token budget exceeded (resource stream)
    # Autonomy over budget (100% > 40%).
    dl6 = [a for a in anomalies if a.control == "DL-6"][0]
    assert dl6.extra["rate"] > dl6.extra["budget"]
    # Score should be low.
    assert score < 50
    # At least one CRITICAL.
    assert any(a.severity.value == "critical" for a in anomalies)


def test_support_triage_clean():
    policy, events, findings, anomalies, score = _run("support-triage")
    # No critical anomalies, fully compliant.
    assert score == 100
    assert all(a.severity.value != "critical" for a in anomalies)
    assert len([a for a in anomalies if not a.waived]) == 0